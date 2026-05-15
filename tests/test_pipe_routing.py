from openwebui_scanntech_function import Pipe


def test_excel_routing():
    pipe = Pipe()
    assert pipe._is_excel_request("gere o arquivo em excel pra mim")
    assert pipe._is_excel_request("planilha dos top 20 clientes")


def test_chart_routing():
    pipe = Pipe()
    assert pipe._is_chart_request("me mostra isso em um grafico")


def test_data_routing():
    pipe = Pipe()
    assert pipe._looks_like_data_question("top 20 produtos mais vendidos") is True
    assert pipe._looks_like_data_question("top 20 lojas aquafast por caixa") is True
    assert pipe._looks_like_data_question("voce tem acesso a base da scanntech") is False
    assert pipe._looks_like_data_question("como funciona o scanntech analyst") is False


def test_mixed_meta_and_data_routes_to_data_not_pure_chat():
    pipe = Pipe()
    q = "qual sua funcao e me mostre o top 5 clientes por valor"
    assert pipe._looks_like_data_question(q) is True
    assert pipe._is_explicit_chat_question(q) is False


def test_lojas_keyword_routes_as_data():
    pipe = Pipe()
    assert pipe._looks_like_data_question("quantas lojas distintas temos na base?") is True
    assert pipe._looks_like_data_question("qual o maior concorrente da aquafast?") is True


def test_synonym_layer_routes_business_language_as_data():
    pipe = Pipe()
    assert pipe._looks_like_data_question("em quantos pontos de venda a aquafast esta presente hoje") is True
    assert pipe._looks_like_data_question("quais produtos teriam mais potencial de venda") is True


def test_cities_sql_uses_clientes_raw_join():
    pipe = Pipe()
    sql = pipe._build_cities_sql_for_clients(["ACME LTDA"])
    assert "scanntech_clientes_raw" in sql
    assert "PDV_STATE" in sql


def test_clients_month_sql_uses_duckdb_month_slice():
    pipe = Pipe()
    sql = pipe._build_clients_sql_for_months(["2026-03"])
    assert "SUBSTR(CAST(DATA_VENDA AS VARCHAR), 1, 7)" in sql
    assert "2026-03" in sql


def test_wrap_sql_adds_limit_when_missing():
    pipe = Pipe()
    raw = "SELECT * FROM ranking_clientes ORDER BY valor_total DESC"
    wrapped = pipe._wrap_sql_for_safe_rows(raw, for_export=False)
    assert "_aquafast_safe" in wrapped
    assert "LIMIT 2000" in wrapped


def test_wrap_sql_skips_when_limit_present():
    pipe = Pipe()
    raw = "SELECT * FROM ranking_clientes LIMIT 50"
    assert pipe._wrap_sql_for_safe_rows(raw, for_export=False) == raw


def test_wrap_sql_skips_for_export():
    pipe = Pipe()
    raw = "SELECT * FROM scanntech"
    assert pipe._wrap_sql_for_safe_rows(raw, for_export=True) == raw


def test_single_value_summary_is_not_ranked():
    pipe = Pipe()
    summary = pipe._deterministic_summary("quantas lojas a aquafast tem hoje", ["total_lojas"], [[568]])
    assert "total_lojas" in summary.lower()
    assert "568" in summary
    assert "Top 3" not in summary


def test_analysis_response_hides_sql_and_shows_source_note():
    pipe = Pipe()
    result = {
        "columns": ["total_lojas"],
        "rows": [[568]],
        "markdown": "| total_lojas |\n| --- |\n| 568 |",
        "row_count": 1,
        "title": "Total de lojas Aquafast",
        "source_note": "Fonte: `ranking_clientes`. A consulta conta as lojas/PDVs que aparecem com venda Aquafast no periodo carregado.",
        "sql": "SELECT COUNT(*) AS total_lojas FROM ranking_clientes",
    }
    text = pipe._build_analysis_response("quantas lojas a aquafast tem hoje?", result, result["sql"])
    assert "Consulta executada" not in text
    assert "Fonte:" in text
    assert "ranking_clientes" in text
