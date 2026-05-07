#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FUNCTION_ID = "ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc"
PIPE_MODEL_ID = f"{FUNCTION_ID}.scanntech_analyst"
WEBUI_CONTAINER = os.getenv("AQUAFAST_WEBUI_CONTAINER", "aquafast_webui")
SCANNTECH_API_URL = os.getenv("AQUAFAST_SCANNTECH_API_URL", "http://localhost:8001/health")
OLLAMA_TAGS_URL = os.getenv("AQUAFAST_OLLAMA_TAGS_URL", "http://localhost:11434/api/tags")


def print_check(level: str, label: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    print(f"[{level}] {label}{suffix}")


def run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def container_running(name: str) -> bool:
    result = run(["docker", "inspect", "-f", "{{.State.Running}}", name], timeout=20)
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def docker_exec_python(container: str, code: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return run(["docker", "exec", container, "python", "-c", code], timeout=timeout)


def check_webui_db() -> dict[str, object]:
    code = f"""
import json
import sqlite3

db_path = "/app/backend/data/webui.db"
result = {{}}
conn = sqlite3.connect(db_path)
cur = conn.cursor()
result["db_exists"] = True
result["function"] = cur.execute(
    "SELECT id, name, type, is_active, length(content), substr(content, 1, 1) "
    "FROM function WHERE id = ?",
    ("{FUNCTION_ID}",),
).fetchone()
result["models"] = cur.execute(
    "SELECT id, name, base_model_id, is_active FROM model"
).fetchall()
cfg_row = cur.execute("SELECT data FROM config WHERE id = 1").fetchone()
result["config"] = json.loads(cfg_row[0]) if cfg_row and cfg_row[0] else {{}}
user_row = cur.execute("SELECT settings FROM user LIMIT 1").fetchone()
result["user"] = json.loads(user_row[0]) if user_row and user_row[0] else {{}}
chat_row = cur.execute("SELECT chat FROM chat ORDER BY updated_at DESC LIMIT 1").fetchone()
result["chat"] = json.loads(chat_row[0]) if chat_row and chat_row[0] else {{}}
print(json.dumps(result, ensure_ascii=False))
conn.close()
"""
    return json.loads(docker_exec_python(WEBUI_CONTAINER, code, timeout=60).stdout)


def compose_model_filter_active() -> bool:
    compose_path = REPO_ROOT / "docker-compose.yml"
    if not compose_path.exists():
        return False
    active = False
    for raw_line in compose_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.lstrip()
        if line.startswith("#"):
            continue
        if "ENABLE_MODEL_FILTER=" in raw_line or "MODEL_FILTER_LIST=" in raw_line:
            active = True
            break
    return active


def main() -> int:
    print("Open WebUI / Scanntech Analyst doctor")
    print("=" * 48)

    issues: list[str] = []

    if container_running(WEBUI_CONTAINER):
        print_check("OK", f"Container {WEBUI_CONTAINER}", "running")
    else:
        print_check("FAIL", f"Container {WEBUI_CONTAINER}", "not running")
        issues.append(f"Run: docker compose -f {REPO_ROOT / 'docker-compose.yml'} up -d open-webui")
        print("\nSuggested commands:")
        print("  docker compose up -d")
        return 1

    db_info = check_webui_db()
    func = db_info.get("function")
    if func:
        func_id, func_name, func_type, is_active, content_len, first_char = func
        print_check("OK" if is_active == 1 else "FAIL", "Function row", f"{func_id} / {func_name} / {func_type} / active={is_active}")
        if is_active != 1:
            issues.append("Function is inactive. Run: python scripts/push_scanntech_function_to_db.py")
        if first_char == "\ufeff":
            print_check("FAIL", "Function content", "starts with BOM")
            issues.append("Function content has BOM. Re-run: python scripts/push_scanntech_function_to_db.py")
        else:
            print_check("OK", "Function content", f"length={content_len}, no BOM")
    else:
        print_check("FAIL", "Function row", f"missing id={FUNCTION_ID}")
        issues.append("Function row missing. Run: python scripts/push_scanntech_function_to_db.py")

    models = db_info.get("models") or []
    if models:
        print_check("OK", "Model rows", f"{len(models)} row(s) in DB")
        if any(row[0] == PIPE_MODEL_ID for row in models):
            print_check("OK", "Pipe model reference", PIPE_MODEL_ID)
        else:
            print_check("WARN", "Pipe model reference", "pipe id not found in model table")
    else:
        print_check("WARN", "Model rows", "model table empty")

    cfg = db_info.get("config") or {}
    user = db_info.get("user") or {}
    chat = db_info.get("chat") or {}

    cfg_ui = cfg.get("ui") or {}
    user_ui = user.get("ui") or {}
    cfg_models = (cfg_ui.get("default_models"), cfg_ui.get("default_model"))
    user_models = (user_ui.get("models"), user_ui.get("selectedModel"), user_ui.get("defaultModel"))
    chat_models = chat.get("models")
    cfg_prompt = cfg_ui.get("prompt_suggestions") or []
    cfg_default_prompt = cfg_ui.get("default_prompt_suggestions") or []
    user_prompt = user_ui.get("prompt_suggestions") or []
    user_default_prompt = user_ui.get("default_prompt_suggestions") or []

    if PIPE_MODEL_ID in str(cfg_models):
        print_check("OK", "Config default", str(cfg_models))
    else:
        print_check("WARN", "Config default", str(cfg_models))

    if PIPE_MODEL_ID in str(user_models):
        print_check("OK", "User default", str(user_models))
    else:
        print_check("WARN", "User default", str(user_models))

    if chat_models and PIPE_MODEL_ID in str(chat_models):
        print_check("OK", "Chat reference", str(chat_models))
    else:
        print_check("WARN", "Chat reference", str(chat_models))

    if cfg_prompt or cfg_default_prompt:
        detail = f"config prompt={len(cfg_prompt)} default_prompt={len(cfg_default_prompt)}"
        level = "OK" if len(cfg_prompt) >= 20 and len(cfg_default_prompt) >= 20 else "WARN"
        print_check(level, "Config suggestions", detail)
        if len(cfg_prompt) != len(cfg_default_prompt):
            print_check("WARN", "Config suggestions mismatch", "prompt_suggestions and default_prompt_suggestions differ")
    else:
        print_check("WARN", "Config suggestions", "missing in config.ui")

    if user_prompt or user_default_prompt:
        detail = f"user prompt={len(user_prompt)} default_prompt={len(user_default_prompt)}"
        level = "OK" if len(user_prompt) >= 20 and len(user_default_prompt) >= 20 else "WARN"
        print_check(level, "User suggestions", detail)
        if len(user_prompt) != len(user_default_prompt):
            print_check("WARN", "User suggestions mismatch", "prompt_suggestions and default_prompt_suggestions differ")
    else:
        print_check("WARN", "User suggestions", "missing in user.ui")

    if compose_model_filter_active():
        print_check("WARN", "Compose model filter", "active; can hide models when the pipe fails")
        issues.append("Model filter is active. Keep it commented until the pipe is healthy.")
    else:
        print_check("OK", "Compose model filter", "disabled by default")

    try:
        with urllib.request.urlopen(SCANNTECH_API_URL, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        print_check("OK", "Scanntech API /health", f"ok={payload.get('ok')} tables={payload.get('tables')} records={payload.get('total_registros')}")
    except Exception as exc:
        print_check("FAIL", "Scanntech API /health", str(exc))
        issues.append("Scanntech API is unhealthy. Check the scanntech-api container.")

    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = payload.get("models", [])
        print_check("OK", "Ollama /api/tags", f"{len(models)} model(s)")
        models_text = json.dumps(models, ensure_ascii=False).lower()
        if "qwen2.5" in models_text:
            print_check("OK", "qwen2.5 presence", "fallback model available")
        else:
            print_check("WARN", "qwen2.5 presence", "missing; free-chat fallback may be impaired, but predefinidas seguem operando")
    except urllib.error.HTTPError as exc:
        print_check("FAIL", "Ollama /api/tags", f"HTTP {exc.code}")
        issues.append("Ollama returned an HTTP error. Check the ollama container.")
    except Exception as exc:
        print_check("FAIL", "Ollama /api/tags", str(exc))
        issues.append("Ollama is not reachable. Check the ollama container.")

    log_result = run(["docker", "logs", WEBUI_CONTAINER, "--since", "1h", "--tail", "300"], timeout=60)
    log_text = (log_result.stdout or "") + (log_result.stderr or "")
    suspicious_patterns = {
        "BOM / U+FEFF": r"U\+FEFF|invalid non-printable character",
        "Import error": r"ModuleNotFoundError|ImportError|Error loading module",
        "Function load": r"function load error|failed to load function|error loading function",
    }
    found_any = False
    for label, pattern in suspicious_patterns.items():
        if re.search(pattern, log_text, flags=re.IGNORECASE):
            print_check("FAIL", "Open WebUI logs", label)
            issues.append(f"Open WebUI logs contain {label.lower()}.")
            found_any = True
    if not found_any:
        print_check("OK", "Open WebUI logs", "no recent import/function-load errors")

    print("\nSuggested commands:")
    if issues:
        print("  python scripts/push_scanntech_function_to_db.py")
        print("  python scripts/doctor_openwebui.py")
        print("  docker compose up -d open-webui")
        print("  docker logs aquafast_webui --since 1h --tail 300")
    else:
        print("  No action required. Open a new chat and test the suggested questions.")

    return 0 if not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())
