import sqlite3, json
db = sqlite3.connect('fieldguard.db')
r = db.execute("select source_evidence from procedure_versions where procedure_id='906db29a' and version_number=5").fetchone()
p = json.loads(r[0]).get('proposal', {})
print('v5 sim:', p.get('simulated'), 'model:', p.get('model'))
print('job:', str(p.get('job_id', ''))[:8])
