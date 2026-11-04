import sqlite3, json
db = sqlite3.connect('fieldguard.db')
r = db.execute("select source_evidence from procedure_versions where id like 'b4d55152%'").fetchone()
p = json.loads(r[0]).get('proposal', {})
print('v5 sim:', p.get('simulated'), 'model:', p.get('model'))
print('job:', str(p.get('job_id', ''))[:8])
print('base v:', p.get('base_version_number'))
