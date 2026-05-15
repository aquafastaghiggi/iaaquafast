import sqlite3
import bcrypt

EMAIL = "aghiggi@aquafast.com.br"
NEW_PASSWORD = "Admin@123"

db = "/app/backend/data/webui.db"

conn = sqlite3.connect(db)
cur = conn.cursor()

hashed = bcrypt.hashpw(
    NEW_PASSWORD.encode(),
    bcrypt.gensalt()
).decode()

cur.execute(
    """
    update auth
    set password=?
    where email=?
    """,
    (hashed, EMAIL),
)

print("rows updated:", cur.rowcount)

conn.commit()
conn.close()

print("password reset ok")