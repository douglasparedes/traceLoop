import sqlite3, json
db = sqlite3.connect('fieldguard.db')
db.row_factory = sqlite3.Row
print([r[0] for r in db.execute("select name from sqlite_master where type='table'")])
t = db.execute("select id, title, status, analysis_strategy, input_mode from tutorial_jobs order by created_at desc limit 4").fetchall()
for r in t:
    print(dict(r))
cid = [r['id'] for r in t if 'Chocolate' in r['title']][0]
print('COOKIE ID:', cid)
for r in db.execute("select stage, status, provider, model, duration_ms from processing_events where entity_id=? order by created_at", (cid,)):
    print(dict(r))
print('---summaries---')
for r in db.execute("select stage, substr(summary,1,300) as s from processing_events where entity_id=? order by created_at", (cid,)):
    print(r['stage'], '=>', r['s'])
print('---content---')
c = db.execute("select content_revision, substr(corrected_transcript,1,200) as ct from tutorial_jobs where id=?", (cid,)).fetchone()
print(dict(c))
for r in db.execute("select step_order, substr(title,1,80) as t from tutorial_steps where tutorial_id=? order by step_order", (cid,)):
    print(dict(r))
