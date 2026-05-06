import json
import sqlite3
import time


PIPE_MODEL = "ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc.scanntech_analyst"
DB_PATH = "/app/backend/data/webui.db"


def main() -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    now = int(time.time())

    cur.execute(
        "UPDATE function SET is_active = 1, is_global = 1, updated_at = ? "
        "WHERE id = 'ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc'",
        (now,),
    )
    cur.execute("UPDATE model SET is_active = 0 WHERE id = 'scanntech_analyst'")

    cfg_row = cur.execute("SELECT data FROM config WHERE id = 1").fetchone()
    cfg = json.loads(cfg_row[0]) if cfg_row and cfg_row[0] else {}
    ui = cfg.setdefault("ui", {})
    ui["default_models"] = [PIPE_MODEL]
    ui["default_pinned_models"] = [PIPE_MODEL]
    ui["default_model"] = PIPE_MODEL
    ui["selected_model"] = PIPE_MODEL
    cur.execute(
        "UPDATE config SET data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
        (json.dumps(cfg, ensure_ascii=False),),
    )

    users = cur.execute("SELECT id, settings FROM user").fetchall()
    for uid, settings_text in users:
        settings = json.loads(settings_text) if settings_text else {}
        ui_settings = settings.setdefault("ui", {})
        ui_settings["models"] = [PIPE_MODEL]
        ui_settings["pinnedModels"] = [PIPE_MODEL]
        ui_settings["selectedModel"] = PIPE_MODEL
        ui_settings["defaultModel"] = PIPE_MODEL
        cur.execute(
            "UPDATE user SET settings = ?, updated_at = ? WHERE id = ?",
            (json.dumps(settings, ensure_ascii=False), now, uid),
        )

    chats = cur.execute("SELECT id, chat FROM chat WHERE chat IS NOT NULL").fetchall()
    for chat_id, chat_text in chats:
        try:
            payload = json.loads(chat_text)
        except Exception:
            continue
        payload["models"] = [PIPE_MODEL]

        for msg in payload.get("messages", []):
            if isinstance(msg, dict):
                if "model" in msg:
                    msg["model"] = PIPE_MODEL
                if "models" in msg:
                    msg["models"] = [PIPE_MODEL]

        history = payload.get("history", {})
        messages = history.get("messages", {}) if isinstance(history, dict) else {}
        for msg in messages.values():
            if isinstance(msg, dict):
                if "model" in msg:
                    msg["model"] = PIPE_MODEL
                if "models" in msg:
                    msg["models"] = [PIPE_MODEL]

        cur.execute(
            "UPDATE chat SET chat = ?, updated_at = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False), now, chat_id),
        )

    con.commit()

    print(cur.execute("SELECT id, name, is_active FROM function").fetchall())
    print(cur.execute("SELECT id, name, is_active FROM model WHERE id = 'scanntech_analyst'").fetchone())
    print(cur.execute("SELECT settings FROM user LIMIT 1").fetchone()[0])
    con.close()


if __name__ == "__main__":
    main()
