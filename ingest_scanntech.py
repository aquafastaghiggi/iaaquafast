"""
==============================================================
 AQUAFAST — Ingestor do arquivo Scanntech
 Converte o CSV/TXT gigante em banco DuckDB consultável
==============================================================

 Uso:
   python ingest_scanntech.py --arquivo caminho/para/scanntech.csv

 Requisitos:
   pip install duckdb pandas rich

 O script:
  1. Detecta o encoding e separador automaticamente
  2. Mostra preview das primeiras linhas para validação
  3. Importa o arquivo completo para DuckDB (suporta 200MB+ tranquilo)
  4. Cria índices para consultas rápidas
  5. Gera relatório de qualidade dos dados
==============================================================
"""

import duckdb
import pandas as pd
import argparse
import sys
import os
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.progress import track
from rich import print as rprint

console = Console()

# ----------------------------------------------------------
#  CONFIGURAÇÕES — ajuste conforme o arquivo real da Scantech
# ----------------------------------------------------------
DB_PATH = "aquafast_scanntech.duckdb"

# Mapeamento de colunas — será atualizado após ver o arquivo real
# Deixamos flexível: o script detecta automaticamente
COLUNAS_ESPERADAS = {
    # nome_no_csv       : nome_amigável
    # Exemplos comuns em arquivos Scanntech — ajuste após ver o header
    "CNPJ"             : "cnpj_cliente",
    "RAZAO_SOCIAL"     : "razao_social",
    "COD_PRODUTO"      : "cod_produto",
    "DESC_PRODUTO"     : "descricao_produto",
    "QTD"              : "quantidade",
    "VALOR"            : "valor_total",
    "DATA"             : "data_venda",
    "UF"               : "estado",
    "CIDADE"           : "cidade",
}


def detectar_separador(arquivo: str, encoding: str) -> str:
    """Detecta automaticamente o separador do CSV."""
    with open(arquivo, "r", encoding=encoding, errors="replace") as f:
        linha = f.readline()
    
    candidatos = [";", ",", "\t", "|"]
    contagens = {sep: linha.count(sep) for sep in candidatos}
    separador = max(contagens, key=contagens.get)
    
    console.print(f"[green]✓[/green] Separador detectado: [bold]{repr(separador)}[/bold]")
    return separador


def detectar_encoding(arquivo: str) -> str:
    """Tenta detectar o encoding do arquivo."""
    try:
        import chardet
        with open(arquivo, "rb") as f:
            raw = f.read(100000)  # Lê primeiros 100KB
        result = chardet.detect(raw)
        enc = result.get("encoding", "utf-8") or "utf-8"
        console.print(f"[green]✓[/green] Encoding detectado: [bold]{enc}[/bold] (confiança: {result.get('confidence', 0):.0%})")
        return enc
    except ImportError:
        # Tenta os mais comuns para arquivos brasileiros
        for enc in ["utf-8", "latin-1", "cp1252", "iso-8859-1"]:
            try:
                with open(arquivo, "r", encoding=enc) as f:
                    f.read(10000)
                console.print(f"[green]✓[/green] Encoding: [bold]{enc}[/bold]")
                return enc
            except UnicodeDecodeError:
                continue
        return "latin-1"


def escolher_coluna_cliente(colunas: list) -> str | None:
    """
    Escolhe a melhor coluna para identificar o cliente.
    Prioriza a razão social para exibição e deixa CNPJ como fallback.
    """
    prioridades = [
        "RAZAO_SOCIAL",
        "RAZAO",
        "CLIENTE",
        "NOME_CLIENTE",
        "COD_CLI",
        "CNPJ",
    ]

    colunas_upper = {c.upper(): c for c in colunas}

    for chave in prioridades:
        for coluna_upper, coluna_original in colunas_upper.items():
            if chave in coluna_upper:
                return coluna_original

    return None


def preview_arquivo(arquivo: str, encoding: str, separador: str, n_linhas: int = 5):
    """Mostra preview das primeiras linhas."""
    console.print("\n[bold cyan]Preview do arquivo:[/bold cyan]")
    
    df_preview = pd.read_csv(
        arquivo,
        sep=separador,
        encoding=encoding,
        nrows=n_linhas,
        dtype=str,
        on_bad_lines="skip"
    )
    
    table = Table(show_header=True, header_style="bold blue")
    for col in df_preview.columns[:10]:  # Mostra no máx 10 colunas
        table.add_column(str(col)[:20], overflow="fold")
    
    for _, row in df_preview.iterrows():
        table.add_row(*[str(v)[:20] for v in row.values[:10]])
    
    console.print(table)
    console.print(f"[dim]Colunas encontradas: {list(df_preview.columns)}[/dim]")
    
    return df_preview.columns.tolist()


def importar_para_duckdb(arquivo: str, encoding: str, separador: str, db_path: str):
    """
    Importa o CSV para DuckDB de forma eficiente.
    DuckDB lê o arquivo em streaming — não carrega tudo na RAM.
    """
    console.print(f"\n[bold]Importando para DuckDB:[/bold] {db_path}")
    
    con = duckdb.connect(db_path)
    
    # DuckDB lê CSV diretamente — muito mais rápido que pandas para arquivos grandes
    console.print("[yellow]Lendo arquivo... (pode levar alguns minutos para 200MB)[/yellow]")
    
    try:
        con.execute(f"""
            CREATE OR REPLACE TABLE scanntech AS
            SELECT * FROM read_csv_auto(
                '{arquivo.replace(chr(92), "/")}',
                delim='{separador}',
                header=true,
                ignore_errors=true,
                sample_size=-1,
                encoding='{encoding}'
            )
        """)
        
        # Conta registros
        total = con.execute("SELECT COUNT(*) FROM scanntech").fetchone()[0]
        console.print(f"[green]✓[/green] Importados: [bold]{total:,}[/bold] registros")
        
        # Mostra schema detectado
        schema = con.execute("DESCRIBE scanntech").fetchdf()
        console.print("\n[bold cyan]Schema detectado:[/bold cyan]")
        
        table = Table(show_header=True, header_style="bold blue")
        table.add_column("Coluna")
        table.add_column("Tipo")
        for _, row in schema.iterrows():
            table.add_row(str(row["column_name"]), str(row["column_type"]))
        console.print(table)
        
        return con, total
        
    except Exception as e:
        console.print(f"[red]Erro na importação automática: {e}[/red]")
        console.print("[yellow]Tentando importação manual com tipos string...[/yellow]")
        
        # Fallback: importa tudo como string
        con.execute(f"""
            CREATE OR REPLACE TABLE scanntech AS
            SELECT * FROM read_csv(
                '{arquivo.replace(chr(92), "/")}',
                delim='{separador}',
                header=true,
                all_varchar=true,
                ignore_errors=true
            )
        """)
        total = con.execute("SELECT COUNT(*) FROM scanntech").fetchone()[0]
        console.print(f"[green]✓[/green] Importados (modo texto): [bold]{total:,}[/bold] registros")
        return con, total


def criar_indices(con: duckdb.DuckDBPyConnection, colunas: list):
    """
    Cria índices nas colunas mais usadas para consultas rápidas.
    DuckDB não usa CREATE INDEX tradicional — usa stats automáticas.
    Mas criamos views e sumários para acelerar.
    """
    console.print("\n[bold]Criando sumários para consultas rápidas...[/bold]")
    
    # Detecta colunas prováveis de data, cliente e produto
    col_lower = [c.lower() for c in colunas]
    
    col_data = next((c for c in colunas if any(k in c.lower() for k in ["data", "date", "dt_", "_dt"])), None)
    col_cliente = escolher_coluna_cliente(colunas)
    col_valor = next((c for c in colunas if any(k in c.lower() for k in ["valor", "total", "vl_", "_vl", "preco"])), None)
    col_produto = next((c for c in colunas if any(k in c.lower() for k in ["produto", "sku", "cod_prod", "descricao"])), None)
    
    console.print(f"[dim]Coluna de data: {col_data}[/dim]")
    console.print(f"[dim]Coluna de cliente: {col_cliente}[/dim]")
    console.print(f"[dim]Coluna de valor: {col_valor}[/dim]")
    console.print(f"[dim]Coluna de produto: {col_produto}[/dim]")
    
    # View de sumário por cliente
    if col_cliente and col_valor:
        try:
            con.execute(f"""
                CREATE OR REPLACE VIEW ranking_clientes AS
                SELECT 
                    "{col_cliente}" as cliente,
                    COUNT(*) as total_pedidos,
                    ROUND(SUM(TRY_CAST("{col_valor}" AS DOUBLE)), 2) as valor_total,
                    ROUND(AVG(TRY_CAST("{col_valor}" AS DOUBLE)), 2) as ticket_medio,
                    MIN("{col_data}") as primeira_compra,
                    MAX("{col_data}") as ultima_compra
                FROM scanntech
                GROUP BY "{col_cliente}"
                ORDER BY valor_total DESC NULLS LAST
            """)
            console.print("[green]✓[/green] View ranking_clientes criada")
        except Exception as e:
            console.print(f"[yellow]⚠ ranking_clientes: {e}[/yellow]")
    
    # View de sumário por produto
    if col_produto and col_valor:
        try:
            con.execute(f"""
                CREATE OR REPLACE VIEW ranking_produtos AS
                SELECT 
                    "{col_produto}" as produto,
                    COUNT(*) as total_vendas,
                    ROUND(SUM(TRY_CAST("{col_valor}" AS DOUBLE)), 2) as receita_total
                FROM scanntech
                GROUP BY "{col_produto}"
                ORDER BY receita_total DESC NULLS LAST
            """)
            console.print("[green]✓[/green] View ranking_produtos criada")
        except Exception as e:
            console.print(f"[yellow]⚠ ranking_produtos: {e}[/yellow]")

    # View de vendas por período
    if col_data and col_valor:
        try:
            con.execute(f"""
                CREATE OR REPLACE VIEW vendas_por_mes AS
                SELECT 
                    SUBSTR(CAST("{col_data}" AS VARCHAR), 1, 7) as mes,
                    COUNT(*) as total_pedidos,
                    ROUND(SUM(TRY_CAST("{col_valor}" AS DOUBLE)), 2) as receita
                FROM scanntech
                GROUP BY 1
                ORDER BY 1
            """)
            console.print("[green]✓[/green] View vendas_por_mes criada")
        except Exception as e:
            console.print(f"[yellow]⚠ vendas_por_mes: {e}[/yellow]")


def relatorio_qualidade(con: duckdb.DuckDBPyConnection, total: int, colunas: list):
    """Gera relatório de qualidade dos dados."""
    console.print("\n[bold cyan]Relatório de qualidade:[/bold cyan]")
    
    table = Table(show_header=True, header_style="bold blue")
    table.add_column("Coluna")
    table.add_column("Nulos")
    table.add_column("Únicos (est.)")
    table.add_column("Exemplo")
    
    for col in colunas[:15]:  # Limita a 15 colunas
        try:
            stats = con.execute(f"""
                SELECT 
                    COUNT(*) - COUNT("{col}") as nulos,
                    APPROX_COUNT_DISTINCT("{col}") as unicos,
                    MAX(CAST("{col}" AS VARCHAR)) as exemplo
                FROM scanntech
            """).fetchone()
            
            pct_nulo = f"{stats[0]/total*100:.1f}%" if total > 0 else "0%"
            table.add_row(
                str(col)[:25],
                f"{stats[0]:,} ({pct_nulo})",
                f"{stats[1]:,}",
                str(stats[2] or "")[:30]
            )
        except Exception:
            table.add_row(str(col)[:25], "?", "?", "?")
    
    console.print(table)


def exportar_config_metabase(db_path: str):
    """Gera arquivo de configuração para conectar o Metabase ao DuckDB."""
    config = f"""
# ============================================================
# INSTRUÇÃO: Conectar Metabase ao DuckDB
# ============================================================
#
# O Metabase não conecta diretamente ao DuckDB.
# Use uma das opções abaixo:
#
# OPÇÃO A (mais simples): 
#   O script já exportou as views para CSV na pasta ./exports/
#   No Metabase: Settings > Databases > Add > Upload CSV
#
# OPÇÃO B (mais poderoso):
#   Instale o plugin DuckDB para Metabase:
#   https://github.com/MotherDuck-Open-Source/metabase-duckdb-driver
#   Copie o .jar para: metabase_plugins/
#   Reinicie o Metabase e adicione conexão tipo DuckDB
#   Path do banco: /metabase-data/{Path(db_path).name}
#
# OPÇÃO C (recomendado para produção):
#   Use o script query_api.py para criar uma API REST
#   que o Metabase consome via connector HTTP
# ============================================================

DB_PATH={db_path}
VIEWS_DISPONIVEIS=ranking_clientes,ranking_produtos,vendas_por_mes
"""
    with open("METABASE_CONFIG.txt", "w") as f:
        f.write(config)
    console.print("[green]✓[/green] Instruções Metabase salvas em METABASE_CONFIG.txt")


def exportar_views_csv(con: duckdb.DuckDBPyConnection):
    """Exporta as views para CSV — para usar direto no Metabase."""
    os.makedirs("exports", exist_ok=True)
    
    views = ["ranking_clientes", "ranking_produtos", "vendas_por_mes"]
    for view in views:
        try:
            con.execute(f"COPY (SELECT * FROM {view}) TO 'exports/{view}.csv' (HEADER, DELIMITER ',')")
            console.print(f"[green]✓[/green] Exportado: exports/{view}.csv")
        except Exception as e:
            console.print(f"[yellow]⚠ Não exportou {view}: {e}[/yellow]")


def main():
    parser = argparse.ArgumentParser(description="Ingestor Scanntech → DuckDB")
    parser.add_argument("--arquivo", required=True, help="Caminho para o CSV/TXT da Scanntech")
    parser.add_argument("--db", default=DB_PATH, help=f"Caminho do banco DuckDB (padrão: {DB_PATH})")
    parser.add_argument("--preview-only", action="store_true", help="Só mostra preview, não importa")
    args = parser.parse_args()
    
    if not os.path.exists(args.arquivo):
        console.print(f"[red]Arquivo não encontrado: {args.arquivo}[/red]")
        sys.exit(1)
    
    tamanho_mb = os.path.getsize(args.arquivo) / 1024 / 1024
    console.print(f"\n[bold]🚀 Aquafast — Ingestor Scanntech[/bold]")
    console.print(f"Arquivo: [cyan]{args.arquivo}[/cyan] ({tamanho_mb:.1f} MB)")
    
    # 1. Detecta formato
    encoding = detectar_encoding(args.arquivo)
    separador = detectar_separador(args.arquivo, encoding)
    
    # 2. Preview
    colunas = preview_arquivo(args.arquivo, encoding, separador)
    
    if args.preview_only:
        console.print("\n[yellow]Modo preview — importação não realizada.[/yellow]")
        console.print("Execute sem --preview-only para importar completo.")
        return
    
    # 3. Confirmação
    console.print(f"\n[bold yellow]Confirma importação de {tamanho_mb:.0f}MB para DuckDB?[/bold yellow]")
    resp = input("Digite 's' para continuar: ").strip().lower()
    if resp != "s":
        console.print("Cancelado.")
        return
    
    # 4. Importa
    con, total = importar_para_duckdb(args.arquivo, encoding, separador, args.db)
    
    # 5. Índices e views
    criar_indices(con, colunas)
    
    # 6. Relatório de qualidade
    relatorio_qualidade(con, total, colunas)
    
    # 7. Exporta para Metabase
    exportar_views_csv(con)
    exportar_config_metabase(args.db)
    
    con.close()
    
    console.print(f"\n[bold green]✅ Pronto![/bold green]")
    console.print(f"Banco salvo em: [cyan]{args.db}[/cyan]")
    console.print(f"Para consultar: python query_scanntech.py")
    console.print(f"Interface chat: http://localhost:3000")
    console.print(f"Dashboards:     http://localhost:3001")


if __name__ == "__main__":
    main()
