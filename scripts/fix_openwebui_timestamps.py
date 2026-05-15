#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


CONTAINER_NAME = os.getenv("AQUAFAST_WEBUI_CONTAINER", "aquafast_webui")
DB_PATH = "/app/backend/data/webui.db"


def run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def container_file_copy(src: str, dst: str) -> subprocess.CompletedProcess[str]:
    return run(["docker", "cp", src, dst], timeout=180)


def iso_timestamp_utc(epoch: float | None = None) -> str:
    dt = datetime.fromtimestamp(epoch if epoch is not None else time.time(), tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def repair_database(db_file: Path) -> dict[str, dict[str, dict[str, int]]]:
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    now_unix = int(time.time())
    now_iso = iso_timestamp_utc(now_unix)

    tables = {
        "user": {
            "created_at": "integer",
            "updated_at": "integer",
            "last_active_at": "integer",
        },
        "config": {
            "created_at": "text",
            "updated_at": "text",
        },
    }

    summary: dict[str, dict[str, dict[str, int]]] = {}
    try:
        for table, columns in tables.items():
            info = cur.execute(f'PRAGMA table_info("{table}")').fetchall()
            existing = {row[1] for row in info}
            table_summary: dict[str, dict[str, int]] = {}
            for column, desired_type in columns.items():
                if column not in existing:
                    continue
                before = cur.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE typeof("{column}") != ? AND "{column}" IS NOT NULL',
                    (desired_type,),
                ).fetchone()[0]

                if before:
                    if table == "user":
                        cur.execute(
                            f'UPDATE "{table}" SET "{column}" = ? WHERE typeof("{column}") != ? AND "{column}" IS NOT NULL',
                            (now_unix, desired_type),
                        )
                    else:
                        cur.execute(
                            f'UPDATE "{table}" SET "{column}" = ? WHERE typeof("{column}") != ? AND "{column}" IS NOT NULL',
                            (now_iso, desired_type),
                        )

                after = cur.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE typeof("{column}") != ? AND "{column}" IS NOT NULL',
                    (desired_type,),
                ).fetchone()[0]
                table_summary[column] = {
                    "before_wrong_type": int(before),
                    "after_wrong_type": int(after),
                    "updated_rows": int(before - after),
                }
            summary[table] = table_summary
        conn.commit()
    finally:
        conn.close()
    return summary


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="openwebui_fix_") as tmpdir:
        tmp = Path(tmpdir)
        local_db = tmp / "webui.db"
        backup_local = tmp / f"webui.db.bak_{time.strftime('%Y%m%d_%H%M%S', time.localtime())}"
        backup_container = f"{CONTAINER_NAME}:/app/backend/data/webui.db.bak_{time.strftime('%Y%m%d_%H%M%S', time.localtime())}"

        copy_out = container_file_copy(f"{CONTAINER_NAME}:{DB_PATH}", str(local_db))
        if copy_out.returncode != 0:
            if copy_out.stdout.strip():
                print(copy_out.stdout.strip())
            if copy_out.stderr.strip():
                print(copy_out.stderr.strip(), file=sys.stderr)
            return copy_out.returncode

        shutil.copy2(local_db, backup_local)

        summary = repair_database(local_db)

        copy_backup = container_file_copy(str(backup_local), backup_container)
        if copy_backup.returncode != 0:
            if copy_backup.stdout.strip():
                print(copy_backup.stdout.strip())
            if copy_backup.stderr.strip():
                print(copy_backup.stderr.strip(), file=sys.stderr)
            return copy_backup.returncode

        copy_back = container_file_copy(str(local_db), f"{CONTAINER_NAME}:{DB_PATH}")
        if copy_back.returncode != 0:
            if copy_back.stdout.strip():
                print(copy_back.stdout.strip())
            if copy_back.stderr.strip():
                print(copy_back.stderr.strip(), file=sys.stderr)
            return copy_back.returncode

        print(f"Backup created: {backup_container.split(':', 1)[1]}")
        print(f"Replacement timestamp (user): {int(time.time())}")
        print(f"Replacement timestamp (config): {iso_timestamp_utc()}")
        for table, columns in summary.items():
            for column, stats in columns.items():
                print(
                    f"{table}.{column}: wrong_before={stats['before_wrong_type']} "
                    f"wrong_after={stats['after_wrong_type']} updated={stats['updated_rows']}"
                )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
