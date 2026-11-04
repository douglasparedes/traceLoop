import sqlite3, json
db = sqlite3.connect('fieldguard.db')
for p in db.execute("select id, title from procedures"):
    print(p[0][:8], '|', p[1][:50])
    for v in db.execute("select version_number, status, substr(id,1,8) from procedure_versions where procedure_id=? order by version_number", (p[0],)):
        print('   v%s %s %s' % v)
