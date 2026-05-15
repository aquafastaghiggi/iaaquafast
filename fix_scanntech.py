import duckdb

con = duckdb.connect("aquafast_scanntech.duckdb")

con.execute("""
CREATE OR REPLACE TABLE scanntech_norm AS
SELECT
    MONTH_ID,
    PDV_ID AS CNPJ,
    CAST(PDV_ID AS VARCHAR) AS RAZAO_SOCIAL,
    PROD_ID AS COD_PRODUTO,
    PROD_ID AS DESC_PRODUTO,
    TRY_CAST(REPLACE(SALES_UNITS, ',', '.') AS DOUBLE) AS QTD,
    TRY_CAST(REPLACE(GROSS_SELLOUT, ',', '.') AS DOUBLE) AS VALOR_TOTAL,
    TRY_CAST(REPLACE(GROSS_SELLOUT, ',', '.') AS DOUBLE)
        / NULLIF(TRY_CAST(REPLACE(SALES_UNITS, ',', '.') AS DOUBLE), 0) AS VALOR_UNITARIO,
    STRPTIME(CAST(MONTH_ID AS VARCHAR), '%Y%m') AS DATA_VENDA
FROM scanntech
""")

con.execute("DROP TABLE scanntech")
con.execute("ALTER TABLE scanntech_norm RENAME TO scanntech")

con.close()

print("OK: tabela scanntech normalizada com VALOR_UNITARIO")