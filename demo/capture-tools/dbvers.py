import sqlite3
db = sqlite3.connect('fieldguard.db')
print("procedures:")
for r in db.execute("select id, title from procedures"):
    print(" ", r[0][:8], r[1])
    for v in db.execute("select id, version_number, status from procedure_versions where procedure_id=? order by version_number", (r[0],)):
        n = db.execute("select count(*) from procedure_steps where procedure_version_id=?", (v[0],)).fetchone()[0]
        print("   v%s %s steps=%d %s" % (v[1], v[2], n, v[0][:8]))
