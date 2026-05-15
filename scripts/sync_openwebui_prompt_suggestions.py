#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time


CONTAINER_NAME = os.getenv("AQUAFAST_WEBUI_CONTAINER", "aquafast_webui")
DB_PATH = "/app/backend/data/webui.db"

HOME_PROMPT_SUGGESTIONS: tuple[dict[str, str], ...] = (
    {"title": "Agente Vendas Aquafast", "content": "Agente Vendas Aquafast"},
    {"title": "Agente Produtos", "content": "Agente Produtos"},
    {"title": "Agente Concorrência", "content": "Agente Concorrência"},
    {"title": "Agente Oportunidades", "content": "Agente Oportunidades"},
    {"title": "Agente Auditoria da Base", "content": "Agente Auditoria da Base"},
)


def build_container_code(suggestions: list[dict[str, str]], dry_run: bool) -> str:
    suggestions_json = json.dumps(
        [{"title": [item["title"]], "content": item["content"]} for item in suggestions],
        ensure_ascii=False,
    )
    dry_run_literal = repr(dry_run)
    return f"""
import json
import sqlite3
import time

DB_PATH = {DB_PATH!r}
SUGGESTIONS = json.loads({suggestions_json!r})
NOW_UNIX = int(time.time())
NOW_ISO = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cfg_row = cur.execute("SELECT data FROM config WHERE id = 1").fetchone()
if not cfg_row or not cfg_row[0]:
    raise SystemExit("config row missing")

cfg = json.loads(cfg_row[0])
ui = cfg.setdefault("ui", {{}})
before_prompt = ui.get("prompt_suggestions") or []
before_default = ui.get("default_prompt_suggestions") or []

print(json.dumps({{
    "before_prompt": len(before_prompt),
    "before_default": len(before_default),
    "dry_run": {dry_run_literal},
}}, ensure_ascii=False))

if not {dry_run_literal}:
    ui["prompt_suggestions"] = SUGGESTIONS
    ui["default_prompt_suggestions"] = SUGGESTIONS
    cur.execute(
        "UPDATE config SET data = ?, updated_at = ? WHERE id = 1",
        (json.dumps(cfg, ensure_ascii=False), NOW_ISO),
    )

    user_cols = [row[1] for row in cur.execute("PRAGMA table_info(user)").fetchall()]
    if "settings" in user_cols:
        users = cur.execute("SELECT id, settings FROM user").fetchall()
        for user_id, settings_text in users:
            settings = json.loads(settings_text) if settings_text else {{}}
            user_ui = settings.setdefault("ui", {{}})
            user_ui["prompt_suggestions"] = SUGGESTIONS
            user_ui["default_prompt_suggestions"] = SUGGESTIONS
            cur.execute(
                "UPDATE user SET settings = ?, updated_at = ? WHERE id = ?",
                (json.dumps(settings, ensure_ascii=False), NOW_UNIX, user_id),
            )

    conn.commit()

cfg_row = cur.execute("SELECT data FROM config WHERE id = 1").fetchone()
cfg = json.loads(cfg_row[0])
ui = cfg.get("ui") or {{}}
print(json.dumps({{
    "after_prompt": len(ui.get("prompt_suggestions") or []),
    "after_default": len(ui.get("default_prompt_suggestions") or []),
}}, ensure_ascii=False))
conn.close()
"""


def run_container_code(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "exec", "-i", CONTAINER_NAME, "python", "-"],
        input=code,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Open WebUI prompt suggestions in config/user settings.")
    parser.add_argument("--dry-run", action="store_true", help="Show counts without writing to the DB")
    args = parser.parse_args()

    suggestions = list(HOME_PROMPT_SUGGESTIONS)
    code = build_container_code(suggestions, dry_run=args.dry_run)
    result = run_container_code(code)

    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())

    if result.returncode != 0:
        raise SystemExit(result.returncode)

    if args.dry_run:
        print(f"Dry-run validated Open WebUI suggestions in {CONTAINER_NAME} ({len(suggestions)} items).")
    else:
        print(f"Updated Open WebUI suggestions in {CONTAINER_NAME} ({len(suggestions)} items).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
