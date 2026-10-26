# OH-SMArt data explorer

An interface for explorting oral history specific data, as deposited via the OH-SMArt deposit app. Fetches all OH-SMArt datasets from dataverse, reads their files and flattens harvested data into a shape suitable for indexing. Uses Typesense for search, a TanStack Start + React frontend.

## Local development

Typesense runs in Docker; the frontend runs on your host via `vp dev` (Vite+)

1. **Start Typesense**

```bash
   cp .env.example .env   # set TYPESENSE_API_KEY
   docker compose --env-file .env up -d
```

2. **Create and fill the collection**

```bash
   pip install -r requirements.txt
   set -a; source .env; set +a
   python harvest.py --dry-run     # preview
   python harvest.py               # sync (or incremental sync when already created)
```

When you need to modify the collection schema, you can run:
```bash
   python harvest.py --full        # ignore checksums, re-fetch everything
   python harvest.py --recreate    # drop + recreate the collection (schema change)
```

3. **Run the frontend** — see [Portal README](/portal/README.md).
