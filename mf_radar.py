"""
mf_radar.py — décodeur Météo-France radar BUFR (centre 85).

Compatible BUFR édition 2 (ancien format, avant juin 2026)
     ET BUFR édition 4 (nouveau format, après migration juin 2026).

Interface publique :
    decode_file(path, tables_dir=None) -> dict avec :
        observed_at   : datetime UTC
        nx, ny        : dimensions de la grille
        pixel_m       : (dx, dy) en mètres
        corner_lat/lon: coin Nord-Ouest
        proj_type, ref_lat, central_lon, scan_mode
        radars        : liste de (lat, lon) des radars contributeurs
        codes         : tableau uint16 ny×nx (format édition 2 uniquement)
        dbz           : tableau float ny×nx en dBZ (NaN = pas de données)

    despeckle(dbz, min_neighbors=2) -> dbz filtré
"""
import io, os, contextlib, datetime as _dt
import numpy as np

_NS = None

def _load_engine():
    global _NS
    if _NS is not None:
        return _NS
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, 'mflib', '_refdecoder.py')).read()
    ns = {}
    exec(compile(src, '_refdecoder.py', 'exec'), ns)
    _NS = ns
    return ns


def decode_file(path, tables_dir=None):
    ns = _load_engine()
    here = os.path.dirname(os.path.abspath(__file__))
    if tables_dir is None:
        tables_dir = os.path.join(here, 'mflib', 'tables')
    ns.update({
        'DIR_PATH':       os.path.dirname(os.path.abspath(path)) or '.',
        'FILE_NAME':      os.path.basename(path),
        'DIR_PATH_TABLE': os.path.abspath(tables_dir),
        'affiche_descriptors': False,
        'FIC_TAB_B':       'bufrtabb_{master}.csv',
        'FIC_TAB_D':       'bufrtabd_{master}.csv',
        'FIC_LOCAL_TAB_B': 'localtabb_{center}_{local}.csv',
        'FIC_LOCAL_TAB_D': 'localtabd_{center}_{local}.csv',
    })
    with contextlib.redirect_stdout(io.StringIO()):
        ns['deco_bufr']()
    d = ns['datas_messages'][0]

    def first(k, default=None):
        v = d.get(k)
        return v[0] if v else default

    nx   = int(first('Number of pixels per row'))
    ny   = int(first('Number of pixels per column'))
    ngrid = nx * ny

    # ── Détection du format ────────────────────────────────────────────────
    # Édition 4 (nouveau format, après migration juin 2026) :
    #   La grille est dans 'Horizontal reflectivity', directement en dBZ.
    #   Valeurs sentinelles : -40.0 = no-data, >100 = fill/hors-échelle.
    #
    # Édition 2 (ancien format) :
    #   La grille est dans 'Pixel value (8 bits)' ou 'Pixel value (4 bits)',
    #   codes entiers 0-255 à convertir via table de calibration.

    if 'Horizontal reflectivity' in d and len(d['Horizontal reflectivity']) >= ngrid:
        # ── Format édition 4 ───────────────────────────────────────────────
        raw = np.array(d['Horizontal reflectivity'][-ngrid:], dtype=float)
        dbz_flat = raw.copy()
        # Masquer les sentinelles
        dbz_flat[raw <= -40.0] = np.nan   # no-data / hors-portée
        dbz_flat[raw >  100.0] = np.nan   # fill (164.7 = missing MF)
        # Valeurs négatives entre -40 et 0 = bruit/clutter → masquer
        dbz_flat[(raw > -40.0) & (raw < 0.0)] = np.nan
        grid_codes = None

    else:
        # ── Format édition 2 (ancienne structure) ─────────────────────────
        pv = d.get('Pixel value (8 bits)')
        if not pv or len(pv) < ngrid:
            pv = d.get('Pixel value (4 bits)')
        if not pv or len(pv) < ngrid:
            raise ValueError(f"no pixel grid of size {ngrid} found")

        codes = np.array(pv[-ngrid:], dtype=np.uint16)
        refl  = np.array(d['Reflectivite pour la valeur du pixel'], dtype=float)
        nlev  = len(refl) // 2
        lut   = np.full(256, np.nan)
        for c in range(nlev):
            lut[c] = refl[2 * c + 1]
        lut[0] = np.nan
        grid_codes = codes.reshape((nx, ny), order='F').T
        dbz_flat   = lut[grid_codes].flatten()

    # ── Reshape en grille (ny, nx), row 0 = Nord ──────────────────────────
    # Scan mode 224 = colonne-major, j S→N, i E→O → reshape F puis transpose
    dbz = dbz_flat.reshape((nx, ny), order='F').T    # (ny, nx)

    # ── Timestamp ─────────────────────────────────────────────────────────
    obs = _dt.datetime(
        int(first('Year')), int(first('Month')), int(first('Day')),
        int(first('Hour')), int(first('Minute')), int(first('Second') or 0),
        tzinfo=_dt.timezone.utc
    )

    # ── Géométrie ─────────────────────────────────────────────────────────
    M    = 111320.0
    lats = d.get('Latitude (high accuracy)',  [])
    lons = d.get('Longitude (high accuracy)', [])

    dN_key = "Distance Nord-Sud du coin Nord-Ouest de l'image au radar"
    dW_key = "Distance Ouest-Est du coin Nord-Ouest de l'image au radar"

    if dN_key in d:
        # Station individuelle : radar au centre, coin NW calculé
        lat0, lon0 = lats[0], lons[0]
        corner_lat = lat0 + first(dN_key) / M
        corner_lon = lon0 - first(dW_key) / (M * np.cos(np.radians(lat0)))
        radars = [(lat0, lon0)]
        offsets_m = (first(dN_key), first(dW_key))
    else:
        # Mosaïque : premier point = coin NW, les suivants = radars
        corner_lat, corner_lon = lats[0], lons[0]
        radars = list(zip(lats[1:], lons[1:]))
        offsets_m = None

    return dict(
        observed_at = obs,
        nx = nx, ny = ny,
        pixel_m     = (first('Pixel size on horizontal - 1'),
                       first('Pixel size on horizontal - 2')),
        corner_lat  = corner_lat,
        corner_lon  = corner_lon,
        proj_type   = first('Projection type'),
        ref_lat     = first('Latitude de reference'),
        central_lon = first("Longitude du meridien parallele a l'axe des Y"),
        scan_mode   = first('Mode de balayage'),
        radars      = radars,
        offsets_m   = offsets_m,   # (dN, dW) en m pour une station, None pour la mosaïque
        codes       = grid_codes,
        dbz         = dbz,
    )


def despeckle(dbz, min_neighbors=2):
    """Supprime les pixels isolés (artefacts) sans toucher aux précipitations groupées."""
    mask = np.isfinite(dbz)
    nb   = np.zeros(mask.shape, dtype=int)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nb[max(0,dr):mask.shape[0]+min(0,dr),
               max(0,dc):mask.shape[1]+min(0,dc)] += \
                mask[max(0,-dr):mask.shape[0]+min(0,-dr),
                     max(0,-dc):mask.shape[1]+min(0,-dc)].astype(int)
    out = dbz.copy()
    out[mask & (nb < min_neighbors)] = np.nan
    return out


# ════════════════════════════════════════════════════════════════════════
#  GÉORÉFÉRENCEMENT  →  image prête pour Leaflet (Web Mercator)
# ════════════════════════════════════════════════════════════════════════
#  Projections des produits MF (vérifiées par ajustement des disques de
#  couverture sur les positions des antennes, erreur ≈ 1 km) :
#    - mosaïque  (projection type 3) : Mercator, échelle vraie à |latitude de référence| (17°)
#    - station   (projection type 4) : projection locale centrée sur le radar (stéréographique)
#  Leaflet étire une ImageOverlay linéairement en Web Mercator : on rééchantillonne
#  donc dans une grille régulière en Web Mercator entre les bornes renvoyées.

R_EARTH = 6371229.0
RADAR_CLEVS = np.array([8, 16, 20, 24, 28, 32, 36, 40, 44, 48, 99])
RADAR_RGB   = np.array([(58,166,255),(30,111,255),(27,209,27),(19,165,19),(10,122,10),
                        (255,240,0),(255,176,0),(255,90,0),(255,0,0),(176,0,0)], dtype=np.uint8)

def _merc_y(lat):  return np.log(np.tan(np.pi/4 + np.radians(lat)/2))
def _merc_lat(y):  return np.degrees(2*np.arctan(np.exp(y)) - np.pi/2)


def _projection(r):
    """Renvoie (forward, inverse) :
       forward(lat, lon)  -> (row, col) continus dans la grille source
       inverse(row, col)  -> (lat, lon)"""
    dx, dy = r['pixel_m']
    if r.get('offsets_m') is None:
        # ── Mosaïque : Mercator, échelle vraie à |ref_lat|
        k  = np.cos(np.radians(abs(r['ref_lat'])))
        y0 = _merc_y(r['corner_lat']); lon0 = r['corner_lon']
        def fwd(lat, lon):
            return ((y0 - _merc_y(lat)) * R_EARTH * k / dy,
                    np.radians(lon - lon0) * R_EARTH * k / dx)
        def inv(row, col):
            return (_merc_lat(y0 - row * dy / (R_EARTH * k)),
                    lon0 + np.degrees(col * dx / (R_EARTH * k)))
    else:
        # ── Station : stéréographique centrée sur le radar
        (la0, lo0), (dN, dW) = r['radars'][0], r['offsets_m']
        p0, l0 = np.radians(la0), np.radians(lo0)
        def fwd(lat, lon):
            p, l = np.radians(lat), np.radians(lon)
            kk = 2 / (1 + np.sin(p0)*np.sin(p) + np.cos(p0)*np.cos(p)*np.cos(l - l0))
            x = R_EARTH * kk * np.cos(p) * np.sin(l - l0)
            y = R_EARTH * kk * (np.cos(p0)*np.sin(p) - np.sin(p0)*np.cos(p)*np.cos(l - l0))
            return (dN - y) / dy, (x + dW) / dx
        def inv(row, col):
            x = col * dx - dW; y = dN - row * dy
            rho = np.hypot(x, y); c = 2 * np.arctan(rho / (2 * R_EARTH))
            with np.errstate(invalid='ignore', divide='ignore'):
                lat = np.arcsin(np.cos(c)*np.sin(p0) + np.where(rho > 0, y*np.sin(c)*np.cos(p0)/rho, 0))
            lon = l0 + np.arctan2(x*np.sin(c), rho*np.cos(p0)*np.cos(c) - y*np.sin(p0)*np.sin(c))
            return np.degrees(lat), np.degrees(lon)
    return fwd, inv


def make_overlay(r, dbz, alpha=210):
    """Grille dBZ décodée -> (image RGBA, bbox) géoréférencées pour L.imageOverlay."""
    ny, nx = dbz.shape
    fwd, inv = _projection(r)

    # Bornes : contour de la grille source reprojeté
    t = np.linspace(0, 1, 200)
    er = np.concatenate([t*ny, t*ny, np.zeros_like(t), np.full_like(t, ny)])
    ec = np.concatenate([np.zeros_like(t), np.full_like(t, nx), t*nx, t*nx])
    blat, blon = inv(er, ec)
    north, south = float(np.max(blat)), float(np.min(blat))
    west,  east  = float(np.min(blon)), float(np.max(blon))

    # Grille cible régulière en Web Mercator (même résolution que la source)
    H, W = ny, nx
    lon_t = west + (np.arange(W) + 0.5) * (east - west) / W
    yN, yS = _merc_y(north), _merc_y(south)
    lat_t = _merc_lat(yN - (np.arange(H) + 0.5) * (yN - yS) / H)
    LON, LAT = np.meshgrid(lon_t, lat_t)

    rr, cc = fwd(LAT, LON)
    ri, ci = np.floor(rr).astype(int), np.floor(cc).astype(int)
    ok = (ri >= 0) & (ri < ny) & (ci >= 0) & (ci < nx)
    samp = np.full((H, W), np.nan)
    samp[ok] = dbz[ri[ok], ci[ok]]

    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    ech = np.isfinite(samp)
    idx = np.clip(np.digitize(samp[ech], RADAR_CLEVS) - 1, 0, len(RADAR_RGB) - 1)
    rgba[ech, :3] = RADAR_RGB[idx]
    rgba[ech, 3] = alpha
    bbox = {"south": round(south, 5), "north": round(north, 5),
            "west":  round(west, 5),  "east":  round(east, 5)}
    return rgba, bbox