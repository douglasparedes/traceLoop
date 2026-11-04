import sqlite3, json
db = sqlite3.connect('fieldguard.db')
r = db.execute("select version_number, status, source_evidence, ai_model, ai_simulated from procedure_versions where procedure_id='906db29a' order by version_number").fetchall()
for v in r:
    se = json.loads(v[2] or '{}')
    p = se.get('proposal', {})
    print('v%s %s model=%s sim=%s job=%s' % (v[0], v[1], p.get('model', v[3]), p.get('simulated', v[4]), str(p.get('job_id',''))[:8]))
