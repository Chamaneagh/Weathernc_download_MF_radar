# Weathernc — Météo-France NC radar → Supabase

Context handoff so this work can continue in Claude Code (VS Code) directly from the repo.

## What this does
Every 5 minutes, downloads Météo-France radar REFLECTIVITE for New Caledonia,
decodes it, and stores a transparent map overlay (+ metadata) in Supabase, for an
animated rain map on weathernc. Three sources:

| source key | what | grid | endpoint |
|---|---|---|---|
| `NC-MOSAIC` | wide-area composite | 1264×1264 @ 1 km | `.../mosaiques/NOUVELLE-CALEDONIE/observations/REFLECTIVITE` |
| `NOUMEA` | single radar (station 94) | 512×512 @ 1 km | `.../stations/94/observations/REFLECTIVITE/produit` |
| `LIFOU` | single radar (station 96) | 512×512 @ 1 km | `.../stations/96/observations/REFLECTIVITE/produit` |

Base URL: `https://public-api.meteofrance.fr/public/DPRadar/v1`. Auth: header `apikey: <key>`.

## Files
- `worker.py` — the 5-min job: download → decode → despeckle → overlay PNG → Supabase Storage + `radar_frames` row. Multi-source loop.
- `mf_radar.py` — clean decode API: `decode_file(path) -> {observed_at, nx, ny, pixel_m, corner_lat/lon, dbz, radars, ...}` plus `despeckle()`. Handles both the mosaic and single-radar layouts.
- `mflib/_refdecoder.py` — the actual BUFR decoder (adapted from github.com/theperk08/Meteo_France_Radars), wrapped by mf_radar. **To refactor into standalone code eventually.**
- `mflib/tables/` — Météo-France BUFR tables. Required. The files in use: master `bufrtabb_11/bufrtabd_11`, local `localtabb_85_14/localtabd_85_14` (mosaic, local table v14) and `localtabb_85_12/localtabd_85_12` (stations, local table v12).
- `schema.sql` — the `radar_frames` table (run once in Supabase).
- `requirements.txt` — requests, numpy, pillow, pandas.

## Key technical facts (the hard-won parts)
- Files are gzipped **BUFR edition 2**, centre **85 (MF Toulouse)**, category 6 (radar).
- They will NOT decode with stock WMO tables or vanilla ecCodes — MF uses **local descriptors** incl. a non-standard 32-bit replication factor (`0-31-192`). The `mflib/tables` local tables resolve them.
- Pixel codes → dBZ via the in-file calibration ("Reflectivite pour la valeur du pixel"); code 0 = no echo, 255 = no data.
- **Georeferencing** is an equirectangular model anchored at the NW corner (mosaic: corner is in-file; station: derived from radar centre + the NW-corner offsets in the file). Validated to ~1 pixel against the two radar positions and the official meteo.nc image. For sub-km precision, confirm MF projection types (mosaic=3, station=4) against the MF "Descriptif technique" PDF.
- The faint horizontal line at **−23.3°** is a real artifact **in MF's own source data** (visible on meteo.nc too), not a decode bug. `despeckle(min_neighbors=2)` removes it without touching real precip.

## Output format for the widget
Each frame is a transparent EPSG:4326 PNG resampled to a regular lat/lon rectangle,
plus a `bbox {south,north,west,east}` in `radar_frames`. The widget overlays it with a
Leaflet/MapLibre `ImageOverlay(bbox)`. Each source has its own bbox, so the UI can switch
between the composite and the station views.

## Deploy
1. `pip install -r requirements.txt`
2. Run `schema.sql` in Supabase; create a Storage bucket `radar` (public if the widget reads PNGs by URL).
3. Set env vars: `MF_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` (service-role, server-side only), `SUPABASE_BUCKET=radar`.
4. First manual run: `python worker.py` — check all three sources log `OK`.
5. Schedule `*/5 * * * *` (cron / GitHub Actions / small VM).

## Open items / next steps
- Confirm station **96 = Lifou** on first live run, and that the `/produit` URLs return the `.gz` directly.
- (Optional) refine georeferencing to the exact MF projection for sub-km precision.
- (Optional) refactor `mflib/_refdecoder.py` into standalone code (currently notebook-derived).
- Retention: prune `radar_frames` older than ~48h (pg_cron) + clean old Storage objects.
- **Step 2 (not started): the widget** — NC map that loads the last N `radar_frames` for a chosen `source` and animates the overlays with a time slider + source switcher.