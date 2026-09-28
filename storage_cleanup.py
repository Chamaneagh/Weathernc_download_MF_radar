"""
storage_cleanup.py — purge des PNG radar anciens via l'API Storage de Supabase.

La suppression SQL directe dans storage.objects est bloquée par Supabase,
d'où ce nettoyage côté worker. Les images sont rangées par date :
    <source>/<AAAA>/<MM>/<JJ>/<HHMM>.png
On supprime tout dossier-jour antérieur à hier (UTC). Une ligne de radar_frames
ayant au plus ~48 h (purge SQL quotidienne à 24 h), elle pointe toujours vers
le dossier d'aujourd'hui ou d'hier : aucune image utilisée n'est supprimée.
"""
import datetime as dt
import requests

KEEP_DAYS = 1          # garde aujourd'hui + hier (UTC)
MAX_FOLDERS = 25       # dossiers-jour max par run (résorbe l'historique progressivement)


def _list(base, headers, bucket, prefix):
    """Liste un niveau de dossier (non récursif). Renvoie les noms des entrées."""
    names, offset = [], 0
    while True:
        r = requests.post(f"{base}/storage/v1/object/list/{bucket}", headers=headers,
                          json={"prefix": prefix, "limit": 1000, "offset": offset,
                                "sortBy": {"column": "name", "order": "asc"}}, timeout=60)
        r.raise_for_status()
        batch = r.json()
        names += [e["name"] for e in batch]
        if len(batch) < 1000:
            return names
        offset += 1000


def _delete(base, headers, bucket, paths):
    for i in range(0, len(paths), 1000):
        requests.delete(f"{base}/storage/v1/object/{bucket}", headers=headers,
                        json={"prefixes": paths[i:i + 1000]}, timeout=60).raise_for_status()


def cleanup_storage(base, key, bucket, source_prefixes, log=print, today=None):
    """Supprime les dossiers-jour trop anciens pour chaque source. Renvoie le nb de fichiers supprimés."""
    headers = {"Authorization": f"Bearer {key}", "apikey": key}
    today = today or dt.datetime.now(dt.timezone.utc).date()
    limit = today - dt.timedelta(days=KEEP_DAYS)
    total, done = 0, 0
    for src in source_prefixes:                                   # ex. "nc-mosaic"
        for y in _list(base, headers, bucket, f"{src}/"):
            for m in _list(base, headers, bucket, f"{src}/{y}/"):
                for d in _list(base, headers, bucket, f"{src}/{y}/{m}/"):
                    try:
                        day = dt.date(int(y), int(m), int(d))
                    except ValueError:
                        continue
                    if day >= limit:
                        continue
                    if done >= MAX_FOLDERS:
                        break
                    folder = f"{src}/{y}/{m}/{d}"
                    files = [f"{folder}/{f}" for f in _list(base, headers, bucket, f"{folder}/")]
                    if files:
                        _delete(base, headers, bucket, files)
                        total += len(files)
                    done += 1
    if total:
        log(f"CLEANUP {total} image(s) supprimée(s) (antérieures au {limit})")
    return total
