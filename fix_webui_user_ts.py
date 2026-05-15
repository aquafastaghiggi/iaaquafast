import sqlite3
import time
import shutil

db = "/app/backend/data/webui.db"

shutil.copy2(db, db + ".bak_fix_user_ts_2")

conn = sqlite3.connect(db)
cur = conn.cursor()

now = int(time.time())

print("before:")
rows = cur.execute(
    "select id,email,created_at,updated_at from user"
).fetchall()

print(rows)

cur.execute(
    "update user set created_at=? where typeof(created_at)='text'",
    (now,)
)

cur.execute(
    "update user set updated_at=? where typeof(updated_at)='text'",
    (now,)
)

conn.commit()

print("after:")
rows = cur.execute(
    "select id,email,created_at,updated_at from user"
).fetchall()

print(rows)

conn.close()

print("backup:", db + ".bak_fix_user_ts_2")