"""
==============================================================
 AQUAFAST — Ingestor Scanntech (3 arquivos)
 BR_PDV + BR_PRD + BR_VTA → DuckDB → view unificada
==============================================================

 Uso:
   python ingest_scanntech_full.py

 Edite as variáveis abaixo com o caminho real dos seus arquivos.
 Requisitos:
   pip install duckdb pandas rich chardet
==============================================================
"""

import duckdb
import os
import sys
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

# ============================================================
#  CONFIGURE AQUI — caminhos dos seus arquivos reais
# ============================================================
ARQUIVO_PDV  = r"BR_PDV_MENSUAL_202603.csv"   # pontos de venda
ARQUIVO_PRD  = r"BR_PRD_MENSUAL_202603.csv"   # produtos
ARQUIVO_VTA  = r"BR_VTA_MENSUAL_202603.csv"   # vendas
DB_PATH      = "scanntech.duckdb"
SEPARADOR    = ";"
ENCODING     = "latin-1"   # tenta latin-1 primeiro — padrão Scanntech BR

# ============================================================
#  NOME DO FABRICANTE DA AQUAFAST — para calcular market share
#  Ajuste para o nome exato que aparece em PROD_MANUFACTURER
# ============================================================
FABRICANTE_AQUAFAST = "AQUAFAST"


def header():
    console.print(Panel.fit(
        "[bold]🚀 Aquafast — Ingestor Scanntech[/bold]\n"
        "3 arquivos → DuckDB → view unificada → Metabase",
        border_style="blue"
    ))


def verificar_arquivos():
    console.print("\n[bold]Verificando arquivos...[/bold]")
    ok = True
    for nome, path in [("PDV", ARQUIVO_PDV), ("PRD", ARQUIVO_PRD), ("VTA", ARQUIVO_VTA)]:
        if os.path.exists(path):
            mb = os.path.getsize(path) / 1024 / 1024
            console.print(f"[green]✓[/green] {nome}: {path} ({mb:.1f} MB)")
        else:
            console.print(f"[red]✗ {nome}: arquivo não encontrado → {path}[/red]")
            ok = False
    if not ok:
        console.print("\n[red]Corrija os caminhos no topo do script e tente novamente.[/red]")
        sys.exit(1)


def importar_tabela(con, arquivo, tabela, separador, encoding):
    """Importa um CSV para uma tabela DuckDB."""
    console.print(f"\n[yellow]Importando {tabela}...[/yellow]")
    path = arquivo.replace("\\", "/")

    try:
        con.execute(f"""
            CREATE OR REPLACE TABLE {tabela} AS
            SELECT * FROM read_csv(
                '{path}',
                delim='{separador}',
                header=true,
                ignore_errors=true,
                all_varchar=true
            )
        """)
    except Exception:
        # Fallback sem encoding explícito
        con.execute(f"""
            CREATE OR REPLACE TABLE {tabela} AS
            SELECT * FROM read_csv_auto(
                '{path}',
                delim='{separador}',
                header=true,
                ignore_errors=true,
                sample_size=10000
            )
        """)

    total = con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
    colunas = len(con.execute(f"DESCRIBE {tabela}").fetchdf())
    console.print(f"[green]✓[/green] {tabela}: [bold]{total:,}[/bold] registros · {colunas} colunas")
    return total


def criar_view_unificada(con):
    """Cria a view principal com JOIN dos 3 arquivos."""
    console.print("\n[bold]Criando view unificada...[/bold]")

    con.execute("""
        CREATE OR REPLACE VIEW vendas_completa AS
        SELECT
            -- Período
            v.MONTH_ID,

            -- Métricas de venda
            TRY_CAST(REPLACE(v.SALES_UNITS,  ',', '.') AS DOUBLE) AS unidades,
            TRY_CAST(REPLACE(v.GROSS_SELLOUT, ',', '.') AS DOUBLE) AS receita,

            -- Produto
            p.PROD_ID,
            p.PROD_BARCODE          AS ean,
            p.PROD_NAME             AS produto,
            p.PROD_MANUFACTURER     AS fabricante,
            p.PROD_BRAND            AS marca,
            p.PROD_CATEGORY         AS categoria,
            p.PROD_NET_WEIGHT       AS peso_volume,
            p.EST_MER_1_DESCRIPTION AS nivel1,
            p.EST_MER_2_DESCRIPTION AS nivel2,
            p.EST_MER_3_DESCRIPTION AS nivel3,
            p.EST_MER_4_DESCRIPTION AS nivel4,

            -- PDV
            d.PDV_ID,
            d.PDV_CODE              AS cod_pdv,
            d.PDV_NAME              AS loja,
            d.PDV_ADDRESS           AS endereco,
            d.PDV_LOCATION          AS cidade,
            d.PDV_STATE             AS estado,
            d.PDV_MICROREGION       AS microrregiao,
            d.PDV_STORE_CHAIN       AS rede,
            d.STORE_CLASSIFICATION  AS tipo_loja,
            TRY_CAST(d.PDV_CHECKOUTS AS INTEGER) AS caixas,
            d.PDV_CNPJ              AS cnpj_loja,
            d.PDV_SOCIAL_NAME       AS razao_social_loja

        FROM vta v
        LEFT JOIN prd p ON v.PROD_ID = p.PROD_ID
        LEFT JOIN pdv d ON v.PDV_ID  = d.PDV_ID
    """)
    total = con.execute("SELECT COUNT(*) FROM vendas_completa").fetchone()[0]
    console.print(f"[green]✓[/green] vendas_completa: [bold]{total:,}[/bold] linhas com JOIN completo")


def criar_views_analiticas(con):
    """Cria views prontas para o Metabase."""
    console.print("\n[bold]Criando views analíticas...[/bold]")

    views = [

        # 1 — Market share por fabricante
        ("market_share_fabricante", """
            WITH total AS (
                SELECT SUM(receita) AS receita_total FROM vendas_completa
            )
            SELECT
                fabricante,
                COUNT(DISTINCT produto)  AS skus,
                COUNT(DISTINCT PDV_ID)   AS pdvs_presentes,
                ROUND(SUM(unidades), 0)  AS total_unidades,
                ROUND(SUM(receita), 2)   AS total_receita,
                ROUND(SUM(receita) / MAX(total.receita_total) * 100, 2) AS market_share_pct
            FROM vendas_completa, total
            WHERE fabricante IS NOT NULL
            GROUP BY fabricante
            ORDER BY total_receita DESC
        """),

        # 2 — Vendas por estado
        ("vendas_por_estado", """
            SELECT
                estado,
                COUNT(DISTINCT PDV_ID)   AS total_pdvs,
                COUNT(DISTINCT fabricante) AS fabricantes,
                ROUND(SUM(unidades), 0)  AS total_unidades,
                ROUND(SUM(receita), 2)   AS total_receita
            FROM vendas_completa
            WHERE estado IS NOT NULL
            GROUP BY estado
            ORDER BY total_receita DESC
        """),

        # 3 — Ranking por rede/bandeira
        ("ranking_redes", """
            SELECT
                rede,
                tipo_loja,
                COUNT(DISTINCT PDV_ID)   AS total_lojas,
                COUNT(DISTINCT fabricante) AS fabricantes,
                ROUND(SUM(unidades), 0)  AS total_unidades,
                ROUND(SUM(receita), 2)   AS total_receita
            FROM vendas_completa
            WHERE rede IS NOT NULL AND rede != ''
            GROUP BY rede, tipo_loja
            ORDER BY total_receita DESC
        """),

        # 4 — Top categorias
        ("top_categorias", """
            SELECT
                categoria,
                nivel3,
                nivel4,
                COUNT(DISTINCT fabricante) AS fabricantes,
                COUNT(DISTINCT produto)    AS skus,
                ROUND(SUM(unidades), 0)   AS total_unidades,
                ROUND(SUM(receita), 2)    AS total_receita
            FROM vendas_completa
            WHERE categoria IS NOT NULL
            GROUP BY categoria, nivel3, nivel4
            ORDER BY total_receita DESC
        """),

        # 5 — Concorrência por categoria e estado
        ("concorrencia_categoria_estado", """
            SELECT
                categoria,
                estado,
                fabricante,
                ROUND(SUM(unidades), 0) AS unidades,
                ROUND(SUM(receita), 2)  AS receita,
                COUNT(DISTINCT PDV_ID)  AS pdvs
            FROM vendas_completa
            WHERE categoria IS NOT NULL AND estado IS NOT NULL
            GROUP BY categoria, estado, fabricante
            ORDER BY categoria, estado, receita DESC
        """),

        # 6 — PDVs por microrregião com potencial
        ("pdvs_por_microrregiao", """
            SELECT
                microrregiao,
                estado,
                COUNT(DISTINCT PDV_ID)     AS total_pdvs,
                COUNT(DISTINCT rede)       AS redes,
                ROUND(SUM(receita), 2)     AS receita_total,
                ROUND(AVG(receita), 2)     AS receita_media_pdv,
                ROUND(AVG(caixas), 1)      AS media_caixas
            FROM vendas_completa
            WHERE microrregiao IS NOT NULL
            GROUP BY microrregiao, estado
            ORDER BY receita_total DESC
        """),

        # 7 — Top produtos da categoria por receita
        ("top_produtos_categoria", """
            SELECT
                categoria,
                produto,
                fabricante,
                marca,
                ean,
                COUNT(DISTINCT PDV_ID)  AS pdvs_com_venda,
                ROUND(SUM(unidades), 0) AS total_unidades,
                ROUND(SUM(receita), 2)  AS total_receita,
                ROUND(SUM(receita) / NULLIF(SUM(unidades), 0), 2) AS preco_medio
            FROM vendas_completa
            WHERE produto IS NOT NULL
            GROUP BY categoria, produto, fabricante, marca, ean
            ORDER BY categoria, total_receita DESC
        """),

        # 8 — Resumo executivo do mês
        ("resumo_executivo", """
            SELECT
                MONTH_ID                        AS mes,
                COUNT(DISTINCT PDV_ID)          AS total_pdvs,
                COUNT(DISTINCT fabricante)      AS total_fabricantes,
                COUNT(DISTINCT produto)         AS total_produtos,
                COUNT(DISTINCT categoria)       AS total_categorias,
                COUNT(DISTINCT estado)          AS total_estados,
                ROUND(SUM(unidades), 0)         AS total_unidades,
                ROUND(SUM(receita), 2)          AS receita_total,
                ROUND(AVG(receita / NULLIF(unidades, 0)), 2) AS preco_medio_geral
            FROM vendas_completa
            GROUP BY MONTH_ID
        """),
    ]

    for nome, sql in views:
        try:
            con.execute(f"CREATE OR REPLACE VIEW {nome} AS {sql}")
            total = con.execute(f"SELECT COUNT(*) FROM {nome}").fetchone()[0]
            console.print(f"[green]✓[/green] {nome}: {total:,} linhas")
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow] {nome}: {e}")


def exportar_para_metabase(con):
    """Exporta CSVs para o Metabase consumir."""
    os.makedirs("exports", exist_ok=True)
    console.print("\n[bold]Exportando para Metabase...[/bold]")

    views = [
        "market_share_fabricante",
        "vendas_por_estado",
        "ranking_redes",
        "top_categorias",
        "concorrencia_categoria_estado",
        "pdvs_por_microrregiao",
        "top_produtos_categoria",
        "resumo_executivo",
    ]

    for view in views:
        try:
            path = f"exports/{view}.csv"
            con.execute(f"COPY (SELECT * FROM {view}) TO '{path}' (HEADER, DELIMITER ',')")
            linhas = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
            console.print(f"[green]✓[/green] exports/{view}.csv ({linhas:,} linhas)")
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow] {view}: {e}")


def resumo_final(con):
    """Mostra resumo executivo dos dados importados."""
    console.print("\n")

    try:
        df = con.execute("SELECT * FROM resumo_executivo").fetchdf()
        if not df.empty:
            row = df.iloc[0]
            console.print(Panel(
                f"[bold]Mês:[/bold] {row['mes']}\n"
                f"[bold]PDVs monitorados:[/bold] {int(row['total_pdvs']):,}\n"
                f"[bold]Fabricantes:[/bold] {int(row['total_fabricantes']):,}\n"
                f"[bold]Produtos:[/bold] {int(row['total_produtos']):,}\n"
                f"[bold]Categorias:[/bold] {int(row['total_categorias']):,}\n"
                f"[bold]Estados:[/bold] {int(row['total_estados']):,}\n"
                f"[bold]Unidades vendidas:[/bold] {int(row['total_unidades']):,}\n"
                f"[bold]Receita total monitorada:[/bold] R$ {float(row['receita_total']):,.2f}",
                title="📊 Resumo do mês",
                border_style="green"
            ))
    except Exception:
        pass

    console.print("\n[bold]Top 10 fabricantes por receita:[/bold]")
    try:
        df_ms = con.execute("""
            SELECT fabricante, total_receita, market_share_pct, pdvs_presentes, skus
            FROM market_share_fabricante
            LIMIT 10
        """).fetchdf()

        table = Table(show_header=True, header_style="bold blue")
        table.add_column("#")
        table.add_column("Fabricante")
        table.add_column("Receita R$", justify="right")
        table.add_column("Market Share", justify="right")
        table.add_column("PDVs", justify="right")
        table.add_column("SKUs", justify="right")

        for i, row in df_ms.iterrows():
            table.add_row(
                str(i + 1),
                str(row["fabricante"] or "")[:35],
                f"R$ {float(row['total_receita']):,.2f}",
                f"{float(row['market_share_pct']):.2f}%",
                str(int(row["pdvs_presentes"])),
                str(int(row["skus"])),
            )
        console.print(table)
    except Exception as e:
        console.print(f"[yellow]Não foi possível gerar ranking: {e}[/yellow]")


def main():
    header()
    verificar_arquivos()

    console.print(f"\n[bold]Conectando ao banco:[/bold] {DB_PATH}")
    con = duckdb.connect(DB_PATH)

    # Importa os 3 arquivos
    importar_tabela(con, ARQUIVO_PDV, "pdv", SEPARADOR, ENCODING)
    importar_tabela(con, ARQUIVO_PRD, "prd", SEPARADOR, ENCODING)
    importar_tabela(con, ARQUIVO_VTA, "vta", SEPARADOR, ENCODING)

    # Cria view unificada com JOIN
    criar_view_unificada(con)

    # Cria views analíticas
    criar_views_analiticas(con)

    # Exporta para Metabase
    exportar_para_metabase(con)

    # Resumo final
    resumo_final(con)

    con.close()

    console.print(f"\n[bold green]✅ Pronto![/bold green]")
    console.print(f"Banco salvo em: [cyan]{DB_PATH}[/cyan]")
    console.print(f"CSVs exportados em: [cyan]./exports/[/cyan]")
    console.print(f"\nAcesse o Metabase: [cyan]http://localhost:3001[/cyan]")
    console.print(f"Importe os CSVs da pasta exports/ e monte seus dashboards.")


if __name__ == "__main__":
    main()
