import subprocess
from pathlib import Path


FUNCTION_ID = "ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc"
CONTAINER = "aquafast_webui"
LOCAL_FILE = Path(r"C:\xampp\htdocs\scantech\openwebui_scanntech_function.py")


def run(cmd: list[str]) -> None:
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.stdout:
        print(completed.stdout.strip())
    if completed.returncode != 0:
        if completed.stderr:
            print(completed.stderr.strip())
        raise SystemExit(completed.returncode)


def main() -> None:
    if not LOCAL_FILE.exists():
        raise SystemExit(f"Arquivo não encontrado: {LOCAL_FILE}")

    run(["docker", "cp", str(LOCAL_FILE), f"{CONTAINER}:/tmp/scanntech_function.py"])

    script = r"""
import sqlite3
from pathlib import Path

FUNCTION_ID = "ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc"
DB_PATH = "/app/backend/data/webui.db"
SOURCE = "/tmp/scanntech_function.py"

content = Path(SOURCE).read_text(encoding="utf-8")
if content.startswith("\ufeff"):
    content = content.lstrip("\ufeff")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("UPDATE function SET content=?, is_active=1 WHERE id=?", (content, FUNCTION_ID))
conn.commit()
cur.execute("SELECT id, name, type, is_active FROM function WHERE id=?", (FUNCTION_ID,))
print(cur.fetchone())
conn.close()
"""
    tmp_local = Path(r"C:\xampp\htdocs\scantech\scripts\_tmp_update_func.py")
    tmp_local.write_text(script, encoding="utf-8")
    run(["docker", "cp", str(tmp_local), f"{CONTAINER}:/tmp/update_func.py"])
    run(["docker", "exec", CONTAINER, "python", "/tmp/update_func.py"])


if __name__ == "__main__":
    main()
