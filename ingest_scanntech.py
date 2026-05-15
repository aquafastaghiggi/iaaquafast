"""
==============================================================
 AQUAFAST — Ingestor Scanntech
 Suporta:
  1) Arquivo único já denormalizado: --arquivo
  2) Layout Scanntech mensal:
     --pdv      BR_VTA_MENSUAL_YYYYMM.txt (fato: vendas)
     --clientes BR_PDV_MENSUAL_YYYYMM.txt (dim: PDVs/lojas)
     --produtos BR_PRD_MENSUAL_YYYYMM.txt (dim: produtos)
==============================================================
"""

import argparse
import json
import os
import sys
from pathlib import Path

import duckdb
import pandas as pd
from rich.console import Console
from rich.table import Table

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console(legacy_windows=False)

DB_PATH = "aquafast_scanntech.duckdb"

COLUNAS_ESSENCIAIS = {
    "cliente": ["PDV_ID", "RAZAO_SOCIAL", "CLIENTE", "NOME_CLIENTE", "CNPJ"],
    "produto": ["PROD_ID", "COD_PRODUTO", "SKU", "PRODUTO", "DESC_PRODUTO"],
    "valor": ["GROSS_SELLOUT", "VALOR_TOTAL", "VALOR", "PRECO"],
    "data": ["MONTH_ID", "DATA_VENDA", "DATA", "DT_VENDA"],
}

CLIENTES_KEYS = [
    "PDV_ID", "CNPJ", "COD_CLI", "COD_CLIENTE", "ID_CLIENTE",
    "CLIENTE_ID", "CODIGO_CLIENTE", "CNPJ_CLIENTE"
]
CLIENTES_NAME_COLS = [
    "RAZAO_SOCIAL", "PDV_NAME", "RAZAO", "NOME_CLIENTE",
    "CLIENTE", "NOME_FANTASIA"
]

PRODUTOS_KEYS = [
    "PROD_ID", "COD_PRODUTO", "SKU", "CODIGO_PRODUTO",
    "ID_PRODUTO", "PRODUTO_ID", "COD_PROD"
]
PRODUTOS_NAME_COLS = [
    "PROD_NAME", "DESC_PRODUTO", "DESCRICAO", "DESCR",
    "PRODUTO", "NOME_PRODUTO"
]


def _safe_path(path: str) -> str:
    return path.replace("\\", "/")


def _upper_map(colunas: list[str]) -> dict[str, str]:
    return {str(c).upper().strip(): str(c) for c in colunas}


def _pick_column(colunas: list[str], candidates: list[str]) -> str | None:
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


def detectar_encoding(arquivo: str) -> str:
    try:
        import chardet

        with open(arquivo, "rb") as f:
            raw = f.read(100000)

        result = chardet.detect(raw)
        enc = result.get("encoding") or "utf-8"

        console.print(
            f"[green]✓[/green] Encoding detectado: "
            f"[bold]{enc}[/bold] "
            f"(confiança: {result.get('confidence', 0):.0%})"
        )
        return enc
    except Exception:
        return "utf-8"


def detectar_separador(arquivo: str, encoding: str) -> str:
    with open(arquivo, "r", encoding=encoding, errors="replace") as f:
        linha = f.readline()

    candidatos = [";", ",", "\t", "|"]
    separador = max(candidatos, key=lambda sep: linha.count(sep))

    console.print(f"[green]✓[/green] Separador detectado: [bold]{repr(separador)}[/bold]")
    return separador


def preview_arquivo_duckdb(
    arquivo: str,
    encoding: str,
    separador: str,
    n_linhas: int = 5,
) -> list[str]:
    con = duckdb.connect(":memory:")

    try:
        rel = con.execute(
            f"""
            SELECT *
            FROM read_csv_auto(
                '{_safe_path(arquivo)}',
                delim='{separador}',
                header=true,
                ignore_errors=true,
                sample_size=20000,
                encoding='{encoding}'
            )
            LIMIT {int(n_linhas)}
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


def preview_arquivo_pandas(
    arquivo: str,
    encoding: str,
    separador: str,
    n_linhas: int = 5,
) -> list[str]:
    console.print("\n[bold cyan]Preview do arquivo:[/bold cyan]")

    df_preview = pd.read_csv(
        arquivo,
        sep=separador,
        encoding=encoding,
        nrows=n_linhas,
        dtype=str,
        on_bad_lines="skip",
    )

    table = Table(show_header=True, header_style="bold blue")

    for col in df_preview.columns[:10]:
        table.add_column(str(col)[:20], overflow="fold")

    for _, row in df_preview.iterrows():
        table.add_row(*[str(v)[:20] for v in row.values[:10]])

    console.print(table)
    console.print(f"[dim]Colunas encontradas: {list(df_preview.columns)}[/dim]")

    return df_preview.columns.tolist()


def validar_colunas_essenciais(colunas: list[str]) -> None:
    colunas_upper = [str(c).upper() for c in colunas]
    faltando = []

    for nome, candidatos in COLUNAS_ESSENCIAIS.items():
        achou = any(
            any(candidato.upper() in coluna for coluna in colunas_upper)
            for candidato in candidatos
        )
        if not achou:
            faltando.append(nome)

    if faltando:
        raise ValueError(
            "Colunas essenciais ausentes ou nao identificadas: "
            + ", ".join(faltando)
            + ". Verifique cliente, produto, valor e data no CSV."
        )


def escolher_coluna_cliente(colunas: list[str]) -> str | None:
    prioridades = [
        "RAZAO_SOCIAL",
        "PDV_NAME",
        "CLIENTE",
        "NOME_CLIENTE",
        "NOME_FANTASIA",
        "CNPJ",
        "PDV_ID",
    ]
    return _pick_column(colunas, prioridades)


def importar_csv_duckdb(
    con: duckdb.DuckDBPyConnection,
    tabela: str,
    arquivo: str,
    encoding: str,
    separador: str,
) -> list[str]:
    console.print(f"[yellow]Importando {tabela}...[/yellow] {arquivo}")

    con.execute(
        f"""
        CREATE OR REPLACE TABLE "{tabela}" AS
        SELECT *
        FROM read_csv_auto(
            '{_safe_path(arquivo)}',
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


def importar_arquivo_unico(
    arquivo: str,
    db_path: str,
    preview_only: bool = False,
    assume_yes: bool = False,
):
    if not os.path.exists(arquivo):
        raise FileNotFoundError(f"Arquivo não encontrado: {arquivo}")

    tamanho_mb = os.path.getsize(arquivo) / 1024 / 1024

    console.print("\n[bold]🚀 Aquafast — Ingestor Scanntech[/bold]")
    console.print(f"Arquivo: [cyan]{arquivo}[/cyan] ({tamanho_mb:.1f} MB)")

    encoding = detectar_encoding(arquivo)
    separador = detectar_separador(arquivo, encoding)

    colunas = preview_arquivo_pandas(arquivo, encoding, separador)
    validar_colunas_essenciais(colunas)

    if preview_only:
        console.print("\n[yellow]Modo preview — importacao nao realizada.[/yellow]")
        return

    if not assume_yes:
        console.print(f"\n[bold yellow]Confirma importação de {tamanho_mb:.0f}MB para DuckDB?[/bold yellow]")
        resp = input("Digite 's' para continuar: ").strip().lower()

        if resp != "s":
            console.print("Cancelado.")
            return
    else:
        console.print("\n[dim]Confirmacao automatica (--yes).[/dim]")

    con = duckdb.connect(db_path)

    try:
        console.print(f"\n[bold]Importando para DuckDB:[/bold] {db_path}")

        con.execute(
            f"""
            CREATE OR REPLACE TABLE scanntech AS
            SELECT *
            FROM read_csv_auto(
                '{_safe_path(arquivo)}',
                delim='{separador}',
                header=true,
                ignore_errors=true,
                sample_size=-1,
                encoding='{encoding}'
            )
            """
        )

        total = con.execute("SELECT COUNT(*) FROM scanntech").fetchone()[0]
        console.print(f"[green]✓[/green] Importados: [bold]{total:,}[/bold] registros")

        normalizar_tabela_vta(con)

        colunas_final = [r[0] for r in con.execute("DESCRIBE scanntech").fetchall()]
        criar_views(con, colunas_final)
        relatorio_qualidade(con, total, colunas_final)
        exportar_views_csv(con)
        exportar_config_metabase(db_path)

    finally:
        con.close()

    console.print("\n[bold green]✅ Pronto![/bold green]")
    console.print(f"Banco salvo em: [cyan]{db_path}[/cyan]")


def normalizar_tabela_vta(con: duckdb.DuckDBPyConnection):
    cols = [r[0] for r in con.execute("DESCRIBE scanntech").fetchall()]
    cols_up = {c.upper(): c for c in cols}

    if not {"MONTH_ID", "PDV_ID", "PROD_ID", "SALES_UNITS", "GROSS_SELLOUT"}.issubset(cols_up):
        return

    console.print("[yellow]Normalizando layout Scanntech VTA...[/yellow]")

    con.execute(
        """
        CREATE OR REPLACE TABLE scanntech_norm AS
        SELECT
            MONTH_ID,
            PDV_ID AS CNPJ,
            CAST(PDV_ID AS VARCHAR) AS RAZAO_SOCIAL,
            PROD_ID AS COD_PRODUTO,
            PROD_ID AS DESC_PRODUTO,
            TRY_CAST(REPLACE(CAST(SALES_UNITS AS VARCHAR), ',', '.') AS DOUBLE) AS QTD,
            TRY_CAST(REPLACE(CAST(GROSS_SELLOUT AS VARCHAR), ',', '.') AS DOUBLE) AS VALOR_TOTAL,
            TRY_CAST(REPLACE(CAST(GROSS_SELLOUT AS VARCHAR), ',', '.') AS DOUBLE)
                / NULLIF(
                    TRY_CAST(REPLACE(CAST(SALES_UNITS AS VARCHAR), ',', '.') AS DOUBLE),
                    0
                ) AS VALOR_UNITARIO,
            STRPTIME(CAST(MONTH_ID AS VARCHAR), '%Y%m') AS DATA_VENDA
        FROM scanntech
        """
    )

    con.execute("DROP TABLE scanntech")
    con.execute("ALTER TABLE scanntech_norm RENAME TO scanntech")

    console.print("[green]✓[/green] Tabela scanntech normalizada")


def importar_3_arquivos_para_duckdb(
    vendas: str,
    clientes: str,
    produtos: str,
    db_path: str,
    preview_only: bool = False,
    assume_yes: bool = False,
):
    if not os.path.exists(vendas):
        raise FileNotFoundError(f"Arquivo vendas não encontrado: {vendas}")

    if not os.path.exists(clientes):
        raise FileNotFoundError(f"Arquivo clientes não encontrado: {clientes}")

    if not os.path.exists(produtos):
        raise FileNotFoundError(f"Arquivo produtos não encontrado: {produtos}")

    console.print("\n[bold]🚀 Aquafast — Ingestor Scanntech (3 arquivos)[/bold]")
    console.print(f"Vendas:   [cyan]{vendas}[/cyan]")
    console.print(f"Clientes: [cyan]{clientes}[/cyan]")
    console.print(f"Produtos: [cyan]{produtos}[/cyan]")

    enc_vendas = detectar_encoding(vendas)
    sep_vendas = detectar_separador(vendas, enc_vendas)

    enc_cli = detectar_encoding(clientes)
    sep_cli = detectar_separador(clientes, enc_cli)

    enc_prod = detectar_encoding(produtos)
    sep_prod = detectar_separador(produtos, enc_prod)

    cols_vendas = preview_arquivo_duckdb(vendas, enc_vendas, sep_vendas)
    cols_cli = preview_arquivo_duckdb(clientes, enc_cli, sep_cli)
    cols_prod = preview_arquivo_duckdb(produtos, enc_prod, sep_prod)

    _pick_required(cols_cli, "chave de cliente", CLIENTES_KEYS)
    _pick_required(cols_cli, "nome do cliente", CLIENTES_NAME_COLS)
    _pick_required(cols_prod, "chave de produto", PRODUTOS_KEYS)
    _pick_required(cols_prod, "nome do produto", PRODUTOS_NAME_COLS)

    _pick_required(cols_vendas, "chave de cliente/venda", CLIENTES_KEYS)
    _pick_required(cols_vendas, "chave de produto/venda", PRODUTOS_KEYS)
    _pick_required(cols_vendas, "quantidade", ["SALES_UNITS", "QTD", "QTDE", "QUANTIDADE"])
    _pick_required(cols_vendas, "valor total", ["GROSS_SELLOUT", "VALOR_TOTAL", "VALOR", "TOTAL"])
    _pick_required(cols_vendas, "data/periodo", ["MONTH_ID", "DATA_VENDA", "DATA", "DT_VENDA"])

    if preview_only:
        console.print("\n[yellow]Modo preview — importacao nao realizada.[/yellow]")
        return

    if not assume_yes:
        console.print("\n[bold yellow]Confirma importacao dos 3 arquivos para DuckDB?[/bold yellow]")
        resp = input("Digite 's' para continuar: ").strip().lower()

        if resp != "s":
            console.print("Cancelado.")
            return
    else:
        console.print("\n[dim]Confirmacao automatica (--yes).[/dim]")

    con = duckdb.connect(db_path)

    try:
        try:
            con.execute("PRAGMA threads=4")
        except Exception:
            pass

        cols_cli_real = importar_csv_duckdb(
            con, "scanntech_clientes_raw", clientes, enc_cli, sep_cli
        )
        cols_prod_real = importar_csv_duckdb(
            con, "scanntech_produtos_raw", produtos, enc_prod, sep_prod
        )
        cols_vendas_real = importar_csv_duckdb(
            con, "scanntech_vendas_raw", vendas, enc_vendas, sep_vendas
        )

        cli_key = _pick_required(cols_cli_real, "chave de cliente", CLIENTES_KEYS)
        cli_name = _pick_required(cols_cli_real, "nome do cliente", CLIENTES_NAME_COLS)

        prod_key = _pick_required(cols_prod_real, "chave de produto", PRODUTOS_KEYS)
        prod_name = _pick_required(cols_prod_real, "nome do produto", PRODUTOS_NAME_COLS)

        vendas_cli_key = _pick_required(cols_vendas_real, "cliente na venda", CLIENTES_KEYS)
        vendas_prod_key = _pick_required(cols_vendas_real, "produto na venda", PRODUTOS_KEYS)
        vendas_qtd = _pick_required(cols_vendas_real, "quantidade", ["SALES_UNITS", "QTD", "QTDE", "QUANTIDADE"])
        vendas_valor = _pick_required(cols_vendas_real, "valor total", ["GROSS_SELLOUT", "VALOR_TOTAL", "VALOR", "TOTAL"])
        vendas_data = _pick_required(cols_vendas_real, "data/periodo", ["MONTH_ID", "DATA_VENDA", "DATA", "DT_VENDA"])

        console.print("\n[bold]Mapeamento detectado:[/bold]")
        console.print(f"[dim]Clientes: key={cli_key} nome={cli_name}[/dim]")
        console.print(f"[dim]Produtos: key={prod_key} nome={prod_name}[/dim]")
        console.print(f"[dim]Vendas: cliente={vendas_cli_key} produto={vendas_prod_key} qtd={vendas_qtd} valor={vendas_valor} data={vendas_data}[/dim]")

        console.print("\n[yellow]Gerando tabela final scanntech...[/yellow]")

        data_expr = (
            f"STRPTIME(CAST(v.\"{vendas_data}\" AS VARCHAR), '%Y%m')"
            if vendas_data.upper() == "MONTH_ID"
            else f'TRY_CAST(v."{vendas_data}" AS DATE)'
        )

        con.execute(
            f"""
            CREATE OR REPLACE TABLE scanntech AS
            SELECT
                v."{vendas_data}" AS MONTH_ID,
                CAST(v."{vendas_cli_key}" AS VARCHAR) AS CNPJ,
                COALESCE(
                    NULLIF(TRIM(CAST(c."{cli_name}" AS VARCHAR)), ''),
                    CAST(v."{vendas_cli_key}" AS VARCHAR)
                ) AS RAZAO_SOCIAL,
                CAST(v."{vendas_prod_key}" AS VARCHAR) AS COD_PRODUTO,
                COALESCE(
                    NULLIF(TRIM(CAST(p."{prod_name}" AS VARCHAR)), ''),
                    CAST(v."{vendas_prod_key}" AS VARCHAR)
                ) AS DESC_PRODUTO,
                TRY_CAST(REPLACE(CAST(v."{vendas_qtd}" AS VARCHAR), ',', '.') AS DOUBLE) AS QTD,
                TRY_CAST(REPLACE(CAST(v."{vendas_valor}" AS VARCHAR), ',', '.') AS DOUBLE) AS VALOR_TOTAL,
                TRY_CAST(REPLACE(CAST(v."{vendas_valor}" AS VARCHAR), ',', '.') AS DOUBLE)
                    / NULLIF(
                        TRY_CAST(REPLACE(CAST(v."{vendas_qtd}" AS VARCHAR), ',', '.') AS DOUBLE),
                        0
                    ) AS VALOR_UNITARIO,
                {data_expr} AS DATA_VENDA
            FROM scanntech_vendas_raw v
            LEFT JOIN scanntech_clientes_raw c
                ON CAST(v."{vendas_cli_key}" AS VARCHAR) = CAST(c."{cli_key}" AS VARCHAR)
            LEFT JOIN scanntech_produtos_raw p
                ON CAST(v."{vendas_prod_key}" AS VARCHAR) = CAST(p."{prod_key}" AS VARCHAR)
            """
        )

        total = con.execute("SELECT COUNT(*) FROM scanntech").fetchone()[0]
        console.print(f"[green]✓[/green] scanntech: {total:,} linhas")

        colunas_final = [r[0] for r in con.execute("DESCRIBE scanntech").fetchall()]

        criar_views(con, colunas_final)
        relatorio_qualidade(con, total, colunas_final)
        exportar_views_csv(con)
        exportar_config_metabase(db_path)

    finally:
        con.close()

    console.print("\n[bold green]✅ Pronto![/bold green]")
    console.print(f"Banco salvo em: [cyan]{db_path}[/cyan]")


def criar_views(con: duckdb.DuckDBPyConnection, colunas: list[str]):
    console.print("\n[bold]Criando sumários para consultas rápidas...[/bold]")

    col_data = _pick_column(colunas, ["DATA_VENDA", "DATA", "MONTH_ID"])
    col_cliente = _pick_column(colunas, ["RAZAO_SOCIAL", "CLIENTE", "CNPJ"])
    col_valor = _pick_column(colunas, ["VALOR_TOTAL", "GROSS_SELLOUT", "VALOR"])
    col_produto = _pick_column(colunas, ["DESC_PRODUTO", "COD_PRODUTO", "PROD_ID"])
    col_qtd = _pick_column(colunas, ["QTD", "SALES_UNITS", "QUANTIDADE"])

    console.print(f"[dim]Coluna de data: {col_data}[/dim]")
    console.print(f"[dim]Coluna de cliente: {col_cliente}[/dim]")
    console.print(f"[dim]Coluna de valor: {col_valor}[/dim]")
    console.print(f"[dim]Coluna de produto: {col_produto}[/dim]")

    if col_cliente and col_valor:
        con.execute(
            f"""
            CREATE OR REPLACE VIEW ranking_clientes AS
            SELECT
                COALESCE(NULLIF(TRIM(CAST("{col_cliente}" AS VARCHAR)), ''), 'NAO_INFORMADO') AS cliente,
                COUNT(*) AS total_pedidos,
                ROUND(SUM(TRY_CAST("{col_valor}" AS DOUBLE)), 2) AS valor_total,
                ROUND(SUM(TRY_CAST("{col_valor}" AS DOUBLE)) / COUNT(*), 2) AS ticket_medio,
                MIN("{col_data}") AS primeira_compra,
                MAX("{col_data}") AS ultima_compra
            FROM scanntech
            GROUP BY 1
            ORDER BY valor_total DESC NULLS LAST
            """
        )
        console.print("[green]✓[/green] View ranking_clientes criada")

    if col_produto and col_valor:
        qtd_expr = f'SUM(TRY_CAST("{col_qtd}" AS DOUBLE))' if col_qtd else "COUNT(*)"

        con.execute(
            f"""
            CREATE OR REPLACE VIEW ranking_produtos AS
            SELECT
                COALESCE(NULLIF(TRIM(CAST("{col_produto}" AS VARCHAR)), ''), 'NAO_INFORMADO') AS produto,
                {qtd_expr} AS total_vendas,
                ROUND(SUM(TRY_CAST("{col_valor}" AS DOUBLE)), 2) AS receita_total
            FROM scanntech
            GROUP BY 1
            ORDER BY receita_total DESC NULLS LAST
            """
        )
        console.print("[green]✓[/green] View ranking_produtos criada")

    if col_data and col_valor:
        con.execute(
            f"""
            CREATE OR REPLACE VIEW vendas_por_mes AS
            SELECT
                SUBSTR(CAST("{col_data}" AS VARCHAR), 1, 7) AS mes,
                COUNT(*) AS total_pedidos,
                ROUND(SUM(TRY_CAST("{col_valor}" AS DOUBLE)), 2) AS receita
            FROM scanntech
            GROUP BY 1
            ORDER BY 1
            """
        )
        console.print("[green]✓[/green] View vendas_por_mes criada")


def relatorio_qualidade(
    con: duckdb.DuckDBPyConnection,
    total: int,
    colunas: list[str],
):
    console.print("\n[bold cyan]Relatório de qualidade:[/bold cyan]")

    table = Table(show_header=True, header_style="bold blue")
    table.add_column("Coluna")
    table.add_column("Nulos")
    table.add_column("Únicos (est.)")
    table.add_column("Exemplo")

    report_rows = []

    for col in colunas[:15]:
        try:
            stats = con.execute(
                f"""
                SELECT
                    COUNT(*) - COUNT("{col}") AS nulos,
                    APPROX_COUNT_DISTINCT("{col}") AS unicos,
                    MAX(CAST("{col}" AS VARCHAR)) AS exemplo
                FROM scanntech
                """
            ).fetchone()

            pct_nulo = f"{stats[0] / total * 100:.1f}%" if total else "0%"

            table.add_row(
                str(col)[:25],
                f"{stats[0]:,} ({pct_nulo})",
                f"{stats[1]:,}",
                str(stats[2] or "")[:30],
            )

            report_rows.append(
                {
                    "coluna": str(col),
                    "nulos": int(stats[0]),
                    "nulos_percentual": round(stats[0] / total * 100, 2) if total else 0,
                    "unicos_estimados": int(stats[1]) if stats[1] is not None else None,
                    "exemplo": str(stats[2] or ""),
                }
            )
        except Exception:
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

    console.print("[green]✓[/green] Relatorio de qualidade salvo em exports/data_quality_report.json")


def exportar_views_csv(con: duckdb.DuckDBPyConnection):
    os.makedirs("exports", exist_ok=True)

    for view in ["ranking_clientes", "ranking_produtos", "vendas_por_mes"]:
        try:
            con.execute(
                f"""
                COPY (
                    SELECT *
                    FROM {view}
                )
                TO 'exports/{view}.csv'
                (HEADER, DELIMITER ',')
                """
            )
            console.print(f"[green]✓[/green] Exportado: exports/{view}.csv")
        except Exception as e:
            console.print(f"[yellow]⚠ Não exportou {view}: {e}[/yellow]")


def exportar_config_metabase(db_path: str):
    config = f"""
# ============================================================
# INSTRUÇÃO: Conectar Metabase ao DuckDB
# ============================================================

DB_PATH={db_path}
VIEWS_DISPONIVEIS=ranking_clientes,ranking_produtos,vendas_por_mes

Arquivos exportados:
- exports/ranking_clientes.csv
- exports/ranking_produtos.csv
- exports/vendas_por_mes.csv
"""

    with open("METABASE_CONFIG.txt", "w", encoding="utf-8") as f:
        f.write(config)

    console.print("[green]✓[/green] Instruções Metabase salvas em METABASE_CONFIG.txt")


def main():
    parser = argparse.ArgumentParser(description="Ingestor Scanntech → DuckDB")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--arquivo", help="Arquivo único Scanntech já denormalizado")
    group.add_argument("--pdv", help="Arquivo de vendas/fato Scanntech, ex: BR_VTA_MENSUAL")

    parser.add_argument("--clientes", help="Arquivo de clientes/PDVs, ex: clientes_fake.csv")
    parser.add_argument("--produtos", help="Arquivo de produtos, ex: BR_PRD_MENSUAL")
    parser.add_argument("--db", default=DB_PATH, help=f"Caminho do banco DuckDB padrão: {DB_PATH}")
    parser.add_argument("--preview-only", action="store_true", help="Só mostra preview, não importa")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Nao pede confirmacao antes de gravar no DuckDB (para scripts/automacao)",
    )

    args = parser.parse_args()

    try:
        if args.pdv:
            if not args.clientes or not args.produtos:
                console.print("[red]Para usar --pdv, passe --clientes e --produtos.[/red]")
                sys.exit(1)

            importar_3_arquivos_para_duckdb(
                vendas=args.pdv,
                clientes=args.clientes,
                produtos=args.produtos,
                db_path=args.db,
                preview_only=args.preview_only,
                assume_yes=args.yes,
            )
            return

        importar_arquivo_unico(
            arquivo=args.arquivo,
            db_path=args.db,
            preview_only=args.preview_only,
            assume_yes=args.yes,
        )

    except Exception as e:
        console.print(f"[red]Erro: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()