import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aquafast_semantics import list_official_questions, match_route, repair_mojibake, resolve_official_route
from api_fastapi import (
    QUERY_RESULT_ROW_CAP,
    app,
    format_markdown,
    get_schema_snapshot,
    legacy_question_to_sql,
    list_report_specs,
    run_report,
    sanitize_filename,
)


def test_sanitize_filename():
    assert sanitize_filename("Top 20 Produtos Mais Vendidos!") == "top_20_produtos_mais_vendidos"


def test_format_markdown():
    md = format_markdown(["a", "b"], [(1, 2), (3, 4)])
    assert "| a | b |" in md
    assert "| 1 | 2 |" in md
    assert "| 3 | 4 |" in md


def test_format_markdown_ptbr_numbers():
    md = format_markdown(["valor", "share"], [(245528276.34, 23.75), (100617, 1.5)])
    assert "245.528.276,34" in md
    assert "23,75" in md
    assert "100.617" in md


def test_legacy_question_to_sql():
    title, sql = legacy_question_to_sql("Top 20 produtos mais vendidos")
    assert "Aquafast" in title
    assert "ranking_produtos" in sql
    assert "caixas_vendidas" in sql


def test_official_route_resolution():
    route = resolve_official_route("quais produtos teriam mais potencial de venda")
    assert route is not None
    assert route.id == "potencial_venda"
    assert "top_produtos_categoria" in route.sql


def test_match_route_handles_short_count_questions():
    cases = {
        "quantas lojas tem na base": "lojas_hoje",
        "quantas lojas existem": "lojas_hoje",
        "total de lojas": "lojas_hoje",
        "quantos pontos de venda": "pontos_venda",
        "quantas redes existem": "ranking_redes",
        "total de produtos": "top_produtos",
        "quantos produtos na base": "top_produtos",
        "qual o total de clientes": "top_clientes",
    }
    for question, expected in cases.items():
        assert match_route(question) == expected


def test_repair_mojibake():
    assert repair_mojibake("SabÃ£o LÃ­quido") == "Sabão Líquido"


def test_official_questions_catalog_has_20_items():
    items = list_official_questions()
    assert len(items) == 20
    assert any(item["id"] == "pontos_venda" for item in items)


def test_legacy_top_n_clientes():
    title, sql = legacy_question_to_sql("Me mostre o top 7 clientes por valor")
    assert "7" in title
    assert "LIMIT 7" in sql


def test_legacy_top_n_produtos():
    _, sql = legacy_question_to_sql("top 15 produtos")
    assert "LIMIT 15" in sql


def test_legacy_quantos_clientes():
    _, sql = legacy_question_to_sql("Quantos clientes temos na base?")
    assert "COUNT(*) AS TOTAL_LOJAS" in sql.upper()
    assert "ranking_clientes" in sql


def test_legacy_receita_total():
    _, sql = legacy_question_to_sql("Qual a receita total?")
    assert "SUM(RECEITA_TOTAL)" in sql.replace(" ", "").upper() or "sum(receita_total)" in sql.lower()
    assert "caixas_vendidas" in sql


def test_legacy_ultimos_12_meses():
    _, sql = legacy_question_to_sql("Últimos 12 meses de vendas")
    assert "LIMIT 12" in sql
    assert "vendas_por_mes" in sql


def test_legacy_maior_volume_vendas_frase_usuario():
    title, sql = legacy_question_to_sql("qual item tem o maior volume de vendas")
    assert "caixa" in title.lower() or "produto" in title.lower()
    assert "ranking_produtos" in sql
    assert "caixas_vendidas" in sql.lower()


def test_legacy_question_to_sql_monthly():
    title, sql = legacy_question_to_sql("Vendas por mês")
    assert "vendas" in title.lower() or "mes" in title.lower()
    assert "vendas_por_mes" in sql


def test_legacy_market_share_uses_raw_tables():
    _, sql = legacy_question_to_sql("market share por fabricante")
    assert "ms_mercado_aquafast" in sql


def test_legacy_maior_concorrente_uses_market_share_view():
    title, sql = legacy_question_to_sql("qual o maior concorrente de aquafast")
    assert "concorrente" in title.lower()
    assert "ms_mercado_aquafast" in sql
    assert "LOWER(fabricante) <> 'aquafast'" in sql or "lower(fabricante) <> 'aquafast'" in sql.lower()


def test_legacy_potential_uses_top_products_category():
    title, sql = legacy_question_to_sql("quais produtos teriam mais potencial de venda")
    assert "potencial" in title.lower()
    assert "top_produtos_categoria" in sql
    assert "pdvs_com_venda" in sql


def test_schema_snapshot_has_objects():
    schema = get_schema_snapshot()
    assert schema["object_count"] >= 1
    assert schema["table_count"] >= 1


def test_report_catalog_contains_expected_reports():
    reports = list_report_specs()
    names = {item["name"] for item in reports}
    assert {"ranking_clientes", "ranking_produtos", "vendas_por_mes"} <= names


def test_run_report_paginates_results():
    report = run_report("ranking_clientes", page=1, page_size=2)
    assert report["report_name"] == "ranking_clientes"
    assert report["page"] == 1
    assert report["page_size"] == 2
    assert report["row_count"] == 2
    assert report["total_rows"] >= 2


@pytest.mark.skipif(not Path("aquafast_scanntech.duckdb").exists(), reason="duckdb ausente")
def test_post_ask_legacy_top_clientes():
    client = TestClient(app)
    response = client.post("/ask", json={"question": "top 5 clientes por valor"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert re.search(r"\bLIMIT\s+5\b", data["sql"], flags=re.IGNORECASE)


@pytest.mark.skipif(not Path("aquafast_scanntech.duckdb").exists(), reason="duckdb ausente")
def test_post_query_truncates_large_result():
    client = TestClient(app)
    sql = f"SELECT * FROM range({QUERY_RESULT_ROW_CAP + 100})"
    response = client.post("/query", json={"sql": sql, "title": "range"})
    assert response.status_code == 200
    data = response.json()
    assert data["truncated"] is True
    assert data["row_count"] == QUERY_RESULT_ROW_CAP


@pytest.mark.skipif(not Path("aquafast_scanntech.duckdb").exists(), reason="duckdb ausente")
def test_official_questions_endpoint_returns_catalog():
    client = TestClient(app)
    response = client.get("/official-questions")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["count"] == 20
    assert any(item["id"] == "maior_concorrente" for item in data["items"])


@pytest.mark.skipif(not Path("aquafast_scanntech.duckdb").exists(), reason="duckdb ausente")
def test_official_question_detail_endpoint_returns_sql():
    client = TestClient(app)
    response = client.get("/official-questions/potencial_venda")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "top_produtos_categoria" in data["sql"]
