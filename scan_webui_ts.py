import sqlite3

db = "/app/backend/data/webui.db"

c = sqlite3.connect(db)
cur = c.cursor()

tables = [
    r[0]
    for r in cur.execute(
        "select name from sqlite_master where type='table'"
    ).fetchall()
]

bad = []

def qname(name):
    return '"' + name.replace('"', '""') + '"'

for t in tables:
    table = qname(t)

    cols = [
        x[1]
        for x in cur.execute(f"pragma table_info({table})").fetchall()
    ]

    for col in ["created_at", "updated_at", "last_active_at"]:
        if col in cols:
            colq = qname(col)
            rows = cur.execute(
                f"select count(*) from {table} where typeof({colq})='text'"
            ).fetchone()[0]

            if rows:
                bad.append((t, col, rows))

print("BAD:")
print(bad)

c.close()