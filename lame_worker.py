#!/usr/bin/env python3
"""
lame_worker.py — Lame d'eau radar NC (Météo-France) -> cumuls de pluie 1 h / 6 h / 24 h.

À chaque run (toutes les 10 min, après le worker radar) :
  1. télécharge le paquet radar du dernier quart d'heure (API DPPaquetRadar) ;
  2. en extrait les créneaux de lame d'eau NC 1 km (IPNC21) pas encore archivés,
     les décode et les archive (grille 5 min, ~14 Ko) dans le bucket 'rain' ;
  3. met à jour les trois cumuls glissants PAR DIFFÉRENCE (ajout des nouveaux
     créneaux, retrait de ceux sortis de la fenêtre) pour limiter le trafic Supabase ;
  4. produit une heatmap PNG géoréférencée par période et met à jour rain_accum.

Unité : 1/100 mm (65535 = hors couverture radar).
Env : MF_API_KEY, SUPABASE_URL, SUPABASE_KEY
"""
import io, os, re, sys, gzip, tarfile, tempfile, datetime as dt
import numpy as np
import requests
from PIL import Image
import mf_radar
from storage_cleanup import cleanup_storage

PAQUET_URL = "https://public-api.meteofrance.fr/public/DPPaquetRadar/v1/mosaique/paquet"
FILE_RE    = re.compile(r"T_IPNC21_C_LFPW_(\d{14})\.bufr\.gz$")
BUCKET     = "rain"
NODATA     = mf_radar.LAME_NODATA
STEP_MIN   = 5
PERIODS    = {"1h": 60, "6h": 360, "24h": 1440}

# Échelle unique pour les trois périodes (mm) : rien n'est représenté sous 1 mm
COLORS = ["#c6ecff", "#8fd3ff", "#4aa8ff", "#1f6fe0", "#20b04a", "#8fd13f",
          "#f5e642", "#f7a531", "#ef5b28", "#d11c3c", "#9b1ea8"]
SCALE_MM = [1, 2, 5, 10, 15, 20, 30, 50, 75, 100, 150]
THRESHOLDS = {p: SCALE_MM for p in PERIODS}
# Opacité croissante avec l'intensité : les faibles cumuls (bleus) laissent voir la carte,
# les fortes pluies sont opaques.            1   2    5    10   15   20   30   50   75  100  150 mm
ALPHAS = [110, 130, 150, 175, 200, 220, 240, 250, 255, 255, 255]
NOCOV_RGBA = (60, 70, 80, 90)          # zone hors couverture radar : gris translucide


def log(*a):
    print(dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), *a, flush=True)

def ep(t):     return int(t.timestamp())
def fromep(e): return dt.datetime.fromtimestamp(e, dt.timezone.utc)
def parse_ts(s): return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)

class MissingGrid(Exception):
    pass


# ── Accès Supabase (REST + Storage) ─────────────────────────────────────────
class Supa:
    def __init__(self, url, key):
        self.url, self.key = url.rstrip("/"), key
        self.h = {"Authorization": f"Bearer {key}", "apikey": key}

    def select(self, table, params):
        r = requests.get(f"{self.url}/rest/v1/{table}", headers=self.h, params=params, timeout=60)
        r.raise_for_status(); return r.json()

    def upsert(self, table, rows, conflict):
        h = dict(self.h, **{"Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"})
        requests.post(f"{self.url}/rest/v1/{table}?on_conflict={conflict}", headers=h,
                      json=rows, timeout=60).raise_for_status()

    def upload(self, path, data, ctype):
        h = dict(self.h, **{"Content-Type": ctype, "x-upsert": "true"})
        requests.post(f"{self.url}/storage/v1/object/{BUCKET}/{path}", headers=h,
                      data=data, timeout=60).raise_for_status()

    def download(self, path):
        r = requests.get(f"{self.url}/storage/v1/object/authenticated/{BUCKET}/{path}",
                         headers=self.h, timeout=60)
        if r.status_code in (400, 404):
            raise MissingGrid(path)
        r.raise_for_status(); return r.content

    def delete(self, paths):
        if paths:
            requests.delete(f"{self.url}/storage/v1/object/{BUCKET}", headers=self.h,
                            json={"prefixes": list(paths)}, timeout=60).raise_for_status()


# ── Sérialisation ───────────────────────────────────────────────────────────
def npz_bytes(**arrays):
    b = io.BytesIO(); np.savez_compressed(b, **arrays); return b.getvalue()

def npz_load(data):
    with np.load(io.BytesIO(data)) as z:
        return {k: z[k] for k in z.files}

def rain_of(grid):
    """Grille 5 min -> pluie en 1/100 mm (hors couverture = 0), en int64 pour sommer."""
    return np.where(grid == NODATA, 0, grid).astype(np.int64)


# ── 1. Paquet radar ─────────────────────────────────────────────────────────
def extract_slots(paquet_bytes):
    """[(datetime UTC du créneau, octets BUFR)] de la lame d'eau NC contenue dans le paquet."""
    items = []
    with tarfile.open(fileobj=io.BytesIO(paquet_bytes), mode="r:*") as tar:
        for m in tar.getmembers():
            mt = FILE_RE.search(m.name)
            if not mt:
                continue
            raw = tar.extractfile(m).read()
            raw = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
            if raw[:4] != b"BUFR":
                log(f"WARN {m.name} : contenu inattendu"); continue
            t = dt.datetime.strptime(mt.group(1), "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
            items.append((t, raw))
    return sorted(items)

def fetch_paquet(api_key):
    r = requests.get(PAQUET_URL, headers={"apikey": api_key, "accept": "*/*"}, timeout=180)
    if r.status_code == 404:
        log("WARN paquet indisponible (404)"); return []
    r.raise_for_status()
    return extract_slots(r.content)

def decode_bufr_bytes(raw):
    fd, path = tempfile.mkstemp(suffix="_bufr")
    try:
        os.write(fd, raw); os.close(fd)
        return mf_radar.decode_lame(path)
    finally:
        os.remove(path)


# ── 2. Archivage des créneaux ───────────────────────────────────────────────
def slot_path(t):
    return f"slots/{t:%Y/%m/%d/%H%M}.npz"

def store_slots(supa, decoded):
    rows = []
    for s in decoded:
        t, g = s["observed_at"], s["grid"]
        supa.upload(slot_path(t), npz_bytes(grid=g), "application/octet-stream")
        rain = rain_of(g)
        rows.append({"observed_at": t.isoformat(), "grid_path": slot_path(t),
                     "rain_pixels": int((rain > 0).sum()), "max_mm": float(rain.max()) / 100})
    if rows:
        supa.upsert("rain_slots", rows, "observed_at")


# ── 3. Cumuls glissants ─────────────────────────────────────────────────────
def update_period(supa, period, minutes, slots_db, t_end, cache, old_row):
    """Met à jour l'accumulateur d'une période -> (acc int64, créneaux inclus, attendus)."""
    def grid(e):
        if e not in cache:
            if e not in slots_db:
                raise MissingGrid(e)
            cache[e] = npz_load(supa.download(slots_db[e]))["grid"]
        return cache[e]

    lo = ep(t_end) - minutes * 60                    # fenêtre ]t_end - W, t_end]
    target = {e for e in slots_db if lo < e <= ep(t_end)}
    acc = None

    if old_row and old_row.get("state_path"):
        try:
            st = npz_load(supa.download(old_row["state_path"]))
            acc, included = st["acc"].astype(np.int64), set(st["included"].tolist())
            for e in sorted(target - included):
                acc += rain_of(grid(e))
            for e in sorted(included - target):
                acc -= rain_of(grid(e))
            included = set(target)
        except MissingGrid as ex:
            log(f"INFO {period} : reconstruction complète ({ex})")
            acc = None

    if acc is None:                                   # pas d'état, ou état inutilisable
        included = set()
        for e in sorted(target):
            try:
                g = rain_of(grid(e))
            except MissingGrid:
                continue
            acc = g if acc is None else acc + g
            included.add(e)
        if acc is None:
            acc = np.zeros(grid(ep(t_end)).shape, np.int64)

    return np.clip(acc, 0, None), included, minutes // STEP_MIN


def render(period, acc, cov, geom):
    mm = np.where(cov, acc / 100.0, np.nan)
    samp, bbox = mf_radar.resample_webmercator(geom, mm)
    H, W = samp.shape
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[np.isnan(samp)] = NOCOV_RGBA
    thr = np.array(THRESHOLDS[period])
    wet = np.isfinite(samp) & (samp >= thr[0])
    idx = np.clip(np.digitize(samp[wet], thr) - 1, 0, len(COLORS) - 1)
    rgb = np.array([[int(c[i:i+2], 16) for i in (1, 3, 5)] for c in COLORS], np.uint8)
    rgba[wet, :3] = rgb[idx]; rgba[wet, 3] = np.array(ALPHAS, np.uint8)[idx]
    b = io.BytesIO(); Image.fromarray(rgba, "RGBA").save(b, "PNG", optimize=True)
    legend = [{"min": t, "color": c, "alpha": a} for t, c, a in zip(THRESHOLDS[period], COLORS, ALPHAS)]
    return b.getvalue(), bbox, legend


def update_all(supa, cache, geom):
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=26)).isoformat()
    slots_db = {ep(parse_ts(r["observed_at"])): r["grid_path"]
                for r in supa.select("rain_slots", {"select": "observed_at,grid_path",
                                                     "observed_at": f"gte.{since}"})}
    if not slots_db:
        log("INFO aucun créneau archivé"); return
    t_end = fromep(max(slots_db))
    rows = {r["period"]: r for r in supa.select("rain_accum", {"select": "*"})}
    last = cache.get(ep(t_end))
    if last is None:
        last = npz_load(supa.download(slots_db[ep(t_end)]))["grid"]
    cov = last != NODATA
    stamp = f"{t_end:%Y%m%d%H%M}"

    for period, minutes in PERIODS.items():
        old = rows.get(period)
        acc, included, expected = update_period(supa, period, minutes, slots_db, t_end, cache, old)
        png, bbox, legend = render(period, acc, cov, geom)
        img_path, st_path = f"accum/{period}/{stamp}.png", f"state/{period}/{stamp}.npz"
        supa.upload(img_path, png, "image/png")
        supa.upload(st_path, npz_bytes(acc=acc.astype(np.uint32),
                                       included=np.array(sorted(included), np.int64)),
                    "application/octet-stream")
        mx = float(acc[cov].max() / 100) if cov.any() else 0.0
        supa.upsert("rain_accum", [{
            "period": period,
            "window_start": (t_end - dt.timedelta(minutes=minutes - STEP_MIN)).isoformat(),
            "window_end": t_end.isoformat(),
            "n_expected": expected, "n_received": len(included),
            "image_path": img_path, "state_path": st_path, "bbox": bbox, "legend": legend,
            "max_mm": mx, "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }], "period")
        if old:                                        # retirer les versions précédentes
            supa.delete([p for p in (old.get("image_path"), old.get("state_path"))
                         if p and p not in (img_path, st_path)])
        log(f"OK {period:3s} {len(included):3d}/{expected} créneaux  max {mx:.1f} mm -> {img_path}")


# ── Programme principal ─────────────────────────────────────────────────────
def run(supa, items):
    """items : [(datetime, octets BUFR)] issus du paquet."""
    known = set()
    if items:
        lo = min(t for t, _ in items).isoformat()
        known = {ep(parse_ts(r["observed_at"]))
                 for r in supa.select("rain_slots", {"select": "observed_at", "observed_at": f"gte.{lo}"})}
    cache, decoded, geom = {}, [], None
    for t, raw in items:
        if ep(t) in known:
            continue
        s = decode_bufr_bytes(raw)
        decoded.append(s); cache[ep(s["observed_at"])] = s["grid"]; geom = s["geom"]
        log(f"NEW créneau {s['observed_at']:%H:%M} UTC  max {rain_of(s['grid']).max()/100:.2f} mm")
    if not decoded:
        log("INFO aucun nouveau créneau"); return
    store_slots(supa, decoded)
    update_all(supa, cache, geom)


def main():
    supa = Supa(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    run(supa, fetch_paquet(os.environ["MF_API_KEY"]))
    try:
        cleanup_storage(supa.url, supa.key, BUCKET, ["slots"], log=log)
    except Exception as e:
        log(f"WARN cleanup: {e!r}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ERROR lame: {e!r}"); sys.exit(1)
