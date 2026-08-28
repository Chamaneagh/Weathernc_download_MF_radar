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
    else:
        # Mosaïque : premier point = coin NW, les suivants = radars
        corner_lat, corner_lon = lats[0], lons[0]
        radars = list(zip(lats[1:], lons[1:]))

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
