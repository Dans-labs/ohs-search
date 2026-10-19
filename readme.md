```bash
cp .env.example .env            # set TYPESENSE_API_KEY
docker compose --env-file .env up -d
pip install -r requirements.txt
set -a; source .env; set +a
python harvest.py --dry-run     # preview
python harvest.py               # sync
```