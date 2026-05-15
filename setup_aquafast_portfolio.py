"""
==============================================================
 AQUAFAST — Importa portfólio e cria views focadas
 Excel de produtos → MySQL → views de mercado Aquafast
==============================================================

 Uso:
   python setup_aquafast_portfolio.py

 Requisitos:
   pip install mysql-connector-python pandas openpyxl rich
==============================================================
"""

import mysql.connector
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
import sys

console = Console()

DB_CONFIG = {
    "host"    : "localhost",
    "port"    : 3306,
    "user"    : "root",
    "password": "k7m2y9u4",
    "database": "scanntech",
}

ARQUIVO_EXCEL = r"C:\xampp\htdocs\scantech\padraoProdutos.xlsx"


def importar_portfolio(con, cur):
    """Importa o Excel do portfólio Aquafast para o MySQL."""
    console.print("\n[bold]Importando portfólio Aquafast...[/bold]")

    df = pd.read_excel(ARQUIVO_EXCEL, sheet_name="data")
    df = df[["PROD_CATEGORY", "PROD_CLASIF_2", "SUBGRUPO E LITRAGEM", "QTDE.CX", "SUBGRUPO E LITRAGEM CIGAM"]]
    df.columns = ["PROD_CATEGORY", "LITRAGEM", "SUBGRUPO_LITRAGEM", "QTDE_CX", "SUBGRUPO_CIGAM"]
    df = df.dropna(subset=["PROD_CATEGORY"])
    df = df[df["PROD_CATEGORY"].str.strip() != ""]

    cur.execute("DROP TABLE IF EXISTS aquafast_portfolio")
    cur.execute("""
        CREATE TABLE aquafast_portfolio (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            PROD_CATEGORY   VARCHAR(100),
            LITRAGEM        VARCHAR(20),
            SUBGRUPO_LITRAGEM VARCHAR(100),
            QTDE_CX         INT,
            SUBGRUPO_CIGAM  VARCHAR(150),
            INDEX idx_cat (PROD_CATEGORY),
            INDEX idx_subgrupo (SUBGRUPO_LITRAGEM)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    for _, row in df.iterrows():
        try:
            qtde = int(float(str(row["QTDE_CX"]).replace(",", "."))) if pd.notna(row["QTDE_CX"]) else None
            cur.execute("""
                INSERT INTO aquafast_portfolio 
                (PROD_CATEGORY, LITRAGEM, SUBGRUPO_LITRAGEM, QTDE_CX, SUBGRUPO_CIGAM)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                str(row["PROD_CATEGORY"]).strip() if pd.notna(row["PROD_CATEGORY"]) else None,
                str(row["LITRAGEM"]).strip() if pd.notna(row["LITRAGEM"]) else None,
                str(row["SUBGRUPO_LITRAGEM"]).strip() if pd.notna(row["SUBGRUPO_LITRAGEM"]) else None,
                qtde,
                str(row["SUBGRUPO_CIGAM"]).strip() if pd.notna(row["SUBGRUPO_CIGAM"]) else None,
            ))
        except Exception as e:
            console.print(f"[yellow]⚠ Linha ignorada: {e}[/yellow]")

    con.commit()
    total = cur.execute("SELECT COUNT(*) FROM aquafast_portfolio") or cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM aquafast_portfolio")
    total = cur.fetchone()[0]
    console.print(f"[green]✓[/green] aquafast_portfolio: [bold]{total}[/bold] combinações importadas")

    # Mostra as categorias importadas
    cur.execute("SELECT DISTINCT PROD_CATEGORY FROM aquafast_portfolio ORDER BY PROD_CATEGORY")
    cats = [r[0] for r in cur.fetchall()]
    console.print(f"[green]✓[/green] Categorias Aquafast: [bold]{', '.join(cats)}[/bold]")
    return cats


def criar_view_mercado_aquafast(cur, categorias):
    """
    View que filtra o banco Scanntech APENAS para as categorias
    onde a Aquafast compete — elimina cera, saco de lixo, etc.
    """
    console.print("\n[bold]Criando view mercado_aquafast...[/bold]")

    # Monta lista de categorias para o IN clause
    cats_sql = ", ".join([f"'{c}'" for c in categorias])

    cur.execute("DROP VIEW IF EXISTS mercado_aquafast")
    cur.execute(f"""
        CREATE VIEW mercado_aquafast AS
        SELECT
            v.MONTH_ID,
            v.SALES_UNITS   AS unidades,
            v.GROSS_SELLOUT AS receita,

            p.PROD_ID,
            p.PROD_BARCODE          AS ean,
            p.PROD_NAME             AS produto,
            p.PROD_MANUFACTURER     AS fabricante,
            p.PROD_BRAND            AS marca,
            p.PROD_CATEGORY         AS categoria,
            p.PROD_NET_WEIGHT       AS peso_volume,
            p.PROD_CLASIF_2         AS litragem,
            p.EST_MER_3_DESCRIPTION AS nivel3,
            p.EST_MER_4_DESCRIPTION AS nivel4,

            d.PDV_ID,
            d.PDV_NAME              AS loja,
            d.PDV_LOCATION          AS cidade,
            d.PDV_STATE             AS estado,
            d.PDV_MICROREGION       AS microrregiao,
            d.PDV_STORE_CHAIN       AS rede,
            d.STORE_CLASSIFICATION  AS tipo_loja,
            d.PDV_CHECKOUTS         AS caixas,
            d.PDV_CNPJ              AS cnpj_loja,
            d.PDV_SOCIAL_NAME       AS razao_social_loja,

            -- Flag se é produto Aquafast
            CASE WHEN p.PROD_MANUFACTURER = 'AQUAFAST' THEN 1 ELSE 0 END AS is_aquafast

        FROM vta v
        LEFT JOIN prd p ON v.PROD_ID = p.PROD_ID
        LEFT JOIN pdv d ON v.PDV_ID  = d.PDV_ID
        WHERE p.PROD_CATEGORY IN ({cats_sql})
    """)
    console.print("[green]✓[/green] mercado_aquafast — só categorias do portfólio Aquafast")


def criar_view_vendas_caixas(cur):
    """
    View que converte unidades Scanntech em caixas Aquafast.
    Cruza pela categoria + litragem do portfólio.
    """
    console.print("\n[bold]Criando view vendas_em_caixas...[/bold]")

    cur.execute("DROP VIEW IF EXISTS vendas_em_caixas")
    cur.execute("""
        CREATE VIEW vendas_em_caixas AS
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
            ROUND(SUM(m.unidades), 0)                              AS total_unidades,
            ROUND(SUM(m.receita), 2)                               AS total_receita,
            ap.QTDE_CX                                             AS unidades_por_caixa,
            ROUND(SUM(m.unidades) / NULLIF(ap.QTDE_CX, 0), 1)     AS total_caixas,
            ROUND(SUM(m.receita) / NULLIF(SUM(m.unidades), 0), 2) AS preco_medio_unitario,
            ROUND(
                SUM(m.receita) / NULLIF(SUM(m.unidades) / NULLIF(ap.QTDE_CX, 0), 0),
                2
            )                                                      AS preco_medio_caixa
        FROM mercado_aquafast m
        LEFT JOIN aquafast_portfolio ap
            ON m.categoria = ap.PROD_CATEGORY
            AND m.litragem = ap.LITRAGEM
        GROUP BY
            m.MONTH_ID, m.fabricante, m.marca, m.categoria,
            m.litragem, m.produto, m.estado, m.microrregiao,
            m.rede, m.tipo_loja, m.loja, m.PDV_ID,
            m.is_aquafast, ap.QTDE_CX
    """)
    console.print("[green]✓[/green] vendas_em_caixas — unidades convertidas para caixas")


def criar_views_estrategicas(cur):
    """Views prontas para perguntas estratégicas do comercial."""
    console.print("\n[bold]Criando views estratégicas...[/bold]")

    views = [

        # Market share só no mercado Aquafast
        ("ms_mercado_aquafast", """
            SELECT
                fabricante,
                COUNT(DISTINCT produto)  AS skus,
                COUNT(DISTINCT PDV_ID)   AS pdvs,
                ROUND(SUM(unidades), 0)  AS total_unidades,
                ROUND(SUM(receita), 2)   AS total_receita,
                ROUND(SUM(receita) / (SELECT SUM(receita) FROM mercado_aquafast) * 100, 2) AS market_share_pct,
                MAX(is_aquafast)         AS is_aquafast
            FROM mercado_aquafast
            WHERE fabricante IS NOT NULL
            GROUP BY fabricante
            ORDER BY total_receita DESC
        """),

        # Concorrência por categoria — foco Aquafast
        ("concorrencia_por_categoria", """
            SELECT
                categoria,
                litragem,
                fabricante,
                ROUND(SUM(unidades), 0)  AS unidades,
                ROUND(SUM(receita), 2)   AS receita,
                COUNT(DISTINCT PDV_ID)   AS pdvs,
                MAX(is_aquafast)         AS is_aquafast
            FROM mercado_aquafast
            WHERE categoria IS NOT NULL
            GROUP BY categoria, litragem, fabricante
            ORDER BY categoria, litragem, receita DESC
        """),

        # PDVs onde Aquafast NÃO está mas concorrente está
        # = oportunidades de prospecção
        ("oportunidades_prospeccao", """
            SELECT
                d.PDV_ID,
                d.PDV_NAME   AS loja,
                d.PDV_STATE  AS estado,
                d.PDV_MICROREGION AS microrregiao,
                d.PDV_STORE_CHAIN AS rede,
                d.STORE_CLASSIFICATION AS tipo_loja,
                COUNT(DISTINCT p.PROD_CATEGORY) AS categorias_sem_aquafast,
                ROUND(SUM(CAST(v.GROSS_SELLOUT AS DECIMAL(15,5))), 2) AS receita_concorrencia
            FROM pdv d
            JOIN vta v ON d.PDV_ID = v.PDV_ID
            JOIN prd p ON v.PROD_ID = p.PROD_ID
            WHERE p.PROD_CATEGORY IN (
                SELECT DISTINCT PROD_CATEGORY FROM aquafast_portfolio
            )
            AND d.PDV_ID NOT IN (
                SELECT DISTINCT PDV_ID FROM mercado_aquafast WHERE is_aquafast = 1
            )
            GROUP BY d.PDV_ID, d.PDV_NAME, d.PDV_STATE, d.PDV_MICROREGION,
                     d.PDV_STORE_CHAIN, d.STORE_CLASSIFICATION
            ORDER BY receita_concorrencia DESC
        """),

        # Preço médio por categoria e litragem vs mercado
        ("comparativo_preco", """
            SELECT
                categoria,
                litragem,
                fabricante,
                COUNT(DISTINCT PDV_ID)                              AS pdvs,
                ROUND(SUM(unidades), 0)                             AS unidades,
                ROUND(SUM(receita) / NULLIF(SUM(unidades), 0), 2)  AS preco_medio_unitario,
                MAX(is_aquafast)                                    AS is_aquafast
            FROM mercado_aquafast
            WHERE litragem IS NOT NULL AND fabricante IS NOT NULL
            GROUP BY categoria, litragem, fabricante
            ORDER BY categoria, litragem, preco_medio_unitario
        """),

        # Vendas em caixas por estado — visão comercial
        ("vendas_caixas_estado", """
            SELECT
                estado,
                categoria,
                litragem,
                fabricante,
                is_aquafast,
                ROUND(SUM(total_caixas), 0)  AS caixas_vendidas,
                ROUND(SUM(total_receita), 2) AS receita_total,
                SUM(pdvs_distintos)          AS pdvs
            FROM (
                SELECT
                    estado, categoria, litragem, fabricante, is_aquafast,
                    ROUND(SUM(unidades) / NULLIF(MAX(unidades_por_caixa), 0), 0) AS total_caixas,
                    ROUND(SUM(receita), 2) AS total_receita,
                    COUNT(DISTINCT PDV_ID) AS pdvs_distintos
                FROM vendas_em_caixas
                GROUP BY estado, categoria, litragem, fabricante, is_aquafast
            ) sub
            GROUP BY estado, categoria, litragem, fabricante, is_aquafast
            ORDER BY estado, categoria, caixas_vendidas DESC
        """),

        # Resumo executivo só do mercado Aquafast
        ("resumo_mercado_aquafast", """
            SELECT
                MONTH_ID                                    AS mes,
                COUNT(DISTINCT categoria)                   AS categorias_monitoradas,
                COUNT(DISTINCT fabricante)                  AS fabricantes_no_mercado,
                COUNT(DISTINCT CASE WHEN is_aquafast=1 THEN PDV_ID END) AS pdvs_com_aquafast,
                COUNT(DISTINCT CASE WHEN is_aquafast=0 THEN PDV_ID END) AS pdvs_so_concorrencia,
                ROUND(SUM(CASE WHEN is_aquafast=1 THEN receita END), 2) AS receita_aquafast,
                ROUND(SUM(CASE WHEN is_aquafast=0 THEN receita END), 2) AS receita_concorrencia,
                ROUND(SUM(receita), 2)                      AS receita_total_mercado,
                ROUND(SUM(CASE WHEN is_aquafast=1 THEN receita END) / SUM(receita) * 100, 2) AS share_aquafast_pct
            FROM mercado_aquafast
            GROUP BY MONTH_ID
        """),
    ]

    for nome, sql in views:
        try:
            cur.execute(f"DROP VIEW IF EXISTS {nome}")
            cur.execute(f"CREATE VIEW {nome} AS {sql}")
            console.print(f"[green]✓[/green] {nome}")
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow] {nome}: {e}")


def resumo_final(cur):
    """Mostra o resumo do mercado focado na Aquafast."""
    console.print("\n")
    try:
        cur.execute("SELECT * FROM resumo_mercado_aquafast")
        row = cur.fetchone()
        if row:
            cols = [d[0] for d in cur.description]
            dados = dict(zip(cols, row))
            console.print(Panel(
                f"[bold]Mês:[/bold] {dados.get('mes')}\n"
                f"[bold]Categorias monitoradas:[/bold] {dados.get('categorias_monitoradas')}\n"
                f"[bold]Fabricantes no mercado:[/bold] {dados.get('fabricantes_no_mercado')}\n"
                f"[bold]PDVs com Aquafast:[/bold] {int(dados.get('pdvs_com_aquafast') or 0):,}\n"
                f"[bold]PDVs só com concorrência:[/bold] {int(dados.get('pdvs_so_concorrencia') or 0):,}\n"
                f"[bold]Receita Aquafast:[/bold] R$ {float(dados.get('receita_aquafast') or 0):,.2f}\n"
                f"[bold]Receita concorrência:[/bold] R$ {float(dados.get('receita_concorrencia') or 0):,.2f}\n"
                f"[bold]Receita total do mercado:[/bold] R$ {float(dados.get('receita_total_mercado') or 0):,.2f}\n"
                f"[bold]Market share Aquafast:[/bold] {float(dados.get('share_aquafast_pct') or 0):.2f}%",
                title="📊 Mercado Aquafast — Março 2026",
                border_style="green"
            ))
    except Exception as e:
        console.print(f"[yellow]Resumo indisponível: {e}[/yellow]")

    # Top concorrentes no mercado Aquafast
    console.print("\n[bold]Top 10 concorrentes no mercado Aquafast:[/bold]")
    try:
        cur.execute("""
            SELECT fabricante, total_receita, market_share_pct, pdvs, skus, is_aquafast
            FROM ms_mercado_aquafast
            LIMIT 10
        """)
        rows = cur.fetchall()
        table = Table(show_header=True, header_style="bold blue")
        table.add_column("#")
        table.add_column("Fabricante")
        table.add_column("Receita R$", justify="right")
        table.add_column("Share %", justify="right")
        table.add_column("PDVs", justify="right")
        table.add_column("SKUs", justify="right")
        table.add_column("Aquafast?", justify="center")

        for i, row in enumerate(rows, 1):
            is_aq = "[green]✓[/green]" if row[5] else ""
            table.add_row(
                str(i),
                str(row[0] or "")[:35],
                f"R$ {float(row[1]):,.2f}",
                f"{float(row[2]):.2f}%",
                f"{int(row[3]):,}",
                str(int(row[4])),
                is_aq,
            )
        console.print(table)
    except Exception as e:
        console.print(f"[yellow]Ranking indisponível: {e}[/yellow]")


def main():
    console.print(Panel.fit(
        "[bold]🚀 Aquafast — Setup portfólio e views estratégicas[/bold]\n"
        "Excel produtos → MySQL → mercado focado → insights",
        border_style="blue"
    ))

    try:
        con = mysql.connector.connect(**DB_CONFIG)
        cur = con.cursor()
        console.print("[green]✓[/green] Conectado ao MySQL")
    except Exception as e:
        console.print(f"[red]Erro ao conectar: {e}[/red]")
        sys.exit(1)

    # 1. Importa portfólio
    categorias = importar_portfolio(con, cur)

    # 2. View mercado filtrado
    criar_view_mercado_aquafast(cur, categorias)

    # 3. View com conversão para caixas
    criar_view_vendas_caixas(cur)

    # 4. Views estratégicas
    criar_views_estrategicas(cur)
    con.commit()

    # 5. Resumo
    resumo_final(cur)

    cur.close()
    con.close()

    console.print(f"\n[bold green]✅ Pronto![/bold green]")
    console.print("\nViews criadas no MySQL:")
    console.print("  [cyan]mercado_aquafast[/cyan]       → só categorias onde Aquafast compete")
    console.print("  [cyan]vendas_em_caixas[/cyan]       → unidades convertidas para caixas")
    console.print("  [cyan]ms_mercado_aquafast[/cyan]    → market share no mercado Aquafast")
    console.print("  [cyan]concorrencia_por_categoria[/cyan] → concorrentes por categoria/litragem")
    console.print("  [cyan]oportunidades_prospeccao[/cyan]   → PDVs sem Aquafast com alto potencial")
    console.print("  [cyan]comparativo_preco[/cyan]      → preço médio Aquafast vs concorrência")
    console.print("  [cyan]vendas_caixas_estado[/cyan]   → vendas em caixas por estado")
    console.print("  [cyan]resumo_mercado_aquafast[/cyan] → KPIs executivos do mês")
    console.print("\nSincronize o schema no Metabase para ver as novas views.")


if __name__ == "__main__":
    main()
