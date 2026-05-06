"""
Aquafast Scanntech API

FastAPI app for deterministic queries, schema inspection and Excel export.
"""

from __future__ import annotations

import argparse
import os
import math
import json
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import mysql.connector
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field
from uvicorn import run as uvicorn_run

from aquafast_semantics import (
    OFFICIAL_QUESTION_ROUTES,
    list_official_questions,
    normalize_business_question,
    repair_mojibake,
    resolve_official_route,
)

APP_NAME = "Aquafast Scanntech API"
DUCKDB_PATH = Path(__file__).with_name("aquafast_scanntech.duckdb")
MYSQL_HOST = os.getenv("AQUAFAST_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("AQUAFAST_MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("AQUAFAST_MYSQL_USER")
MYSQL_PASSWORD = os.getenv("AQUAFAST_MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("AQUAFAST_MYSQL_DATABASE")
CHAT_BACKEND = os.getenv("AQUAFAST_CHAT_BACKEND", "duckdb").strip().lower()
EXPORT_DIR = Path(__file__).with_name("exports") / "generated"
MYSQL_CONNECT_TIMEOUT_SECONDS = int(os.getenv("AQUAFAST_MYSQL_CONNECT_TIMEOUT_SECONDS", "5"))
PORTFOLIO_TABLE = "aquafast_portfolio"
REPORT_SPECS: dict[str, dict[str, Any]] = {
    "ranking_clientes": {
        "title": "Top clientes Aquafast por caixa",
        "description": "Ranking das lojas/PDVs do portifolio Aquafast por caixas vendidas e receita.",
        "sql": "SELECT * FROM ranking_clientes ORDER BY caixas_vendidas DESC, receita_total DESC, cliente",
    },
    "ranking_produtos": {
        "title": "Top produtos Aquafast por caixa",
        "description": "Ranking dos produtos do portifolio Aquafast por caixas vendidas e receita.",
        "sql": "SELECT * FROM ranking_produtos ORDER BY caixas_vendidas DESC, receita_total DESC, produto",
    },
    "vendas_por_mes": {
        "title": "Vendas Aquafast por mes",
        "description": "Serie mensal do portifolio Aquafast em caixas e receita.",
        "sql": "SELECT * FROM vendas_por_mes ORDER BY mes",
    },
    "market_share_fabricante": {
        "title": "Market share Aquafast por fabricante",
        "description": "Participacao de cada fabricante dentro do mercado Aquafast.",
        "sql": "SELECT * FROM ms_mercado_aquafast ORDER BY total_receita DESC LIMIT 20",
    },
    "vendas_por_estado": {
        "title": "Vendas Aquafast por estado",
        "description": "Receita e cobertura por estado dentro do portfolio Aquafast.",
        "sql": "SELECT * FROM vendas_caixas_estado ORDER BY receita_total DESC",
    },
    "ranking_redes": {
        "title": "Ranking de redes Aquafast",
        "description": "Performance de redes e tipos de loja dentro do portfolio Aquafast.",
        "sql": "SELECT * FROM ranking_redes ORDER BY total_receita DESC",
    },
    "top_produtos_categoria": {
        "title": "Top produtos por categoria Aquafast",
        "description": "Produtos mais fortes por categoria, em caixas, dentro do portfolio Aquafast.",
        "sql": "SELECT * FROM top_produtos_categoria ORDER BY caixas_vendidas DESC LIMIT 50",
    },
}
AVAILABLE_REPORTS = list(REPORT_SPECS)
REPORT_PAGE_SIZE_LIMIT = 200
# Limita linhas devolvidas ao chat/Open WebUI (evita travar com SELECT * em fatos enormes).
QUERY_RESULT_ROW_CAP = 2000
# Export Excel: teto para nao estourar RAM com fatos de milhoes de linhas.
EXPORT_RESULT_ROW_CAP = 50_000

_SCHEMA_BOOTSTRAPPED = False

if not MYSQL_USER or not MYSQL_PASSWORD or not MYSQL_DATABASE:
    raise RuntimeError(
        "Set AQUAFAST_MYSQL_USER, AQUAFAST_MYSQL_PASSWORD and AQUAFAST_MYSQL_DATABASE "
        "in the environment or .env file."
    )

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

    header = " | ".join(repair_mojibake(str(column)) for column in columns)
    separator = " | ".join(["---"] * len(columns))
    lines = [f"| {header} |", f"| {separator} |"]

    for row in rows:
        values = [_format_ptbr_value(value) for value in row]
        lines.append(f"| {' | '.join(values)} |")

    return "\n".join(lines)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return repair_mojibake(value)
    return value


def _format_ptbr_number(value: float | int) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    if float(value).is_integer():
        return f"{int(value):,}".replace(",", ".")
    text = f"{float(value):,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _format_ptbr_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _format_ptbr_number(value)
    if isinstance(value, Decimal):
        return _format_ptbr_number(float(value))
    return repair_mojibake(str(value))


def _build_source_note(question: str, title: str, sql: str) -> str:
    text = normalize(" ".join([question, title, sql]))

    if "potencial de venda" in text or "maior potencial" in text:
        return (
            "Fonte: `top_produtos_categoria`. "
            "A consulta usa a presença em PDVs e o volume em caixas como proxy de potencial de venda."
        )
    if any(term in text for term in ["maior concorrente", "concorrentes", "concorrencia", "competidor", "competidores"]):
        return (
            "Fonte: `ms_mercado_aquafast`. "
            "A consulta compara os fabricantes do mercado da categoria e exclui a Aquafast para apontar concorrentes."
        )
    if any(term in text for term in ["market share", "participacao", "share"]):
        return (
            "Fonte: `ms_mercado_aquafast`. "
            "A consulta mede a participacao de cada fabricante dentro do mercado da categoria."
        )
    if any(term in text for term in ["ponto de venda", "pontos de venda", "loja", "lojas", "pdv"]):
        return (
            "Fonte: `ranking_clientes`. "
            "A consulta conta as lojas/PDVs que aparecem com venda Aquafast no periodo carregado."
        )
    if any(term in text for term in ["produto por categoria", "categoria", "litragem", "mix"]):
        return (
            "Fonte: `top_produtos_categoria`. "
            "A consulta cruza o portfolio Aquafast com caixas para enxergar o mix por categoria."
        )
    if any(term in text for term in ["vendas por mes", "vendas por mês", "mensal", "serie mensal", "série mensal"]):
        return (
            "Fonte: `vendas_por_mes`. "
            "A consulta consolida caixas e receita ao longo do tempo para mostrar tendencia mensal."
        )
    if any(term in text for term in ["vendas por estado", "estado", "uf"]):
        return (
            "Fonte: `vendas_caixas_estado`. "
            "A consulta cruza as vendas Aquafast com a UF para mostrar distribuicao geografica."
        )
    if any(term in text for term in ["top produtos", "ranking produtos", "mais vendidos", "receita por produto", "volume de vendas"]):
        return (
            "Fonte: `ranking_produtos`. "
            "A consulta lista os produtos Aquafast com maior volume em caixas e receita."
        )
    if any(term in text for term in ["clientes", "lojas", "churn", "compra"]):
        return (
            "Fonte: `ranking_clientes`. "
            "A consulta resume as lojas Aquafast por caixas vendidas, receita e recorrencia."
        )
    return "Fonte: consulta local no DuckDB usando as views semanticas da Aquafast."


def _build_source_note_clean(question: str, title: str, sql: str) -> str:
    route = resolve_official_route(question) or resolve_official_route(title) or resolve_official_route(sql)
    if route is not None:
        return repair_mojibake(route.source_note)
    text = normalize_business_question(" ".join([question, title, sql]))
    if "potencial de venda" in text or "maior potencial" in text:
        return repair_mojibake(
            "Fonte: `top_produtos_categoria`. "
            "A consulta usa a presenca em PDVs e o volume em caixas como proxy de potencial de venda."
        )
    if any(term in text for term in ["maior concorrente", "concorrentes", "concorrencia", "competidor", "competidores"]):
        return repair_mojibake(
            "Fonte: `ms_mercado_aquafast`. "
            "A consulta compara os fabricantes do mercado da categoria e exclui a Aquafast para apontar concorrentes."
        )
    if any(term in text for term in ["market share", "participacao", "share"]):
        return repair_mojibake(
            "Fonte: `ms_mercado_aquafast`. "
            "A consulta mede a participacao de cada fabricante dentro do mercado da categoria."
        )
    if any(term in text for term in ["ponto de venda", "pontos de venda", "loja", "lojas", "pdv"]):
        return repair_mojibake(
            "Fonte: `ranking_clientes`. "
            "A consulta conta as lojas/PDVs que aparecem com venda Aquafast no periodo carregado."
        )
    if any(term in text for term in ["produto por categoria", "categoria", "litragem", "mix"]):
        return repair_mojibake(
            "Fonte: `top_produtos_categoria`. "
            "A consulta cruza o portfolio Aquafast com caixas para enxergar o mix por categoria."
        )
    if any(term in text for term in ["vendas por mes", "mensal", "serie mensal"]):
        return repair_mojibake(
            "Fonte: `vendas_por_mes`. "
            "A consulta consolida caixas e receita ao longo do tempo para mostrar tendencia mensal."
        )
    if any(term in text for term in ["vendas por estado", "estado", "uf"]):
        return repair_mojibake(
            "Fonte: `vendas_caixas_estado`. "
            "A consulta cruza as vendas Aquafast com a UF para mostrar distribuicao geografica."
        )
    if any(term in text for term in ["top produtos", "ranking produtos", "mais vendidos", "receita por produto", "volume de vendas"]):
        return repair_mojibake(
            "Fonte: `ranking_produtos`. "
            "A consulta lista os produtos Aquafast com maior volume em caixas e receita."
        )
    if any(term in text for term in ["clientes", "lojas", "churn", "compra"]):
        return repair_mojibake(
            "Fonte: `ranking_clientes`. "
            "A consulta resume as lojas Aquafast por caixas vendidas, receita e recorrencia."
        )
    return repair_mojibake("Fonte: consulta local no DuckDB usando as views semanticas da Aquafast.")


def _duckdb_object_exists(con: duckdb.DuckDBPyConnection, object_name: str) -> bool:
    row = con.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
          AND table_name = ?
        LIMIT 1
        """,
        [object_name],
    ).fetchone()
    return row is not None


def _fetch_mysql_portfolio_rows() -> list[tuple[Any, ...]]:
    con = mysql.connector.connect(**_mysql_config())
    cur = None
    try:
        cur = con.cursor()
        cur.execute(
            f"""
            SELECT PROD_CATEGORY, LITRAGEM, SUBGRUPO_LITRAGEM, QTDE_CX, SUBGRUPO_CIGAM
            FROM {PORTFOLIO_TABLE}
            WHERE PROD_CATEGORY IS NOT NULL
            """
        )
        rows = cur.fetchall()
        return rows
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        con.close()


def _bootstrap_duckdb_aquafast_views() -> None:
    global _SCHEMA_BOOTSTRAPPED
    if _SCHEMA_BOOTSTRAPPED:
        return

    con = duckdb.connect(str(DUCKDB_PATH))
    try:
        if not _duckdb_object_exists(con, PORTFOLIO_TABLE):
            rows = _fetch_mysql_portfolio_rows()
            con.execute(
                f"""
                CREATE TABLE {PORTFOLIO_TABLE} (
                    PROD_CATEGORY VARCHAR,
                    LITRAGEM VARCHAR,
                    SUBGRUPO_LITRAGEM VARCHAR,
                    QTDE_CX INTEGER,
                    SUBGRUPO_CIGAM VARCHAR
                )
                """
            )
            if rows:
                normalized = [
                    (
                        row[0].strip() if row[0] is not None and str(row[0]).strip() else None,
                        row[1].strip() if row[1] is not None and str(row[1]).strip() else None,
                        row[2].strip() if row[2] is not None and str(row[2]).strip() else None,
                        int(row[3]) if row[3] is not None else None,
                        row[4].strip() if row[4] is not None and str(row[4]).strip() else None,
                    )
                    for row in rows
                ]
                con.executemany(
                    f"INSERT INTO {PORTFOLIO_TABLE} VALUES (?, ?, ?, ?, ?)",
                    normalized,
                )

        statements = [
            f"""
            CREATE OR REPLACE VIEW mercado_aquafast AS
            SELECT
              s.MONTH_ID,
              s.QTD AS unidades,
              s.VALOR_TOTAL AS receita,
              p.PROD_ID,
              p.PROD_BARCODE AS ean,
              p.PROD_NAME AS produto,
              p.PROD_MANUFACTURER AS fabricante,
              p.PROD_BRAND AS marca,
              p.PROD_CATEGORY AS categoria,
              p.PROD_NET_WEIGHT AS peso_volume,
              p.PROD_CLASIF_2 AS litragem,
              p.EST_MER_3_DESCRIPTION AS nivel3,
              p.EST_MER_4_DESCRIPTION AS nivel4,
              c.PDV_ID,
              c.PDV_NAME AS loja,
              c.PDV_LOCATION AS cidade,
              c.PDV_STATE AS estado,
              c.PDV_MICROREGION AS microrregiao,
              c.PDV_STORE_CHAIN AS rede,
              c.STORE_CLASSIFICATION AS tipo_loja,
              c.PDV_CHECKOUTS AS caixas,
              c.PDV_CNPJ AS cnpj_loja,
              c.PDV_SOCIAL_NAME AS razao_social_loja,
              CASE WHEN LOWER(COALESCE(p.PROD_MANUFACTURER, '')) = 'aquafast' THEN 1 ELSE 0 END AS is_aquafast
            FROM scanntech s
            LEFT JOIN scanntech_produtos_raw p ON s.COD_PRODUTO = p.PROD_ID
            LEFT JOIN scanntech_clientes_raw c
              ON LOWER(TRIM(s.RAZAO_SOCIAL)) = LOWER(TRIM(COALESCE(c.PDV_SOCIAL_NAME, c.PDV_NAME)))
            WHERE p.PROD_CATEGORY IN (SELECT DISTINCT PROD_CATEGORY FROM {PORTFOLIO_TABLE})
            """,
            f"""
            CREATE OR REPLACE VIEW vendas_em_caixas AS
            SELECT
              m.MONTH_ID,
              m.fabricante,
              m.marca,
              m.categoria,
              m.litragem,
              m.produto,
              m.estado,
              m.microrregiao,
              m.rede,
              m.tipo_loja,
              m.loja,
              m.PDV_ID,
              m.is_aquafast,
              ROUND(SUM(m.unidades), 0) AS total_unidades,
              ROUND(SUM(m.unidades), 0) AS unidades,
              ROUND(SUM(m.receita), 2) AS total_receita,
              ROUND(SUM(m.receita), 2) AS receita,
              ap.QTDE_CX AS unidades_por_caixa,
              ROUND(SUM(m.unidades) / NULLIF(ap.QTDE_CX, 0), 1) AS total_caixas,
              ROUND(SUM(m.unidades) / NULLIF(ap.QTDE_CX, 0), 1) AS caixas,
              ROUND(SUM(m.receita) / NULLIF(SUM(m.unidades), 0), 2) AS preco_medio_unitario,
              ROUND(SUM(m.receita) / NULLIF(SUM(m.unidades) / NULLIF(ap.QTDE_CX, 0), 0), 2) AS preco_medio_caixa
            FROM mercado_aquafast m
            LEFT JOIN {PORTFOLIO_TABLE} ap
              ON UPPER(TRIM(COALESCE(m.categoria, ''))) = UPPER(TRIM(COALESCE(ap.PROD_CATEGORY, '')))
             AND UPPER(TRIM(COALESCE(m.litragem, ''))) = UPPER(TRIM(COALESCE(ap.LITRAGEM, '')))
            GROUP BY
              m.MONTH_ID, m.fabricante, m.marca, m.categoria, m.litragem, m.produto,
              m.estado, m.microrregiao, m.rede, m.tipo_loja, m.loja, m.PDV_ID,
              m.is_aquafast, ap.QTDE_CX
            """,
            """
            CREATE OR REPLACE VIEW ranking_clientes AS
            SELECT
              loja AS cliente,
              ROUND(SUM(caixas), 1) AS caixas_vendidas,
              ROUND(SUM(receita), 2) AS receita_total,
              ROUND(SUM(receita) / NULLIF(SUM(caixas), 0), 2) AS ticket_medio_caixa,
              MIN(MONTH_ID) AS primeira_compra,
              MAX(MONTH_ID) AS ultima_compra
            FROM vendas_em_caixas
            WHERE is_aquafast = 1
            GROUP BY loja
            """,
            """
            CREATE OR REPLACE VIEW ranking_produtos AS
            SELECT
              produto,
              categoria,
              litragem,
              fabricante,
              marca,
              ROUND(SUM(unidades), 0) AS total_unidades,
              ROUND(SUM(caixas), 1) AS caixas_vendidas,
              ROUND(SUM(receita), 2) AS receita_total,
              ROUND(SUM(receita) / NULLIF(SUM(caixas), 0), 2) AS preco_medio_caixa
            FROM vendas_em_caixas
            WHERE is_aquafast = 1
            GROUP BY produto, categoria, litragem, fabricante, marca
            """,
            """
            CREATE OR REPLACE VIEW vendas_por_mes AS
            SELECT
              SUBSTR(CAST(MONTH_ID AS VARCHAR), 1, 4) || '-' || SUBSTR(CAST(MONTH_ID AS VARCHAR), 5, 2) AS mes,
              ROUND(SUM(caixas), 1) AS caixas_vendidas,
              ROUND(SUM(receita), 2) AS receita_total,
              COUNT(DISTINCT PDV_ID) AS pdvs_ativos,
              COUNT(DISTINCT categoria) AS categorias
            FROM vendas_em_caixas
            WHERE is_aquafast = 1
            GROUP BY 1
            """,
            """
            CREATE OR REPLACE VIEW ms_mercado_aquafast AS
            SELECT
              fabricante,
              COUNT(DISTINCT produto) AS skus,
              COUNT(DISTINCT PDV_ID) AS pdvs,
              ROUND(SUM(unidades), 0) AS total_unidades,
              ROUND(SUM(receita), 2) AS total_receita,
              ROUND(SUM(receita) / NULLIF((SELECT SUM(receita) FROM mercado_aquafast), 0) * 100, 2) AS market_share_pct,
              MAX(is_aquafast) AS is_aquafast
            FROM mercado_aquafast
            WHERE fabricante IS NOT NULL
            GROUP BY fabricante
            ORDER BY total_receita DESC
            """,
            """
            CREATE OR REPLACE VIEW concorrencia_por_categoria AS
            SELECT
              categoria,
              litragem,
              fabricante,
              ROUND(SUM(unidades), 0) AS unidades,
              ROUND(SUM(receita), 2) AS receita,
              COUNT(DISTINCT PDV_ID) AS pdvs,
              MAX(is_aquafast) AS is_aquafast
            FROM mercado_aquafast
            WHERE categoria IS NOT NULL
            GROUP BY categoria, litragem, fabricante
            ORDER BY categoria, litragem, receita DESC
            """,
            """
            CREATE OR REPLACE VIEW comparativo_preco AS
            SELECT
              categoria,
              litragem,
              fabricante,
              COUNT(DISTINCT PDV_ID) AS pdvs,
              ROUND(SUM(unidades), 0) AS unidades,
              ROUND(SUM(receita) / NULLIF(SUM(unidades), 0), 2) AS preco_medio_unitario,
              MAX(is_aquafast) AS is_aquafast
            FROM mercado_aquafast
            WHERE litragem IS NOT NULL AND fabricante IS NOT NULL
            GROUP BY categoria, litragem, fabricante
            ORDER BY categoria, litragem, preco_medio_unitario
            """,
            """
            CREATE OR REPLACE VIEW vendas_caixas_estado AS
            SELECT
              estado,
              categoria,
              litragem,
              fabricante,
              is_aquafast,
              ROUND(SUM(caixas), 0) AS caixas_vendidas,
              ROUND(SUM(receita), 2) AS receita_total,
              COUNT(DISTINCT PDV_ID) AS pdvs
            FROM vendas_em_caixas
            WHERE is_aquafast = 1
            GROUP BY estado, categoria, litragem, fabricante, is_aquafast
            ORDER BY estado, categoria, caixas_vendidas DESC
            """,
            """
            CREATE OR REPLACE VIEW resumo_mercado_aquafast AS
            SELECT
              MONTH_ID AS mes,
              COUNT(DISTINCT categoria) AS categorias_monitoradas,
              COUNT(DISTINCT fabricante) AS fabricantes_no_mercado,
              COUNT(DISTINCT CASE WHEN is_aquafast = 1 THEN PDV_ID END) AS pdvs_com_aquafast,
              COUNT(DISTINCT CASE WHEN is_aquafast = 0 THEN PDV_ID END) AS pdvs_so_concorrencia,
              ROUND(SUM(CASE WHEN is_aquafast = 1 THEN receita ELSE 0 END), 2) AS receita_aquafast,
              ROUND(SUM(CASE WHEN is_aquafast = 0 THEN receita ELSE 0 END), 2) AS receita_concorrencia,
              ROUND(SUM(receita), 2) AS receita_total_mercado,
              ROUND(SUM(CASE WHEN is_aquafast = 1 THEN receita ELSE 0 END) / NULLIF(SUM(receita), 0) * 100, 2) AS share_aquafast_pct
            FROM mercado_aquafast
            GROUP BY MONTH_ID
            """,
            f"""
            CREATE OR REPLACE VIEW top_produtos_categoria AS
            SELECT
              m.categoria,
              m.produto,
              m.fabricante,
              m.marca,
              ROUND(SUM(m.unidades) / NULLIF(ap.QTDE_CX, 0), 1) AS caixas_vendidas,
              ROUND(SUM(m.unidades), 0) AS total_unidades,
              ROUND(SUM(m.receita), 2) AS total_receita,
              ROUND(SUM(m.receita) / NULLIF(SUM(m.unidades) / NULLIF(ap.QTDE_CX, 0), 0), 2) AS preco_medio_caixa,
              COUNT(DISTINCT m.PDV_ID) AS pdvs_com_venda
            FROM mercado_aquafast m
            LEFT JOIN {PORTFOLIO_TABLE} ap
              ON UPPER(TRIM(COALESCE(m.categoria, ''))) = UPPER(TRIM(COALESCE(ap.PROD_CATEGORY, '')))
             AND UPPER(TRIM(COALESCE(m.litragem, ''))) = UPPER(TRIM(COALESCE(ap.LITRAGEM, '')))
            WHERE m.is_aquafast = 1
              AND ap.QTDE_CX IS NOT NULL
            GROUP BY m.categoria, m.produto, m.fabricante, m.marca, ap.QTDE_CX
            ORDER BY caixas_vendidas DESC
            """,
            """
            CREATE OR REPLACE VIEW ranking_redes AS
            SELECT
              COALESCE(rede, 'SEM REDE') AS rede,
              tipo_loja,
              COUNT(DISTINCT PDV_ID) AS total_lojas,
              COUNT(DISTINCT fabricante) AS fabricantes,
              ROUND(SUM(caixas), 1) AS caixas_vendidas,
              ROUND(SUM(receita), 2) AS total_receita
            FROM vendas_em_caixas
            WHERE is_aquafast = 1
            GROUP BY COALESCE(rede, 'SEM REDE'), tipo_loja
            ORDER BY total_receita DESC
            """,
        ]
        for statement in statements:
            con.execute(statement)
        con.commit()
        _SCHEMA_BOOTSTRAPPED = True
    finally:
        con.close()


def _mysql_config() -> dict[str, Any]:
    return {
        "host": MYSQL_HOST,
        "port": MYSQL_PORT,
        "user": MYSQL_USER,
        "password": MYSQL_PASSWORD,
        "database": MYSQL_DATABASE,
        "connection_timeout": MYSQL_CONNECT_TIMEOUT_SECONDS,
    }


def _bootstrap_compatibility_views() -> None:
    global _SCHEMA_BOOTSTRAPPED
    if _SCHEMA_BOOTSTRAPPED:
        return

    con = mysql.connector.connect(**_mysql_config())
    try:
        cur = con.cursor()
        statements = [
            """
            CREATE OR REPLACE VIEW scanntech_clientes_raw AS
            SELECT
              PDV_ID,
              PDV_CODE,
              PDV_NAME,
              PDV_ADDRESS,
              PDV_LOCATION,
              PDV_STATE,
              CAST(PDV_CHECKOUTS AS UNSIGNED) AS PDV_CHECKOUTS,
              PDV_CLASIF_1,
              PDV_CLASIF_2,
              PDV_CLASIF_3,
              PDV_CLASIF_4,
              PDV_CLASIF_5,
              PDV_CNPJ,
              PDV_SOCIAL_NAME,
              PDV_STORE_CHAIN,
              STORE_CLASSIFICATION,
              PDV_MICROREGION
            FROM pdv
            """,
            """
            CREATE OR REPLACE VIEW scanntech_produtos_raw AS
            SELECT
              PROD_ID,
              PROD_BARCODE,
              PROD_NAME,
              PROD_MANUFACTURER,
              PROD_BRAND,
              PROD_CATEGORY,
              PROD_NET_WEIGHT,
              PROD_CLASIF_1,
              PROD_CLASIF_2,
              PROD_CLASIF_3,
              PROD_CLASIF_4,
              PROD_CLASIF_5,
              EST_MER_1_DESCRIPTION,
              EST_MER_2_DESCRIPTION,
              EST_MER_3_DESCRIPTION,
              EST_MER_4_DESCRIPTION,
              EST_MER_5_DESCRIPTION,
              EST_MER_ID,
              PACK_QUANTITY,
              CONTENT_BARCODE
            FROM prd
            """,
            """
            CREATE OR REPLACE VIEW scanntech_vendas_raw AS
            SELECT
              MONTH_ID,
              PDV_ID,
              PROD_ID,
              SALES_UNITS,
              GROSS_SELLOUT
            FROM vta
            """,
            """
            CREATE OR REPLACE VIEW scanntech AS
            SELECT
              v.MONTH_ID,
              p.PDV_CNPJ AS CNPJ,
              COALESCE(p.PDV_SOCIAL_NAME, p.PDV_NAME) AS RAZAO_SOCIAL,
              v.PROD_ID AS COD_PRODUTO,
              pr.PROD_NAME AS DESC_PRODUTO,
              v.SALES_UNITS AS QTD,
              v.GROSS_SELLOUT AS VALOR_TOTAL,
              ROUND(v.GROSS_SELLOUT / NULLIF(v.SALES_UNITS, 0), 5) AS VALOR_UNITARIO,
              STR_TO_DATE(CONCAT(v.MONTH_ID, '01'), '%Y%m%d') AS DATA_VENDA
            FROM vta v
            LEFT JOIN prd pr ON v.PROD_ID = pr.PROD_ID
            LEFT JOIN pdv p ON v.PDV_ID = p.PDV_ID
            """,
            """
            DROP VIEW IF EXISTS ranking_clientes
            """,
            """
            DROP TABLE IF EXISTS ranking_clientes
            """,
            """
            CREATE TABLE ranking_clientes AS
            SELECT
              COALESCE(p.PDV_SOCIAL_NAME, p.PDV_NAME) AS cliente,
              COUNT(*) AS total_pedidos,
              ROUND(SUM(v.GROSS_SELLOUT), 2) AS valor_total,
              ROUND(SUM(v.GROSS_SELLOUT) / NULLIF(COUNT(*), 0), 2) AS ticket_medio,
              MIN(STR_TO_DATE(CONCAT(v.MONTH_ID, '01'), '%Y%m%d')) AS primeira_compra,
              MAX(STR_TO_DATE(CONCAT(v.MONTH_ID, '01'), '%Y%m%d')) AS ultima_compra
            FROM vta v
            JOIN pdv p ON v.PDV_ID = p.PDV_ID
            GROUP BY p.PDV_ID, p.PDV_SOCIAL_NAME, p.PDV_NAME
            """,
            """
            DROP VIEW IF EXISTS ranking_produtos
            """,
            """
            DROP TABLE IF EXISTS ranking_produtos
            """,
            """
            CREATE TABLE ranking_produtos AS
            SELECT
              pr.PROD_NAME AS produto,
              COUNT(*) AS total_vendas,
              ROUND(SUM(v.GROSS_SELLOUT), 2) AS receita_total
            FROM vta v
            JOIN prd pr ON v.PROD_ID = pr.PROD_ID
            GROUP BY pr.PROD_ID, pr.PROD_NAME
            """,
            """
            DROP VIEW IF EXISTS vendas_por_mes
            """,
            """
            DROP TABLE IF EXISTS vendas_por_mes
            """,
            """
            CREATE TABLE vendas_por_mes AS
            SELECT
              DATE_FORMAT(STR_TO_DATE(CONCAT(MONTH_ID, '01'), '%Y%m%d'), '%Y-%m') AS mes,
              COUNT(*) AS total_pedidos,
              ROUND(SUM(GROSS_SELLOUT), 2) AS receita
            FROM vta
            GROUP BY MONTH_ID
            """,
            """
            DROP VIEW IF EXISTS market_share_fabricante
            """,
            """
            DROP TABLE IF EXISTS market_share_fabricante
            """,
            """
            CREATE TABLE market_share_fabricante AS
            SELECT
              p.PROD_MANUFACTURER AS fabricante,
              COUNT(DISTINCT p.PROD_ID) AS skus,
              COUNT(DISTINCT v.PDV_ID) AS pdvs_presentes,
              ROUND(SUM(v.SALES_UNITS), 0) AS total_unidades,
              ROUND(SUM(v.GROSS_SELLOUT), 2) AS total_receita,
              ROUND(
                SUM(v.GROSS_SELLOUT) / NULLIF((SELECT SUM(GROSS_SELLOUT) FROM vta), 0) * 100,
                2
              ) AS market_share_pct
            FROM vta v
            JOIN prd p ON v.PROD_ID = p.PROD_ID
            WHERE p.PROD_MANUFACTURER IS NOT NULL
            GROUP BY p.PROD_MANUFACTURER
            ORDER BY total_receita DESC
            """,
            """
            DROP VIEW IF EXISTS vendas_por_estado
            """,
            """
            DROP TABLE IF EXISTS vendas_por_estado
            """,
            """
            CREATE TABLE vendas_por_estado AS
            SELECT
              d.PDV_STATE AS estado,
              COUNT(DISTINCT d.PDV_ID) AS total_pdvs,
              COUNT(DISTINCT p.PROD_MANUFACTURER) AS fabricantes,
              ROUND(SUM(v.SALES_UNITS), 0) AS total_unidades,
              ROUND(SUM(v.GROSS_SELLOUT), 2) AS total_receita
            FROM vta v
            JOIN pdv d ON v.PDV_ID = d.PDV_ID
            JOIN prd p ON v.PROD_ID = p.PROD_ID
            WHERE d.PDV_STATE IS NOT NULL
            GROUP BY d.PDV_STATE
            ORDER BY total_receita DESC
            """,
            """
            DROP VIEW IF EXISTS ranking_redes
            """,
            """
            DROP TABLE IF EXISTS ranking_redes
            """,
            """
            CREATE TABLE ranking_redes AS
            SELECT
              COALESCE(d.PDV_STORE_CHAIN, 'SEM REDE') AS rede,
              d.STORE_CLASSIFICATION AS tipo_loja,
              COUNT(DISTINCT d.PDV_ID) AS total_lojas,
              COUNT(DISTINCT p.PROD_MANUFACTURER) AS fabricantes,
              ROUND(SUM(v.SALES_UNITS), 0) AS total_unidades,
              ROUND(SUM(v.GROSS_SELLOUT), 2) AS total_receita
            FROM vta v
            JOIN pdv d ON v.PDV_ID = d.PDV_ID
            JOIN prd p ON v.PROD_ID = p.PROD_ID
            GROUP BY COALESCE(d.PDV_STORE_CHAIN, 'SEM REDE'), d.STORE_CLASSIFICATION
            ORDER BY total_receita DESC
            """,
            """
            DROP VIEW IF EXISTS top_produtos_categoria
            """,
            """
            DROP TABLE IF EXISTS top_produtos_categoria
            """,
            """
            CREATE TABLE top_produtos_categoria AS
            SELECT
              p.PROD_CATEGORY AS categoria,
              p.PROD_NAME AS produto,
              p.PROD_MANUFACTURER AS fabricante,
              p.PROD_BRAND AS marca,
              p.PROD_BARCODE AS ean,
              COUNT(DISTINCT v.PDV_ID) AS pdvs_com_venda,
              ROUND(SUM(v.SALES_UNITS), 0) AS total_unidades,
              ROUND(SUM(v.GROSS_SELLOUT), 2) AS total_receita,
              ROUND(SUM(v.GROSS_SELLOUT) / NULLIF(SUM(v.SALES_UNITS), 0), 2) AS preco_medio
            FROM vta v
            JOIN prd p ON v.PROD_ID = p.PROD_ID
            WHERE p.PROD_CATEGORY IS NOT NULL
            GROUP BY
              p.PROD_CATEGORY,
              p.PROD_NAME,
              p.PROD_MANUFACTURER,
              p.PROD_BRAND,
              p.PROD_BARCODE
            ORDER BY total_receita DESC
            """,
        ]
        for statement in statements:
            cur.execute(statement)
        con.commit()
        cur.close()
        _SCHEMA_BOOTSTRAPPED = True
    finally:
        con.close()


def open_connection():
    if CHAT_BACKEND == "mysql":
        _bootstrap_compatibility_views()
        return mysql.connector.connect(**_mysql_config())
    _bootstrap_duckdb_aquafast_views()
    if not DUCKDB_PATH.exists():
        raise FileNotFoundError(f"Banco nao encontrado: {DUCKDB_PATH}")
    return duckdb.connect(str(DUCKDB_PATH), read_only=True)


def ensure_read_only_sql(sql: str) -> str:
    candidate = sql.strip().rstrip(";")
    if not re.match(r"^(select|with|show|describe)\b", candidate, flags=re.IGNORECASE):
        raise ValueError("A API aceita apenas consultas de leitura.")
    return candidate


def _sql_supports_row_cap(sql: str) -> bool:
    head = sql.strip().lstrip("(").lower()
    return head.startswith("select") or head.startswith("with")


def _strip_trailing_order_by(sql: str) -> str:
    candidate = sql.strip().rstrip(";")
    match = re.search(r"\border\s+by\b", candidate, flags=re.IGNORECASE)
    if not match:
        return candidate
    return candidate[: match.start()].rstrip()


def _execute_sql(con: Any, sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    if CHAT_BACKEND == "mysql":
        cur = con.cursor()
        try:
            cur.execute(sql)
            columns = [item[0] for item in cur.description] if cur.description else []
            rows = cur.fetchall()
            normalized_rows = [tuple(_normalize_value(value) for value in row) for row in rows]
            return columns, normalized_rows
        finally:
            cur.close()

    result = con.execute(sql)
    columns = [item[0] for item in result.description]
    rows = result.fetchall()
    normalized_rows = [tuple(_normalize_value(value) for value in row) for row in rows]
    return columns, normalized_rows


def run_query(sql: str, *, row_cap: int | None = None) -> dict[str, Any]:
    candidate = ensure_read_only_sql(sql.strip().rstrip(";"))
    con = open_connection()
    try:
        truncated = False
        if row_cap is not None and row_cap > 0 and _sql_supports_row_cap(candidate):
            fetch_limit = int(row_cap) + 1
            wrapped = f"SELECT * FROM ({candidate}) AS _aquafast_sub LIMIT {fetch_limit}"
            columns, rows = _execute_sql(con, wrapped)
        else:
            columns, rows = _execute_sql(con, candidate)
        if row_cap is not None and row_cap > 0 and len(rows) > row_cap:
            truncated = True
            rows = rows[:row_cap]

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "markdown": format_markdown(columns, rows),
            "truncated": truncated,
            "row_cap": row_cap,
        }
    finally:
        con.close()


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

    count_sql = f"SELECT COUNT(*) AS total_rows FROM ({_strip_trailing_order_by(base_sql)}) AS report_data"
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
    result = run_query(sql, row_cap=EXPORT_RESULT_ROW_CAP)
    file_path = write_xlsx_report(title, result["columns"], result["rows"])
    return {
        **result,
        "file_name": file_path.name,
        "file_path": str(file_path),
        "download_url": f"http://localhost:8001/download/{file_path.name}",
    }


def legacy_question_to_sql(question: str) -> tuple[str, str]:
    route = resolve_official_route(question)
    if route is not None:
        return route.title, route.sql

    q = normalize_business_question(question)

    m_top_cli = re.search(r"\btop\s+(\d+)\s+clientes", q)
    if m_top_cli:
        n = min(max(int(m_top_cli.group(1)), 1), 200)
        return (
            f"Top {n} clientes Aquafast por caixa",
            f"SELECT * FROM ranking_clientes ORDER BY caixas_vendidas DESC, receita_total DESC, cliente LIMIT {n}",
        )

    m_top_prd = re.search(r"\btop\s+(\d+)\s+produtos", q)
    if m_top_prd:
        n = min(max(int(m_top_prd.group(1)), 1), 200)
        return (
            f"Top {n} produtos Aquafast por caixa",
            f"SELECT * FROM ranking_produtos ORDER BY caixas_vendidas DESC, receita_total DESC, produto LIMIT {n}",
        )

    if any(term in q for term in ["maior concorrente", "maiores concorrentes", "concorrente", "concorrentes", "concorrencia", "competidor", "competidores"]):
        limit = 1 if any(term in q for term in ["maior concorrente", "principal concorrente"]) else 10
        return (
            "Maiores concorrentes da Aquafast",
            f"""
            SELECT
              fabricante,
              skus,
              pdvs,
              total_unidades,
              total_receita,
              market_share_pct
            FROM ms_mercado_aquafast
            WHERE LOWER(fabricante) <> 'aquafast'
            ORDER BY total_receita DESC, market_share_pct DESC, fabricante
            LIMIT {limit}
            """.strip(),
        )

    if any(term in q for term in ["top 20 clientes", "clientes por valor", "ranking clientes", "clientes que mais compraram", "valor total dos clientes"]):
        return "Top clientes Aquafast por caixa", "SELECT * FROM ranking_clientes ORDER BY caixas_vendidas DESC, receita_total DESC, cliente LIMIT 20"

    if any(term in q for term in ["top 20 produtos", "produtos mais vendidos", "ranking produtos", "produtos por receita"]):
        return "Top produtos Aquafast por caixa", "SELECT * FROM ranking_produtos ORDER BY caixas_vendidas DESC, receita_total DESC, produto LIMIT 20"

    if any(term in q for term in ["market share", "participacao", "participação", "fabricantes", "marcas", "marca"]):
        return (
            "Market share Aquafast por fabricante",
            "SELECT * FROM ms_mercado_aquafast ORDER BY total_receita DESC LIMIT 20",
        )

    if any(term in q for term in ["estado", "uf", "vendas por estado"]):
        return (
            "Vendas Aquafast por estado",
            "SELECT * FROM vendas_caixas_estado ORDER BY receita_total DESC",
        )

    if any(term in q for term in ["rede", "bandeira", "ranking de redes"]):
        return (
            "Ranking de redes Aquafast",
            "SELECT * FROM ranking_redes ORDER BY total_receita DESC",
        )

    if any(term in q for term in ["categoria", "litragem", "mix", "produto por categoria"]):
        return (
            "Produtos por categoria Aquafast",
            "SELECT * FROM top_produtos_categoria ORDER BY caixas_vendidas DESC LIMIT 50",
        )

    if any(
        term in q
        for term in [
            "vendas por mes",
            "vendas por mês",
            "evolucao mensal",
            "evolução mensal",
            "receita por mes",
            "receita por mês",
            "serie mensal",
            "série mensal",
            "historico mensal",
            "histórico mensal",
            "comparativo mensal",
        ]
    ):
        return "Vendas Aquafast por mes", "SELECT * FROM vendas_por_mes ORDER BY mes"

    if any(term in q for term in ["ultimos 12 meses", "últimos 12 meses", "ultimo ano", "último ano", "12 meses de vendas"]):
        return (
            "Ultimos 12 meses (vendas Aquafast por mes)",
            "SELECT * FROM vendas_por_mes ORDER BY mes DESC LIMIT 12",
        )

    if any(term in q for term in ["ultimos 6 meses", "últimos 6 meses", "6 meses de vendas"]):
        return (
            "Ultimos 6 meses (vendas Aquafast por mes)",
            "SELECT * FROM vendas_por_mes ORDER BY mes DESC LIMIT 6",
        )

    if any(term in q for term in ["potencial de venda", "mais potencial", "teriam mais potencial", "o que vender", "produto com potencial", "produtos com potencial", "distribuicao", "distribuição"]):
        return (
            "Produtos Aquafast com maior potencial de venda",
            """
            SELECT
                produto,
                categoria,
                fabricante,
                marca,
                pdvs_com_venda,
                caixas_vendidas,
                total_receita,
                preco_medio_caixa
            FROM top_produtos_categoria
            ORDER BY pdvs_com_venda DESC, caixas_vendidas DESC, total_receita DESC, produto
            LIMIT 20
            """.strip(),
        )

    if any(term in q for term in ["pontos de venda", "ponto de venda", "pdv", "presentes hoje", "presente hoje", "presença hoje", "presenca hoje"]):
        return (
            "Total de pontos de venda Aquafast",
            "SELECT COUNT(*) AS total_pontos_de_venda FROM ranking_clientes",
        )

    if any(term in q for term in ["quantos clientes", "quantas lojas", "numero de clientes", "número de clientes", "total de clientes", "quantos pdvs"]):
        return (
            "Total de lojas Aquafast",
            "SELECT COUNT(*) AS total_lojas FROM ranking_clientes",
        )

    if any(term in q for term in ["quantos produtos", "numero de produtos", "número de produtos", "total de produtos distintos", "quantos skus"]):
        return (
            "Total de produtos Aquafast",
            "SELECT COUNT(DISTINCT produto) AS total_produtos FROM ranking_produtos",
        )

    if any(
        term in q
        for term in [
            "receita total",
            "faturamento total",
            "quanto vendemos no total",
            "valor total de vendas",
            "soma de todas as vendas",
        ]
    ) and not any(x in q for x in ["top", "ranking", "lista", "por cliente", "por produto"]):
        return (
            "Receita total agregada Aquafast",
            """
            SELECT
                ROUND(SUM(receita_total), 2) AS receita_total,
                CAST(SUM(caixas_vendidas) AS BIGINT) AS caixas_vendidas,
                ROUND(SUM(receita_total) / NULLIF(SUM(caixas_vendidas), 0), 2) AS ticket_medio_caixa
            FROM ranking_clientes
            """.strip(),
        )

    if any(term in q for term in ["ticket medio ponderado", "ticket médio ponderado", "ticket medio geral", "ticket médio geral"]):
        return (
            "Ticket medio por caixa Aquafast",
            """
            SELECT
                ROUND(SUM(receita_total) / NULLIF(SUM(caixas_vendidas), 0), 2) AS ticket_medio_caixa_ponderado,
                ROUND(AVG(ticket_medio_caixa), 2) AS ticket_medio_simples_entre_lojas
            FROM ranking_clientes
            """.strip(),
        )

    if any(term in q for term in ["clientes com mais pedidos", "mais pedidos por cliente", "quem mais compra em frequencia", "maior numero de pedidos"]):
        return (
            "Lojas com mais caixas (frequencia)",
            """
            SELECT cliente, caixas_vendidas, receita_total, ticket_medio_caixa, primeira_compra, ultima_compra
            FROM ranking_clientes
            ORDER BY caixas_vendidas DESC, receita_total DESC
            LIMIT 50
            """.strip(),
        )

    if any(
        term in q
        for term in [
            "produtos por quantidade",
            "mais vendidos em quantidade",
            "maior volume de vendas",
            "produtos com maior volume",
            "mais unidades vendidas",
        ]
    ):
        return (
            "Produtos com maior volume (caixas)",
            """
            SELECT produto, caixas_vendidas, receita_total
            FROM ranking_produtos
            ORDER BY caixas_vendidas DESC, receita_total DESC
            LIMIT 50
            """.strip(),
        )

    if any(term in q for term in ["receita por produto", "faturamento por produto", "produtos por receita", "ranking de receita por produto"]):
        return (
            "Receita por produto Aquafast (top 30)",
            """
            SELECT produto, caixas_vendidas, receita_total
            FROM ranking_produtos
            ORDER BY receita_total DESC, caixas_vendidas DESC
            LIMIT 30
            """.strip(),
        )

    if any(term in q for term in ["sem compra", "90 dias", "churn"]):
        return (
            "Lojas sem compra há mais de 90 dias",
            """
            SELECT cliente, ultima_compra, caixas_vendidas, receita_total
            FROM ranking_clientes
            WHERE ultima_compra < CURRENT_DATE - INTERVAL '90 days'
            ORDER BY receita_total DESC
            LIMIT 50
            """.strip(),
        )

    if any(term in q for term in ["1 compra", "uma compra", "apenas uma compra", "risco de churn"]):
        return (
            "Lojas com apenas 1 compra",
            """
            SELECT cliente, caixas_vendidas, receita_total, primeira_compra, ultima_compra
            FROM ranking_clientes
            WHERE caixas_vendidas = 1
            ORDER BY receita_total DESC
            LIMIT 50
            """.strip(),
        )

    if any(term in q for term in ["resumo geral", "resumo do arquivo", "visao geral", "visão geral"]):
        return (
            "Resumo geral Aquafast",
            """
            SELECT
                COUNT(*) AS total_registros,
                COUNT(DISTINCT cliente) AS total_clientes,
                ROUND(SUM(receita_total), 2) AS receita_total,
                ROUND(AVG(ticket_medio_caixa), 2) AS ticket_medio_geral,
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
        if CHAT_BACKEND == "mysql":
            tables = _execute_sql(
                con,
                f"""
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = '{MYSQL_DATABASE}'
                ORDER BY table_schema, table_name
                """,
            )[1]
            columns = _execute_sql(
                con,
                f"""
                SELECT table_schema, table_name, column_name, data_type, ordinal_position
                FROM information_schema.columns
                WHERE table_schema = '{MYSQL_DATABASE}'
                ORDER BY table_schema, table_name, ordinal_position
                """,
            )[1]
        else:
            tables = _execute_sql(
                con,
                """
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY table_schema, table_name
                """,
            )[1]
            columns = _execute_sql(
                con,
                """
                SELECT table_schema, table_name, column_name, data_type, ordinal_position
                FROM information_schema.columns
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY table_schema, table_name, ordinal_position
                """,
            )[1]
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
        "database": MYSQL_DATABASE if CHAT_BACKEND == "mysql" else DUCKDB_PATH.name,
        "table_count": sum(1 for item in structured if item["type"] == "BASE TABLE"),
        "view_count": sum(1 for item in structured if item["type"] == "VIEW"),
        "object_count": len(structured),
        "objects": structured,
        "summary_text": "\n".join(lines),
    }


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        health_table = "vta" if CHAT_BACKEND == "mysql" else "scanntech"
        total_registros = run_query(f"SELECT COUNT(*) AS total_registros FROM {health_table}")["rows"][0][0]
        schema = get_schema_snapshot()
        return {
            "ok": True,
            "db_path": MYSQL_DATABASE if CHAT_BACKEND == "mysql" else DUCKDB_PATH.name,
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
        query_result = run_query(sql, row_cap=QUERY_RESULT_ROW_CAP)
        return {
            "ok": True,
            "title": request.title.strip() or "Consulta SQL",
            "question": "",
            "sql": sql,
            "source_note": _build_source_note_clean("", request.title.strip() or "Consulta SQL", sql),
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
            "source_note": _build_source_note_clean("", request.title.strip() or "Exportacao Excel", sql),
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
        result = run_query(sql, row_cap=QUERY_RESULT_ROW_CAP)
        return {
            "ok": True,
            "title": title,
            "question": request.question,
            "sql": sql,
            "source_note": _build_source_note_clean(request.question, title, sql),
            **result,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/official-questions")
def official_questions() -> dict[str, Any]:
    items = list_official_questions()
    return {"ok": True, "count": len(items), "items": items}


@app.get("/official-questions/{question_id}")
def official_question(question_id: str) -> dict[str, Any]:
    for route in OFFICIAL_QUESTION_ROUTES:
        if route.id == question_id:
            return {
                "ok": True,
                "id": repair_mojibake(route.id),
                "title": repair_mojibake(route.title),
                "description": repair_mojibake(route.description),
                "examples": [repair_mojibake(example) for example in route.examples],
                "source_note": repair_mojibake(route.source_note),
                "sql": repair_mojibake(route.sql),
            }
    raise HTTPException(status_code=404, detail="Pergunta oficial nao encontrada")


def main() -> None:
    parser = argparse.ArgumentParser(description="API local de analise Scanntech")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn_run("api_fastapi:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
