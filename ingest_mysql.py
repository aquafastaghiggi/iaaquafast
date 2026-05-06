"""
==============================================================
 AQUAFAST — Ingestor Scanntech → MySQL (XAMPP)
 BR_PDV + BR_PRD + BR_VTA → 3 tabelas + view unificada
==============================================================

 Uso:
   python ingest_mysql.py

 Requisitos:
   pip install mysql-connector-python pandas rich

 ATENÇÃO: Após o uso, configure credenciais reais no .env e evite expor root.
==============================================================
"""

import mysql.connector
import pandas as pd
import os
import sys
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import track

console = Console()

# ============================================================
#  CONFIGURAÇÕES — ajuste os caminhos dos arquivos
# ============================================================
DB_CONFIG = {
    "host"    : os.getenv("AQUAFAST_MYSQL_HOST", "localhost"),
    "port"    : int(os.getenv("AQUAFAST_MYSQL_PORT", "3306")),
    "user"    : os.getenv("AQUAFAST_MYSQL_USER"),
    "password": os.getenv("AQUAFAST_MYSQL_PASSWORD"),
}
DB_NAME = os.getenv("AQUAFAST_MYSQL_DATABASE")

if not DB_CONFIG["user"] or not DB_CONFIG["password"] or not DB_NAME:
    raise RuntimeError(
        "Set AQUAFAST_MYSQL_USER, AQUAFAST_MYSQL_PASSWORD and AQUAFAST_MYSQL_DATABASE "
        "in the environment or .env file."
    )

# Ajuste os caminhos para os arquivos reais
ARQUIVO_PDV  = r"C:\xampp\htdocs\scantech\BR_PDV_MENSUAL_202603.txt"   # pontos de venda
ARQUIVO_PRD  = r"C:\xampp\htdocs\scantech\BR_PRD_MENSUAL_202603.txt"   # produtos
ARQUIVO_VTA  = r"C:\xampp\htdocs\scantech\BR_VTA_MENSUAL_202603.txt"   # vendas

SEPARADOR = ";"
ENCODING  = "latin-1"
CHUNK_SIZE = 500   # linhas por insert — equilibra velocidade e memória


def conectar(com_banco=True):
    cfg = DB_CONFIG.copy()
    if com_banco:
        cfg["database"] = DB_NAME
    return mysql.connector.connect(**cfg)


def criar_banco(cur):
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    console.print(f"[green]✓[/green] Banco [bold]{DB_NAME}[/bold] pronto")


def criar_tabelas(cur):
    """Cria as 3 tabelas com schema fixo."""

    cur.execute("DROP TABLE IF EXISTS vta")
    cur.execute("DROP TABLE IF EXISTS pdv")
    cur.execute("DROP TABLE IF EXISTS prd")

    cur.execute("""
        CREATE TABLE pdv (
            PDV_ID              INT,
            PDV_CODE            VARCHAR(20),
            PDV_NAME            VARCHAR(200),
            PDV_ADDRESS         VARCHAR(300),
            PDV_LOCATION        VARCHAR(100),
            PDV_STATE           VARCHAR(50),
            PDV_CHECKOUTS       VARCHAR(10),
            PDV_CLASIF_1        VARCHAR(100),
            PDV_CLASIF_2        VARCHAR(100),
            PDV_CLASIF_3        VARCHAR(100),
            PDV_CLASIF_4        VARCHAR(100),
            PDV_CLASIF_5        VARCHAR(100),
            PDV_CNPJ            VARCHAR(20),
            PDV_SOCIAL_NAME     VARCHAR(200),
            PDV_STORE_CHAIN     VARCHAR(100),
            STORE_CLASSIFICATION VARCHAR(100),
            PDV_MICROREGION     VARCHAR(200),
            PRIMARY KEY (PDV_ID)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    console.print("[green]✓[/green] Tabela pdv criada")

    cur.execute("""
        CREATE TABLE prd (
            PROD_ID                 VARCHAR(50),
            PROD_BARCODE            VARCHAR(30),
            PROD_NAME               VARCHAR(300),
            PROD_MANUFACTURER       VARCHAR(200),
            PROD_BRAND              VARCHAR(200),
            PROD_CATEGORY           VARCHAR(200),
            PROD_NET_WEIGHT         VARCHAR(30),
            PROD_CLASIF_1           VARCHAR(100),
            PROD_CLASIF_2           VARCHAR(100),
            PROD_CLASIF_3           VARCHAR(100),
            PROD_CLASIF_4           VARCHAR(100),
            PROD_CLASIF_5           VARCHAR(100),
            EST_MER_1_DESCRIPTION   VARCHAR(100),
            EST_MER_2_DESCRIPTION   VARCHAR(100),
            EST_MER_3_DESCRIPTION   VARCHAR(100),
            EST_MER_4_DESCRIPTION   VARCHAR(100),
            EST_MER_5_DESCRIPTION   VARCHAR(100),
            EST_MER_ID              VARCHAR(50),
            PACK_QUANTITY           VARCHAR(20),
            CONTENT_BARCODE         VARCHAR(30),
            PRIMARY KEY (PROD_ID)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    console.print("[green]✓[/green] Tabela prd criada")

    cur.execute("""
        CREATE TABLE vta (
            MONTH_ID        VARCHAR(10),
            PDV_ID          INT,
            PROD_ID         VARCHAR(50),
            SALES_UNITS     DECIMAL(15,5),
            GROSS_SELLOUT   DECIMAL(15,5),
            INDEX idx_pdv  (PDV_ID),
            INDEX idx_prod (PROD_ID),
            INDEX idx_month (MONTH_ID)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    console.print("[green]✓[/green] Tabela vta criada")


def limpar_valor(val):
    """Converte vírgula decimal para ponto e trata nulos."""
    if pd.isna(val) or val == "" or val is None:
        return None
    s = str(val).strip().strip('"')
    if s in ("", "Nulo", "NULL", "null"):
        return None
    return s.replace(",", ".")


def importar_csv(con, cur, arquivo, tabela, colunas_numericas=None):
    """Importa CSV em chunks para o MySQL."""
    console.print(f"\n[yellow]Importando {tabela} — {arquivo}...[/yellow]")

    if not os.path.exists(arquivo):
        console.print(f"[red]✗ Arquivo não encontrado: {arquivo}[/red]")
        return 0

    mb = os.path.getsize(arquivo) / 1024 / 1024
    console.print(f"[dim]Tamanho: {mb:.1f} MB[/dim]")

    total_inserido = 0
    colunas_numericas = colunas_numericas or []

    # Lê o CSV em chunks para não estourar memória
    reader = pd.read_csv(
        arquivo,
        sep=SEPARADOR,
        encoding=ENCODING,
        dtype=str,
        chunksize=CHUNK_SIZE,
        on_bad_lines="skip",
        quotechar='"'
    )

    for chunk in reader:
        # Limpa os dados
        chunk = chunk.where(pd.notnull(chunk), None)

        # Remove aspas extras dos nomes de coluna
        chunk.columns = [c.strip().strip('"') for c in chunk.columns]

        rows = []
        for _, row in chunk.iterrows():
            linha = []
            for col in chunk.columns:
                val = row.get(col)
                linha.append(limpar_valor(val))
            rows.append(tuple(linha))

        if not rows:
            continue

        placeholders = ", ".join(["%s"] * len(chunk.columns))
        cols = ", ".join([f"`{c}`" for c in chunk.columns])
        sql = f"INSERT IGNORE INTO `{tabela}` ({cols}) VALUES ({placeholders})"

        try:
            cur.executemany(sql, rows)
            con.commit()
            total_inserido += len(rows)
        except Exception as e:
            console.print(f"[yellow]⚠ Erro em chunk: {e}[/yellow]")
            con.rollback()

    console.print(f"[green]✓[/green] {tabela}: [bold]{total_inserido:,}[/bold] registros importados")
    return total_inserido


def criar_view_unificada(cur):
    """Cria a view principal com JOIN dos 3 arquivos."""
    console.print("\n[bold]Criando view unificada...[/bold]")

    cur.execute("DROP VIEW IF EXISTS vendas_completa")
    cur.execute("""
        CREATE VIEW vendas_completa AS
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
            d.PDV_SOCIAL_NAME       AS razao_social_loja

        FROM vta v
        LEFT JOIN prd p ON v.PROD_ID = p.PROD_ID
        LEFT JOIN pdv d ON v.PDV_ID  = d.PDV_ID
    """)
    console.print("[green]✓[/green] View vendas_completa criada")


def criar_views_analiticas(cur):
    """Cria views prontas para o Metabase."""
    console.print("\n[bold]Criando views analíticas...[/bold]")

    views = [
        ("market_share_fabricante", """
            SELECT
                fabricante,
                COUNT(DISTINCT produto)  AS skus,
                COUNT(DISTINCT PDV_ID)   AS pdvs_presentes,
                ROUND(SUM(unidades), 0)  AS total_unidades,
                ROUND(SUM(receita), 2)   AS total_receita,
                ROUND(SUM(receita) / (SELECT SUM(receita) FROM vendas_completa) * 100, 2) AS market_share_pct
            FROM vendas_completa
            WHERE fabricante IS NOT NULL
            GROUP BY fabricante
            ORDER BY total_receita DESC
        """),
        ("vendas_por_estado", """
            SELECT
                estado,
                COUNT(DISTINCT PDV_ID)     AS total_pdvs,
                COUNT(DISTINCT fabricante) AS fabricantes,
                ROUND(SUM(unidades), 0)    AS total_unidades,
                ROUND(SUM(receita), 2)     AS total_receita
            FROM vendas_completa
            WHERE estado IS NOT NULL
            GROUP BY estado
            ORDER BY total_receita DESC
        """),
        ("ranking_redes", """
            SELECT
                rede,
                tipo_loja,
                COUNT(DISTINCT PDV_ID)     AS total_lojas,
                COUNT(DISTINCT fabricante) AS fabricantes,
                ROUND(SUM(unidades), 0)    AS total_unidades,
                ROUND(SUM(receita), 2)     AS total_receita
            FROM vendas_completa
            WHERE rede IS NOT NULL AND rede != ''
            GROUP BY rede, tipo_loja
            ORDER BY total_receita DESC
        """),
        ("top_categorias", """
            SELECT
                categoria,
                COUNT(DISTINCT fabricante) AS fabricantes,
                COUNT(DISTINCT produto)    AS skus,
                ROUND(SUM(unidades), 0)    AS total_unidades,
                ROUND(SUM(receita), 2)     AS total_receita
            FROM vendas_completa
            WHERE categoria IS NOT NULL
            GROUP BY categoria
            ORDER BY total_receita DESC
        """),
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
        ("pdvs_por_microrregiao", """
            SELECT
                microrregiao,
                estado,
                COUNT(DISTINCT PDV_ID)  AS total_pdvs,
                COUNT(DISTINCT rede)    AS redes,
                ROUND(SUM(receita), 2)  AS receita_total,
                ROUND(AVG(receita), 2)  AS receita_media_pdv
            FROM vendas_completa
            WHERE microrregiao IS NOT NULL
            GROUP BY microrregiao, estado
            ORDER BY receita_total DESC
        """),
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
        ("resumo_executivo", """
            SELECT
                MONTH_ID                           AS mes,
                COUNT(DISTINCT PDV_ID)             AS total_pdvs,
                COUNT(DISTINCT fabricante)         AS total_fabricantes,
                COUNT(DISTINCT produto)            AS total_produtos,
                COUNT(DISTINCT categoria)          AS total_categorias,
                COUNT(DISTINCT estado)             AS total_estados,
                ROUND(SUM(unidades), 0)            AS total_unidades,
                ROUND(SUM(receita), 2)             AS receita_total
            FROM vendas_completa
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
    """Mostra resumo do que foi importado."""
    console.print("\n")
    try:
        cur.execute("SELECT * FROM resumo_executivo")
        row = cur.fetchone()
        if row:
            cols = [d[0] for d in cur.description]
            dados = dict(zip(cols, row))
            console.print(Panel(
                f"[bold]Mês:[/bold] {dados.get('mes')}\n"
                f"[bold]PDVs monitorados:[/bold] {int(dados.get('total_pdvs',0)):,}\n"
                f"[bold]Fabricantes:[/bold] {int(dados.get('total_fabricantes',0)):,}\n"
                f"[bold]Produtos:[/bold] {int(dados.get('total_produtos',0)):,}\n"
                f"[bold]Categorias:[/bold] {int(dados.get('total_categorias',0)):,}\n"
                f"[bold]Estados:[/bold] {int(dados.get('total_estados',0)):,}\n"
                f"[bold]Unidades vendidas:[/bold] {int(dados.get('total_unidades',0)):,}\n"
                f"[bold]Receita total:[/bold] R$ {float(dados.get('receita_total',0)):,.2f}",
                title="📊 Resumo do mês importado",
                border_style="green"
            ))
    except Exception as e:
        console.print(f"[yellow]Resumo indisponível: {e}[/yellow]")

    console.print("\n[bold]Top 10 fabricantes:[/bold]")
    try:
        cur.execute("SELECT fabricante, total_receita, market_share_pct, pdvs_presentes, skus FROM market_share_fabricante LIMIT 10")
        rows = cur.fetchall()

        table = Table(show_header=True, header_style="bold blue")
        table.add_column("#")
        table.add_column("Fabricante")
        table.add_column("Receita R$", justify="right")
        table.add_column("Share %", justify="right")
        table.add_column("PDVs", justify="right")
        table.add_column("SKUs", justify="right")

        for i, row in enumerate(rows, 1):
            table.add_row(
                str(i),
                str(row[0] or "")[:35],
                f"R$ {float(row[1]):,.2f}",
                f"{float(row[2]):.2f}%",
                str(int(row[3])),
                str(int(row[4])),
            )
        console.print(table)
    except Exception as e:
        console.print(f"[yellow]Ranking indisponível: {e}[/yellow]")


def main():
    console.print(Panel.fit(
        "[bold]🚀 Aquafast — Ingestor Scanntech → MySQL[/bold]\n"
        "3 arquivos CSV → MySQL XAMPP → Metabase",
        border_style="blue"
    ))

    # 1. Conecta sem banco e cria o banco
    console.print("\n[bold]Conectando ao MySQL...[/bold]")
    try:
        con = conectar(com_banco=False)
        cur = con.cursor()
        console.print("[green]✓[/green] Conectado ao MySQL")
        criar_banco(cur)
        con.commit()
        cur.close()
        con.close()
    except Exception as e:
        console.print(f"[red]Erro ao conectar: {e}[/red]")
        sys.exit(1)

    # 2. Conecta no banco e cria tabelas
    con = conectar(com_banco=True)
    cur = con.cursor()

    criar_tabelas(cur)
    con.commit()

    # 3. Importa os 3 arquivos
    importar_csv(con, cur, ARQUIVO_PDV, "pdv")
    importar_csv(con, cur, ARQUIVO_PRD, "prd")
    importar_csv(con, cur, ARQUIVO_VTA, "vta")

    # 4. View unificada e analíticas
    criar_view_unificada(cur)
    criar_views_analiticas(cur)
    con.commit()

    # 5. Resumo
    resumo_final(cur)

    cur.close()
    con.close()

    console.print(f"\n[bold green]✅ Pronto![/bold green]")
    console.print(f"Banco: [cyan]{DB_NAME}[/cyan] no MySQL localhost")
    console.print(f"\nAgora conecte o Metabase:")
    console.print(f"  Host: [cyan]localhost[/cyan]")
    console.print(f"  Porta: [cyan]3306[/cyan]")
    console.print(f"  Banco: [cyan]{DB_NAME}[/cyan]")
    console.print(f"  Usuário: [cyan]{DB_CONFIG['user']}[/cyan]")


if __name__ == "__main__":
    main()
