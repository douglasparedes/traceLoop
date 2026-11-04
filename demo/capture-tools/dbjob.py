import sqlite3, json
db = sqlite3.connect('fieldguard.db')
for vid in ['ba2b8fb5', 'aacb11e0', '4b3aaaf4']:
    r = db.execute("select version_number, status, source_evidence from procedure_versions where id like ?", (vid+'%',)).fetchone()
    if not r:
        print(vid, 'MISSING')
        continue
    se = json.loads(r[2] or '{}')
    p = se.get('proposal', {})
    print('v%s %s job=%s feedback=%s' % (r[0], r[1], str(p.get('job_id',''))[:8], str(p.get('feedback_event_id',''))[:8]))
print('---jobs---')
for j in db.execute("select substr(id,1,8), status, procedure_version_id, technician_id from job_sessions order by started_at desc limit 4"):
    print(dict(j))
