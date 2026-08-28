#!/usr/bin/env python3
"""
worker.py — Meteo-France NC radar REFLECTIVITE -> Supabase
3 sources : NC-MOSAIC, Nouméa (station 94), Lifou (station 96)
"""
import os, sys, gzip, io, json, tempfile, datetime as dt
import numpy as np
import requests
from PIL import Image
import mf_radar

# Ancienne base (v1)
# BASE = "https://public-api.meteofrance.fr/public/DPRadar/v1"

# Nouvelle base (sans v1 pour la mosaïque)
BASE_MOSAIC   = "https://public-api.meteofrance.fr/public/DPRadar"
BASE_STATIONS = "https://public-api.meteofrance.fr/public/DPRadar/v1"

SOURCES = [
    {"key": "NC-MOSAIC", "name": "New Caledonia composite",
     "url": f"{BASE_MOSAIC}/mosaiques/NOUVELLE-CALEDONIE/observations/REFLECTIVITE/produit?maille=1000"},
    {"key": "NOUMEA",    "name": "Noumea radar",
     "url": f"{BASE_STATIONS}/stations/94/observations/REFLECTIVITE/produit"},
    {"key": "LIFOU",     "name": "Lifou radar",
     "url": f"{BASE_STATIONS}/stations/96/observations/REFLECTIVITE/produit"},
]

MF_API_KEY      = os.environ["MF_API_KEY"]
SUPABASE_URL    = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY    = os.environ["SUPABASE_KEY"]
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "radar")

CLEVS = np.array([8, 16, 20, 24, 28, 32, 36, 40, 44, 48, 99])
RGB   = np.array([
    (58,166,255),(30,111,255),(27,209,27),(19,165,19),(10,122,10),
    (255,240,0),(255,176,0),(255,90,0),(255,0,0),(176,0,0)
], dtype=np.uint8)


def log(*a):
    print(dt.datetime.now(dt.timezone.utc).isoformat(), *a, flush=True)


def download_bufr(url: str):
    r = requests.get(
        url,
        headers={"apikey": MF_API_KEY, "accept": "*/*"},
        timeout=60
    )
    # 404 = radar indisponible temporairement → avertissement, pas une erreur
    if r.status_code == 404:
        log("WARN  pas de produit disponible (404) — skip")
        return None

    r.raise_for_status()
    raw = r.content

    # Décompression gzip (magic \x1f\x8b)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    # Décompression LZW/compress (magic \x1f\x9d) — parfois renvoyé par MF
    elif raw[:2] == b"\x1f\x9d":
        import unlzw3
        raw = unlzw3.unlzw(raw)

    if raw[:4] != b"BUFR":
        raise RuntimeError(f"payload inattendu (premiers octets : {raw[:8]!r})")

    fd, path = tempfile.mkstemp(suffix="_bufr")
    os.write(fd, raw)
    os.close(fd)
    return path


def make_overlay(dbz, clat, clon, dx, dy):
    M = 111320.0
    ny, nx = dbz.shape
    latN, latS = clat, clat - ny * dy / M
    lat_mid = (latN + latS) / 2.0
    lonW, lonE = clon, clon + nx * dx / (M * np.cos(np.radians(lat_mid)))
    tlat = np.linspace(latN, latS, ny)
    tlon = np.linspace(lonW, lonE, nx)
    LON, LAT = np.meshgrid(tlon, tlat)
    sr = np.round((clat - LAT) * M / dy).astype(int)
    sc = np.round((LON - clon) * M * np.cos(np.radians(LAT)) / dx).astype(int)
    ok = (sr >= 0) & (sr < ny) & (sc >= 0) & (sc < nx)
    samp = np.full((ny, nx), np.nan)
    samp[ok] = dbz[sr[ok], sc[ok]]
    rgba = np.zeros((ny, nx, 4), dtype=np.uint8)
    ech = np.isfinite(samp)
    idx = np.clip(np.digitize(samp[ech], CLEVS) - 1, 0, len(RGB) - 1)
    rgba[ech, :3] = RGB[idx]
    rgba[ech, 3] = 210
    bbox = {
        "south": round(float(latS), 5), "north": round(float(latN), 5),
        "west":  round(float(lonW), 5), "east":  round(float(lonE), 5)
    }
    return rgba, bbox


def upload_png(path_in_bucket: str, png_bytes: bytes):
    url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{path_in_bucket}"
    h = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "apikey": SUPABASE_KEY,
        "Content-Type": "image/png",
        "x-upsert": "true"
    }
    requests.post(url, headers=h, data=png_bytes, timeout=60).raise_for_status()


def upsert_frame(row: dict):
    url = f"{SUPABASE_URL}/rest/v1/radar_frames?on_conflict=source,observed_at"
    h = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "apikey": SUPABASE_KEY,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    requests.post(url, headers=h, data=json.dumps(row), timeout=60).raise_for_status()


def process(src: dict):
    bufr = download_bufr(src["url"])
    if bufr is None:        # 404 → skip proprement
        return

    try:
        r = mf_radar.decode_file(bufr)
    finally:
        os.remove(bufr)

    dbz = mf_radar.despeckle(r["dbz"], min_neighbors=2)
    rgba, bbox = make_overlay(dbz, r["corner_lat"], r["corner_lon"], *r["pixel_m"])

    obs = r["observed_at"]
    key = f"{src['key'].lower()}/{obs:%Y/%m/%d}/{obs:%H%M}.png"

    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG")
    png = buf.getvalue()

    upload_png(key, png)
    upsert_frame({
        "source": src["key"],
        "name": src["name"],
        "product": "REFLECTIVITE",
        "observed_at": obs.isoformat(),
        "image_path": key,
        "bbox": bbox,
        "nx": r["nx"],
        "ny": r["ny"],
        "echo_pixels": int(np.isfinite(dbz).sum()),
    })
    log(f"OK {src['key']:9s} {obs:%H:%M} -> {key} ({len(png)}B, "
        f"{int(np.isfinite(dbz).sum())} echo)")


def main():
    rc = 0
    for src in SOURCES:
        try:
            process(src)
        except Exception as e:
            log(f"ERROR {src['key']}: {e!r}")
            rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
