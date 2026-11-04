import sqlite3
db = sqlite3.connect('fieldguard.db')
db.row_factory = sqlite3.Row
t = db.execute("select id, title, status, analysis_strategy from tutorial_jobs order by created_at desc limit 1").fetchone()
print("TUT:", dict(t))
cid = t['id']
for r in db.execute("select stage, status, provider, model, duration_ms from processing_events where entity_id=? order by created_at", (cid,)):
    print("EV:", dict(r))
for r in db.execute("select stage, substr(summary,1,400) as s from processing_events where entity_id=? order by created_at", (cid,)):
    print("SUM:", r['stage'], '=>', r['s'])
print("---steps---")
try:
    for r in db.execute("select step_order, substr(title,1,80) as t, substr(instruction,1,120) as i from tutorial_steps where tutorial_id=? order by step_order", (cid,)):
        print("STEP:", dict(r))
except Exception as e:
    print("steps table:", e)
    for tbl in ['tutorial_steps', 'procedure_steps', 'content_steps']:
        try:
            print(tbl, db.execute(f"select * from {tbl} limit 1").fetchone())
        except Exception as e2:
            print(tbl, 'missing')
