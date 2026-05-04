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
import json
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

COLUNAS_ESSENCIAIS = {
    "cliente": ["RAZAO_SOCIAL", "CLIENTE", "NOME_CLIENTE", "CNPJ"],
    "produto": ["COD_PRODUTO", "SKU", "PRODUTO", "DESC_PRODUTO"],
    "valor": ["VALOR_TOTAL", "VALOR", "PRECO"],
    "data": ["DATA_VENDA", "DATA", "DT_VENDA"],
}

# ----------------------------------------------------------
#  MODO 3 ARQUIVOS (PDV + dimensoes)
# ----------------------------------------------------------
CLIENTES_KEYS = ["CNPJ", "COD_CLI", "COD_CLIENTE", "ID_CLIENTE", "CLIENTE_ID", "CODIGO_CLIENTE", "CNPJ_CLIENTE"]
CLIENTES_NAME_COLS = ["RAZAO_SOCIAL", "RAZAO", "NOME_CLIENTE", "CLIENTE", "NOME_FANTASIA"]
PRODUTOS_KEYS = ["COD_PRODUTO", "SKU", "CODIGO_PRODUTO", "ID_PRODUTO", "PRODUTO_ID", "COD_PROD"]
PRODUTOS_NAME_COLS = ["DESC_PRODUTO", "DESCRICAO", "DESCR", "PRODUTO", "NOME_PRODUTO"]


def _upper_map(colunas: list[str]) -> dict[str, str]:
    return {str(c).upper().strip(): str(c) for c in colunas}


def _pick_column(colunas: list[str], candidates: list[str]) -> str | None:
    """Encontra uma coluna por substring (case-insensitive)."""
    upper = _upper_map(colunas)
    for cand in candidates:
        cand_up = cand.upper()
        for key, original in upper.items():
            if cand_up == key or cand_up in key:
                return original
    return None


def _pick_required(colunas: list[str], label: str, candidates: list[str]) -> str:
    col = _pick_column(colunas, candidates)
    if not col:
        raise ValueError(
            f"Nao encontrei coluna obrigatoria ({label}). "
            f"Candidatos: {candidates}. Colunas: {colunas}"
        )
    return col


def _safe_relpath(path: str) -> str:
    return path.replace(chr(92), "/")


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
    Prioriza a razão social para exibição legível.
    """
    prioridades = [
        "RAZAO_SOCIAL",
        "RAZAO",
        "CLIENTE",
        "NOME_CLIENTE",
        "NOME_FANTASIA",
        "COD_CLI",
        "CNPJ",
    ]

    colunas_upper = {c.upper(): c for c in colunas}

    for chave in prioridades:
        for coluna_upper, coluna_original in colunas_upper.items():
            if chave in coluna_upper:
                return coluna_original

    return None


def validar_colunas_essenciais(colunas: list) -> None:
    """Garante que o arquivo tem o minimo necessario para analise."""
    colunas_upper = [str(col).upper() for col in colunas]
    faltando = []

    for nome, candidatos in COLUNAS_ESSENCIAIS.items():
        if not any(any(candidato in coluna for coluna in colunas_upper) for candidato in candidatos):
            faltando.append(nome)

    if faltando:
        raise ValueError(
            "Colunas essenciais ausentes ou nao identificadas: "
            + ", ".join(faltando)
            + ". Verifique cliente, produto, valor e data no CSV."
        )


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


def preview_arquivo_duckdb(arquivo: str, encoding: str, separador: str, n_linhas: int = 5) -> list[str]:
    """Preview usando DuckDB (evita pandas e funciona bem em arquivos grandes)."""
    con = duckdb.connect(":memory:")
    try:
        rel = con.execute(
            f"""
            SELECT * FROM read_csv_auto(
                '{_safe_relpath(arquivo)}',
                delim='{separador}',
                header=true,
                ignore_errors=true,
                sample_size=20000,
                encoding='{encoding}'
            ) LIMIT {int(n_linhas)}
            """
        )
        cols = [d[0] for d in rel.description]
        rows = rel.fetchall()
    finally:
        con.close()

    console.print("\n[bold cyan]Preview do arquivo:[/bold cyan]")
    table = Table(show_header=True, header_style="bold blue")
    for col in cols[:10]:
        table.add_column(str(col)[:20], overflow="fold")
    for row in rows:
        table.add_row(*[str(v)[:20] for v in row[:10]])
    console.print(table)
    console.print(f"[dim]Colunas encontradas: {cols}[/dim]")
    return cols


def importar_csv_duckdb(
    con: duckdb.DuckDBPyConnection,
    tabela: str,
    arquivo: str,
    encoding: str,
    separador: str,
) -> list[str]:
    """Importa um CSV grande diretamente via DuckDB em streaming e retorna as colunas detectadas."""
    console.print(f"[yellow]Importando {tabela}...[/yellow] {arquivo}")
    con.execute(
        f"""
        CREATE OR REPLACE TABLE "{tabela}" AS
        SELECT * FROM read_csv_auto(
            '{_safe_relpath(arquivo)}',
            delim='{separador}',
            header=true,
            ignore_errors=true,
            sample_size=-1,
            encoding='{encoding}'
        )
        """
    )
    cols = [r[0] for r in con.execute(f'DESCRIBE "{tabela}"').fetchall()]
    total = con.execute(f'SELECT COUNT(*) FROM "{tabela}"').fetchone()[0]
    console.print(f"[green]✓[/green] {tabela}: {total:,} linhas")
    return cols


def importar_3_arquivos_para_duckdb(
    pdv: str,
    clientes: str,
    produtos: str,
    db_path: str,
    preview_only: bool = False,
):
    """
    Importa 3 arquivos (PDV + dimensoes clientes e produtos) e gera a tabela final `scanntech`
    no formato esperado pela stack.
    """
    if not os.path.exists(pdv):
        raise FileNotFoundError(f"Arquivo PDV nao encontrado: {pdv}")
    if not os.path.exists(clientes):
        raise FileNotFoundError(f"Arquivo clientes nao encontrado: {clientes}")
    if not os.path.exists(produtos):
        raise FileNotFoundError(f"Arquivo produtos nao encontrado: {produtos}")

    console.print("\n[bold]🚀 Aquafast — Ingestor Scanntech (3 arquivos)[/bold]")
    console.print(f"PDV:      [cyan]{pdv}[/cyan]")
    console.print(f"Clientes: [cyan]{clientes}[/cyan]")
    console.print(f"Produtos: [cyan]{produtos}[/cyan]")

    enc_pdv = detectar_encoding(pdv)
    sep_pdv = detectar_separador(pdv, enc_pdv)
    enc_cli = detectar_encoding(clientes)
    sep_cli = detectar_separador(clientes, enc_cli)
    enc_pro = detectar_encoding(produtos)
    sep_pro = detectar_separador(produtos, enc_pro)

    cols_pdv = preview_arquivo_duckdb(pdv, enc_pdv, sep_pdv)
    cols_cli = preview_arquivo_duckdb(clientes, enc_cli, sep_cli)
    cols_pro = preview_arquivo_duckdb(produtos, enc_pro, sep_pro)

    # valida o minimo das dimensoes
    _pick_required(cols_cli, "chave de cliente (clientes)", CLIENTES_KEYS)
    _pick_required(cols_cli, "nome do cliente (clientes)", CLIENTES_NAME_COLS)
    _pick_required(cols_pro, "chave de produto (produtos)", PRODUTOS_KEYS)
    _pick_required(cols_pro, "nome do produto (produtos)", PRODUTOS_NAME_COLS)

    if preview_only:
        console.print("\n[yellow]Modo preview — importacao nao realizada.[/yellow]")
        return None

    console.print("\n[bold yellow]Confirma importacao dos 3 arquivos para DuckDB?[/bold yellow]")
    resp = input("Digite 's' para continuar: ").strip().lower()
    if resp != "s":
        console.print("Cancelado.")
        return None

    con = duckdb.connect(db_path)
    try:
        try:
            con.execute("PRAGMA threads=4")
        except Exception:
            pass

        cols_cli_real = importar_csv_duckdb(con, "scanntech_clientes_raw", clientes, enc_cli, sep_cli)
        cols_pro_real = importar_csv_duckdb(con, "scanntech_produtos_raw", produtos, enc_pro, sep_pro)
        cols_pdv_real = importar_csv_duckdb(con, "scanntech_pdv_raw", pdv, enc_pdv, sep_pdv)

        cli_key = _pick_required(cols_cli_real, "chave de cliente (clientes)", CLIENTES_KEYS)
        cli_name = _pick_required(cols_cli_real, "nome do cliente (clientes)", CLIENTES_NAME_COLS)
        pro_key = _pick_required(cols_pro_real, "chave de produto (produtos)", PRODUTOS_KEYS)
        pro_name = _pick_required(cols_pro_real, "nome do produto (produtos)", PRODUTOS_NAME_COLS)

        pdv_cli_key = _pick_required(cols_pdv_real, "chave de cliente (pdv)", CLIENTES_KEYS)
        pdv_pro_key = _pick_required(cols_pdv_real, "chave de produto (pdv)", PRODUTOS_KEYS)

        pdv_qtd = _pick_required(cols_pdv_real, "quantidade (pdv)", ["QTD", "QTDE", "QUANTIDADE", "QTD_ITEM", "QTD_VENDA"])
        pdv_valor_total = _pick_required(cols_pdv_real, "valor total (pdv)", ["VALOR_TOTAL", "VALOR", "TOTAL", "VL_TOTAL", "VLR_TOTAL"])
        pdv_valor_unit = _pick_column(cols_pdv_real, ["VALOR_UNITARIO", "VL_UNIT", "VLR_UNIT", "PRECO_UNIT", "PRECO_UNITARIO"])
        pdv_data = _pick_required(cols_pdv_real, "data (pdv)", ["DATA_VENDA", "DATA", "DT_VENDA", "DATA_EMISSAO", "DT_EMISSAO"])
        pdv_uf = _pick_column(cols_pdv_real, ["UF", "ESTADO"])
        pdv_cidade = _pick_column(cols_pdv_real, ["CIDADE", "MUNICIPIO", "MUNICÍPIO"])
        pdv_canal = _pick_column(cols_pdv_real, ["CANAL", "TIPO_CANAL", "SEGMENTO"])

        console.print("\n[bold]Mapeamento detectado:[/bold]")
        console.print(f"[dim]Clientes: key={cli_key} nome={cli_name}[/dim]")
        console.print(f"[dim]Produtos: key={pro_key} nome={pro_name}[/dim]")
        console.print(f"[dim]PDV: cli_key={pdv_cli_key} pro_key={pdv_pro_key}[/dim]")

        select_cols = [
            f'CAST(p."{pdv_cli_key}" AS BIGINT) AS CNPJ',
            f'CAST(c."{cli_name}" AS VARCHAR) AS RAZAO_SOCIAL',
            f'CAST(p."{pdv_pro_key}" AS VARCHAR) AS COD_PRODUTO',
            f'CAST(pr."{pro_name}" AS VARCHAR) AS DESC_PRODUTO',
            f'CAST(p."{pdv_qtd}" AS BIGINT) AS QTD',
        ]
        if pdv_valor_unit:
            select_cols.append(f'CAST(p."{pdv_valor_unit}" AS DOUBLE) AS VALOR_UNITARIO')
        else:
            select_cols.append("NULL::DOUBLE AS VALOR_UNITARIO")
        select_cols.append(f'CAST(p."{pdv_valor_total}" AS DOUBLE) AS VALOR_TOTAL')
        select_cols.append(f'CAST(p."{pdv_data}" AS DATE) AS DATA_VENDA')
        if pdv_uf:
            select_cols.append(f'CAST(p."{pdv_uf}" AS VARCHAR) AS UF')
        else:
            select_cols.append("NULL::VARCHAR AS UF")
        if pdv_cidade:
            select_cols.append(f'CAST(p."{pdv_cidade}" AS VARCHAR) AS CIDADE')
        else:
            select_cols.append("NULL::VARCHAR AS CIDADE")
        if pdv_canal:
            select_cols.append(f'CAST(p."{pdv_canal}" AS VARCHAR) AS CANAL')
        else:
            select_cols.append("NULL::VARCHAR AS CANAL")

        console.print("\n[yellow]Gerando tabela final scanntech (join PDV + dimensoes)...[/yellow]")
        con.execute(
            f"""
            CREATE OR REPLACE TABLE scanntech AS
            SELECT
                {",\n                ".join(select_cols)}
            FROM scanntech_pdv_raw p
            LEFT JOIN scanntech_clientes_raw c
                ON CAST(p."{pdv_cli_key}" AS VARCHAR) = CAST(c."{cli_key}" AS VARCHAR)
            LEFT JOIN scanntech_produtos_raw pr
                ON CAST(p."{pdv_pro_key}" AS VARCHAR) = CAST(pr."{pro_key}" AS VARCHAR)
            """
        )

        total_final = con.execute("SELECT COUNT(*) FROM scanntech").fetchone()[0]
        console.print(f"[green]✓[/green] scanntech: {total_final:,} linhas")

        colunas_final = [r[0] for r in con.execute("DESCRIBE scanntech").fetchall()]
        criar_indices(con, colunas_final)
        relatorio_qualidade(con, total_final, colunas_final)
        exportar_views_csv(con)
        exportar_config_metabase(db_path)
    finally:
        con.close()
    return True


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
    
    # Prioriza VALOR_TOTAL > VALOR_LIQUIDO > VALOR_UNITARIO > TOTAL
    col_valor = None
    for prioridade in ["valor_total", "valor_liquido", "total", "valor", "vl_total", "vl_", "_vl", "preco"]:
        col_valor = next((c for c in colunas if prioridade in c.lower()), None)
        if col_valor:
            break
    if not col_valor:
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
                    COALESCE(NULLIF(TRIM(CAST("{col_cliente}" AS VARCHAR)), ''), 'NAO_INFORMADO') as cliente,
                    COUNT(*) as total_pedidos,
                    ROUND(SUM(TRY_CAST("{col_valor}" AS DOUBLE)), 2) as valor_total,
                    ROUND(SUM(TRY_CAST("{col_valor}" AS DOUBLE)) / COUNT(*), 2) as ticket_medio,
                    MIN("{col_data}") as primeira_compra,
                    MAX("{col_data}") as ultima_compra
                FROM scanntech
                GROUP BY COALESCE(NULLIF(TRIM(CAST("{col_cliente}" AS VARCHAR)), ''), 'NAO_INFORMADO')
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
                    COALESCE(NULLIF(TRIM(CAST("{col_produto}" AS VARCHAR)), ''), 'NAO_INFORMADO') as produto,
                    COUNT(*) as total_vendas,
                    ROUND(SUM(TRY_CAST("{col_valor}" AS DOUBLE)), 2) as receita_total
                FROM scanntech
                GROUP BY COALESCE(NULLIF(TRIM(CAST("{col_produto}" AS VARCHAR)), ''), 'NAO_INFORMADO')
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
    report_rows = []
    
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
            report_rows.append(
                {
                    "coluna": str(col),
                    "nulos": int(stats[0]),
                    "nulos_percentual": round(stats[0] / total * 100, 2) if total > 0 else 0,
                    "unicos_estimados": int(stats[1]) if stats[1] is not None else None,
                    "exemplo": str(stats[2] or ""),
                }
            )
            table.add_row(
                str(col)[:25],
                f"{stats[0]:,} ({pct_nulo})",
                f"{stats[1]:,}",
                str(stats[2] or "")[:30]
            )
        except Exception:
            report_rows.append(
                {
                    "coluna": str(col),
                    "nulos": None,
                    "nulos_percentual": None,
                    "unicos_estimados": None,
                    "exemplo": None,
                }
            )
            table.add_row(str(col)[:25], "?", "?", "?")
    
    console.print(table)
    os.makedirs("exports", exist_ok=True)
    with open("exports/data_quality_report.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "total_registros": total,
                "colunas_analisadas": report_rows,
            },
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    console.print("[green]✓[/green] Relatorio de qualidade salvo em [bold]exports/data_quality_report.json[/bold]")


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
#   Use a API FastAPI em http://localhost:8001
#   Endpoints úteis:
#     /reports
#     /reports/ranking_clientes?page=1&page_size=50
#     /reports/ranking_produtos?page=1&page_size=50
#     /reports/vendas_por_mes?page=1&page_size=50
#   Esses endpoints retornam JSON paginado e podem ser usados
#   por ferramentas externas ou conectores HTTP/JSON compatíveis.
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
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--arquivo", help="Caminho para o CSV/TXT unico da Scanntech (ja denormalizado)")
    group.add_argument("--pdv", help="Caminho para o arquivo de vendas PDV (fato)")
    parser.add_argument("--clientes", help="Caminho para o arquivo de clientes (dimensao)")
    parser.add_argument("--produtos", help="Caminho para o arquivo de produtos (dimensao)")
    parser.add_argument("--db", default=DB_PATH, help=f"Caminho do banco DuckDB (padrão: {DB_PATH})")
    parser.add_argument("--preview-only", action="store_true", help="Só mostra preview, não importa")
    args = parser.parse_args()

    # Modo 3 arquivos
    if args.pdv:
        if not args.clientes or not args.produtos:
            console.print("[red]Para usar --pdv, voce precisa passar --clientes e --produtos.[/red]")
            sys.exit(1)
        try:
            importar_3_arquivos_para_duckdb(
                args.pdv,
                args.clientes,
                args.produtos,
                args.db,
                preview_only=args.preview_only,
            )
        except Exception as e:
            console.print(f"[red]Erro: {e}[/red]")
            sys.exit(1)
        return
    
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
    validar_colunas_essenciais(colunas)
    
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
