#!/usr/bin/env python3
from __future__ import annotations

import ast
import py_compile
import subprocess
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

    tree = ast.parse(content, filename=str(FUNCTION_FILE))
    pipe_class = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "Pipe"
        ),
        None,
    )
    if pipe_class is None:
        raise RuntimeError("Pipe class is missing from openwebui_scanntech_function.py")

    required_methods = {"pipes", "pipe"}
    methods = {
        node.name
        for node in pipe_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing_methods = sorted(required_methods - methods)
    if missing_methods:
        raise RuntimeError(
            "openwebui_scanntech_function.py is missing required Pipe methods: "
            + ", ".join(missing_methods)
        )

    if not content.lstrip():
        raise RuntimeError("Function file is empty after trimming")


def copy_optional_helper() -> None:
    if SEMANTICS_FILE.exists():
        try:
            run(
                ["docker", "cp", str(SEMANTICS_FILE), f"{CONTAINER}:/tmp/aquafast_semantics.py"],
                timeout=15,
            )
        except (subprocess.TimeoutExpired, RuntimeError) as exc:
            print(f"WARN: could not copy optional aquafast_semantics.py helper: {exc}")


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
