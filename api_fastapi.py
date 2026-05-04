"""
Aquafast Scanntech API

FastAPI app for deterministic DuckDB queries, schema inspection and Excel export.
"""

from __future__ import annotations

import argparse
import math
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field
from uvicorn import run as uvicorn_run

APP_NAME = "Aquafast Scanntech API"
DB_PATH = Path(__file__).with_name("aquafast_scanntech.duckdb")
EXPORT_DIR = Path(__file__).with_name("exports") / "generated"
REPORT_SPECS: dict[str, dict[str, Any]] = {
    "ranking_clientes": {
        "title": "Top 20 clientes por valor total",
        "description": "Ranking dos clientes por valor total, ticket medio e periodo de compra.",
        "sql": "SELECT * FROM ranking_clientes ORDER BY valor_total DESC NULLS LAST, total_pedidos DESC, cliente",
    },
    "ranking_produtos": {
        "title": "Top 20 produtos mais vendidos",
        "description": "Ranking dos produtos por volume vendido e receita total.",
        "sql": "SELECT * FROM ranking_produtos ORDER BY receita_total DESC NULLS LAST, total_vendas DESC, produto",
    },
    "vendas_por_mes": {
        "title": "Vendas por mes",
        "description": "Serie mensal de pedidos e receita total.",
        "sql": "SELECT * FROM vendas_por_mes ORDER BY mes",
    },
}
AVAILABLE_REPORTS = list(REPORT_SPECS)
REPORT_PAGE_SIZE_LIMIT = 200

app = FastAPI(title=APP_NAME, version="1.0.0")


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1)


class SQLRequest(BaseModel):
    sql: str = Field(..., min_length=1)
    title: str = Field(default="Consulta SQL")


def normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.strip().lower().split())


def sanitize_filename(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", normalize(text)).strip("_")
    return cleaned or "exportacao"


def format_markdown(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    if not rows:
        return "_Nenhum resultado encontrado._"

    header = " | ".join(columns)
    separator = " | ".join(["---"] * len(columns))
    lines = [f"| {header} |", f"| {separator} |"]

    for row in rows:
        values = ["" if value is None else str(value) for value in row]
        lines.append(f"| {' | '.join(values)} |")

    return "\n".join(lines)


def open_connection():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Banco nao encontrado: {DB_PATH}")
    return duckdb.connect(str(DB_PATH), read_only=True)


def run_query(sql: str) -> dict[str, Any]:
    con = open_connection()
    try:
        result = con.execute(sql)
        columns = [item[0] for item in result.description]
        rows = result.fetchall()
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "markdown": format_markdown(columns, rows),
        }
    finally:
        con.close()


def ensure_read_only_sql(sql: str) -> str:
    candidate = sql.strip().rstrip(";")
    if not re.match(r"^(select|with|show|describe)\b", candidate, flags=re.IGNORECASE):
        raise ValueError("A API aceita apenas consultas de leitura.")
    return candidate


def clamp_page(value: int) -> int:
    return max(1, int(value))


def clamp_page_size(value: int) -> int:
    return max(1, min(int(value), REPORT_PAGE_SIZE_LIMIT))


def get_report_spec(report_name: str) -> dict[str, Any]:
    try:
        return REPORT_SPECS[report_name]
    except KeyError as exc:
        raise KeyError(f"Relatorio desconhecido: {report_name}") from exc


def list_report_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "title": spec["title"],
            "description": spec["description"],
            "default_page_size": 50,
        }
        for name, spec in REPORT_SPECS.items()
    ]


def run_report(report_name: str, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    spec = get_report_spec(report_name)
    base_sql = ensure_read_only_sql(spec["sql"])
    page = clamp_page(page)
    page_size = clamp_page_size(page_size)
    offset = (page - 1) * page_size

    count_sql = f"SELECT COUNT(*) AS total_rows FROM ({base_sql}) AS report_data"
    page_sql = f"SELECT * FROM ({base_sql}) AS report_data LIMIT {page_size} OFFSET {offset}"

    total_rows_result = run_query(count_sql)
    total_rows = int(total_rows_result["rows"][0][0]) if total_rows_result["rows"] else 0
    total_pages = math.ceil(total_rows / page_size) if total_rows else 0

    page_result = run_query(page_sql)
    return {
        "report_name": report_name,
        "title": spec["title"],
        "description": spec["description"],
        "sql": page_sql,
        "base_sql": base_sql,
        "page": page,
        "page_size": page_size,
        "total_rows": total_rows,
        "total_pages": total_pages,
        "has_previous_page": page > 1,
        "has_next_page": page < total_pages,
        **page_result,
    }


def write_xlsx_report(title: str, columns: list[str], rows: list[tuple[Any, ...]]) -> Path:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{sanitize_filename(title)}_{stamp}.xlsx"
    file_path = EXPORT_DIR / filename

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Resultado"
    sheet.append(columns)
    for row in rows:
        sheet.append(list(row))

    for idx, column in enumerate(columns, start=1):
        width = max(len(str(column)), 14)
        sheet.column_dimensions[get_column_letter(idx)].width = min(width + 2, 42)

    workbook.save(file_path)
    return file_path


def export_query(sql: str, title: str) -> dict[str, Any]:
    sql = ensure_read_only_sql(sql)
    result = run_query(sql)
    file_path = write_xlsx_report(title, result["columns"], result["rows"])
    return {
        **result,
        "file_name": file_path.name,
        "file_path": str(file_path),
        "download_url": f"http://localhost:8001/download/{file_path.name}",
    }


def legacy_question_to_sql(question: str) -> tuple[str, str]:
    q = normalize(question)

    if any(term in q for term in ["top 20 clientes", "clientes por valor", "ranking clientes", "clientes que mais compraram", "valor total dos clientes"]):
        return "Top 20 clientes por valor total", "SELECT * FROM ranking_clientes LIMIT 20"

    if any(term in q for term in ["top 20 produtos", "produtos mais vendidos", "ranking produtos", "produtos por receita"]):
        return "Top 20 produtos mais vendidos", "SELECT * FROM ranking_produtos LIMIT 20"

    if any(term in q for term in ["vendas por mes", "vendas por mês", "evolucao mensal", "receita por mes", "receita por mês"]):
        return "Vendas por mês", "SELECT * FROM vendas_por_mes ORDER BY mes"

    if any(term in q for term in ["sem compra", "90 dias", "churn"]):
        return (
            "Clientes sem compra há mais de 90 dias",
            """
            SELECT cliente, ultima_compra, total_pedidos, valor_total
            FROM ranking_clientes
            WHERE ultima_compra < CURRENT_DATE - INTERVAL '90 days'
            ORDER BY valor_total DESC
            LIMIT 50
            """.strip(),
        )

    if any(term in q for term in ["1 compra", "uma compra", "apenas uma compra", "risco de churn"]):
        return (
            "Clientes com apenas 1 compra",
            """
            SELECT cliente, total_pedidos, valor_total, primeira_compra, ultima_compra
            FROM ranking_clientes
            WHERE total_pedidos = 1
            ORDER BY valor_total DESC
            LIMIT 50
            """.strip(),
        )

    if any(term in q for term in ["resumo geral", "resumo do arquivo", "visao geral", "visão geral"]):
        return (
            "Resumo geral do arquivo",
            """
            SELECT
                COUNT(*) AS total_registros,
                COUNT(DISTINCT cliente) AS total_clientes,
                ROUND(SUM(valor_total), 2) AS receita_total,
                ROUND(AVG(ticket_medio), 2) AS ticket_medio_geral,
                MIN(primeira_compra) AS periodo_inicio,
                MAX(ultima_compra) AS periodo_fim
            FROM ranking_clientes
            """.strip(),
        )

    if re.match(r"^\s*(select|with|show|describe)\b", question, flags=re.IGNORECASE):
        return "Consulta SQL livre", question.strip().rstrip(";")

    raise ValueError(
        "Nao identifiquei uma consulta suportada. Use SQL direto ou use a IA do chat para gerar a consulta."
    )


def get_schema_snapshot() -> dict[str, Any]:
    con = open_connection()
    try:
        tables = con.execute(
            """
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name
            """
        ).fetchall()
        columns = con.execute(
            """
            SELECT table_schema, table_name, column_name, data_type, ordinal_position
            FROM information_schema.columns
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name, ordinal_position
            """
        ).fetchall()
    finally:
        con.close()

    structured: list[dict[str, Any]] = []
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for schema, table, table_type in tables:
        entry = {
            "schema": schema,
            "name": table,
            "type": table_type,
            "columns": [],
        }
        structured.append(entry)
        index[(schema, table)] = entry

    for schema, table, column_name, data_type, ordinal_position in columns:
        entry = index.get((schema, table))
        if entry is None:
            continue
        entry["columns"].append(
            {
                "name": column_name,
                "type": data_type,
                "position": ordinal_position,
            }
        )

    lines = []
    for entry in structured:
        column_text = ", ".join(f"{col['name']}:{col['type']}" for col in entry["columns"])
        lines.append(f"- {entry['name']} ({entry['type']}): {column_text}")

    return {
        "database": DB_PATH.name,
        "table_count": sum(1 for item in structured if item["type"] == "BASE TABLE"),
        "view_count": sum(1 for item in structured if item["type"] == "VIEW"),
        "object_count": len(structured),
        "objects": structured,
        "summary_text": "\n".join(lines),
    }


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        total_registros = run_query("SELECT COUNT(*) AS total_registros FROM scanntech")["rows"][0][0]
        schema = get_schema_snapshot()
        return {
            "ok": True,
            "db_path": DB_PATH.name,
            "total_registros": total_registros,
            "tables": schema["table_count"],
            "views": schema["view_count"],
            "available_reports": AVAILABLE_REPORTS,
            "report_count": len(REPORT_SPECS),
            "schema_summary": schema["summary_text"],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/schema")
def schema() -> dict[str, Any]:
    try:
        return {
            "ok": True,
            **get_schema_snapshot(),
            "available_reports": list_report_specs(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/reports")
def reports() -> dict[str, Any]:
    return {
        "ok": True,
        "report_count": len(REPORT_SPECS),
        "page_size_limit": REPORT_PAGE_SIZE_LIMIT,
        "reports": list_report_specs(),
    }


@app.get("/reports/{report_name}")
def report(report_name: str, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    try:
        return {"ok": True, **run_report(report_name, page=page, page_size=page_size)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/reports/{report_name}/export")
def report_export(report_name: str) -> dict[str, Any]:
    try:
        spec = get_report_spec(report_name)
        export_result = export_query(spec["sql"], spec["title"])
        return {
            "ok": True,
            "report_name": report_name,
            "title": spec["title"],
            "description": spec["description"],
            **export_result,
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/query")
def query(request: SQLRequest) -> dict[str, Any]:
    try:
        sql = ensure_read_only_sql(request.sql)
        query_result = run_query(sql)
        return {
            "ok": True,
            "title": request.title.strip() or "Consulta SQL",
            "question": "",
            "sql": sql,
            **query_result,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/export")
def export(request: SQLRequest) -> dict[str, Any]:
    try:
        sql = ensure_read_only_sql(request.sql)
        export_result = export_query(sql, request.title.strip() or "Exportacao Excel")
        return {
            "ok": True,
            "title": request.title.strip() or "Exportacao Excel",
            "question": "",
            "sql": sql,
            **export_result,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/download/{file_name}")
def download(file_name: str) -> FileResponse:
    file_path = (EXPORT_DIR / file_name).resolve()
    export_root = EXPORT_DIR.resolve()
    if export_root not in file_path.parents or not file_path.exists():
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado")
    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.post("/ask")
def ask(request: QuestionRequest) -> dict[str, Any]:
    try:
        title, sql = legacy_question_to_sql(request.question)
        result = run_query(sql)
        return {
            "ok": True,
            "title": title,
            "question": request.question,
            "sql": sql,
            **result,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def main() -> None:
    parser = argparse.ArgumentParser(description="API local de analise Scanntech")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn_run("api_fastapi:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
