import sqlite3, json
db = sqlite3.connect('fieldguard.db')
cid = '3c210b9d-eb23-4eba-b467-b2e165662317'
for r in db.execute("select stage, summary from processing_events where entity_id=? order by created_at", (cid,)):
    print("=" * 20, r[0])
    try:
        print(json.dumps(json.loads(r[1]), indent=1)[:2500])
    except Exception:
        print(r[1][:500])
