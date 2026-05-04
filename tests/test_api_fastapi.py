from api_fastapi import format_markdown, get_schema_snapshot, legacy_question_to_sql, sanitize_filename


def test_sanitize_filename():
    assert sanitize_filename("Top 20 Produtos Mais Vendidos!") == "top_20_produtos_mais_vendidos"


def test_format_markdown():
    md = format_markdown(["a", "b"], [(1, 2), (3, 4)])
    assert "| a | b |" in md
    assert "| 1 | 2 |" in md
    assert "| 3 | 4 |" in md


def test_legacy_question_to_sql():
    title, sql = legacy_question_to_sql("Top 20 produtos mais vendidos")
    assert title == "Top 20 produtos mais vendidos"
    assert "ranking_produtos" in sql


def test_legacy_question_to_sql_monthly():
    title, sql = legacy_question_to_sql("Vendas por mês")
    assert "Vendas por" in title
    assert "vendas_por_mes" in sql


def test_schema_snapshot_has_objects():
    schema = get_schema_snapshot()
    assert schema["object_count"] >= 1
    assert schema["table_count"] >= 1
