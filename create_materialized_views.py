import duckdb

DB_PATH = "C:/xampp/htdocs/scantech/aquafast_scanntech.duckdb"
conn = duckdb.connect(DB_PATH, read_only=False)

views = [
    """
    CREATE OR REPLACE TABLE mv_top_produtos AS
    SELECT
        COD_PRODUTO,
        DESC_PRODUTO,
        SUM(QTD) as total_qty,
        SUM(VALOR_TOTAL) as total_valor,
        COUNT(DISTINCT CNPJ) as lojas_presentes
    FROM scanntech
    GROUP BY COD_PRODUTO, DESC_PRODUTO
    ORDER BY total_valor DESC
    """,
    """
    CREATE OR REPLACE TABLE mv_top_redes AS
    SELECT
        RAZAO_SOCIAL,
        COUNT(DISTINCT CNPJ) as total_lojas,
        SUM(VALOR_TOTAL) as total_valor,
        COUNT(DISTINCT COD_PRODUTO) as skus_vendidos
    FROM scanntech
    GROUP BY RAZAO_SOCIAL
    ORDER BY total_valor DESC
    """,
    """
    CREATE OR REPLACE TABLE mv_oportunidades AS
    SELECT
        s.CNPJ,
        s.RAZAO_SOCIAL,
        COUNT(DISTINCT s.COD_PRODUTO) as skus_concorrente,
        COUNT(DISTINCT aq.COD_PRODUTO) as skus_aquafast,
        COUNT(DISTINCT s.COD_PRODUTO) - COUNT(DISTINCT aq.COD_PRODUTO) as gap_skus
    FROM scanntech s
    LEFT JOIN scanntech aq
        ON s.CNPJ = aq.CNPJ
        AND aq.RAZAO_SOCIAL ILIKE '%aquafast%'
    WHERE s.RAZAO_SOCIAL NOT ILIKE '%aquafast%'
    GROUP BY s.CNPJ, s.RAZAO_SOCIAL
    HAVING gap_skus > 0
    ORDER BY gap_skus DESC
    """,
    """
    CREATE OR REPLACE TABLE mv_evolucao_mensal AS
    SELECT
        MONTH_ID,
        SUM(VALOR_TOTAL) as faturamento_total,
        SUM(QTD) as volume_total,
        COUNT(DISTINCT CNPJ) as lojas_ativas,
        COUNT(DISTINCT COD_PRODUTO) as skus_ativos
    FROM scanntech
    GROUP BY MONTH_ID
    ORDER BY MONTH_ID
    """
]

for v in views:
    name = v.strip().split('\n')[0].split('mv_')[1].split(' ')[0]
    print(f"Criando mv_{name}...")
    conn.execute(v)
    print(f"  OK")

conn.close()
print("\nTodas as views materializadas criadas com sucesso.")
