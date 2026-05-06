#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "aquafast_webui"
FUNCTION_ID = "ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc"
FUNCTION_MODEL_ID = f"{FUNCTION_ID}.scanntech_analyst"
FUNCTION_FILE = REPO_ROOT / "openwebui_scanntech_function.py"
SEMANTICS_FILE = REPO_ROOT / "aquafast_semantics.py"


def run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        message = stderr or stdout or "command failed"
        raise RuntimeError(f"{' '.join(cmd)} failed: {message}")
    return completed


def ensure_no_bom(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        raise RuntimeError(f"{path} starts with a UTF-8 BOM")
    return data.decode("utf-8")


def validate_function_source() -> None:
    if not FUNCTION_FILE.exists():
        raise FileNotFoundError(f"Missing function file: {FUNCTION_FILE}")

    # Fail fast if the source accidentally picks up a BOM again.
    content = ensure_no_bom(FUNCTION_FILE)

    py_compile.compile(str(FUNCTION_FILE), doraise=True)

    sys.path.insert(0, str(REPO_ROOT))
    if SEMANTICS_FILE.exists():
        import aquafast_semantics  # noqa: F401

    spec = importlib.util.spec_from_file_location("openwebui_scanntech_function_validation", FUNCTION_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not create import spec for openwebui_scanntech_function.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "Pipe"):
        raise RuntimeError("Pipe class is missing from openwebui_scanntech_function.py")

    if not content.lstrip():
        raise RuntimeError("Function file is empty after trimming")


def copy_optional_helper() -> None:
    if SEMANTICS_FILE.exists():
        run(["docker", "cp", str(SEMANTICS_FILE), f"{CONTAINER}:/tmp/aquafast_semantics.py"])


def copy_function_file() -> None:
    run(["docker", "cp", str(FUNCTION_FILE), f"{CONTAINER}:/tmp/scanntech_function.py"])


def update_db_in_container() -> None:
    script = f"""
import json
import sqlite3
from pathlib import Path

FUNCTION_ID = {FUNCTION_ID!r}
FUNCTION_MODEL_ID = {FUNCTION_MODEL_ID!r}
DB_PATH = "/app/backend/data/webui.db"
SOURCE = "/tmp/scanntech_function.py"

content = Path(SOURCE).read_text(encoding="utf-8")
if content.startswith("\\ufeff"):
    raise RuntimeError("Function content in /tmp still starts with BOM")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("UPDATE function SET content=?, is_active=1 WHERE id=?", (content, FUNCTION_ID))
conn.commit()
row = cur.execute(
    "SELECT id, name, type, is_active FROM function WHERE id=?",
    (FUNCTION_ID,),
).fetchone()
print(row)
conn.close()
"""

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        handle.write(script)
        temp_script = Path(handle.name)

    try:
        run(["docker", "cp", str(temp_script), f"{CONTAINER}:/tmp/update_scanntech_function.py"])
        result = run(["docker", "exec", CONTAINER, "python", "/tmp/update_scanntech_function.py"])
        print(result.stdout.strip())
    finally:
        try:
            temp_script.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    validate_function_source()
    copy_function_file()
    copy_optional_helper()
    update_db_in_container()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
