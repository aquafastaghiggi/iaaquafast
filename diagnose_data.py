"""
Aquafast — Diagnóstico de Integridade de Dados

Valida a qualidade e integridade dos dados no banco DuckDB.
Identifica dados inventados, nulos, duplicados e inconsistências.
"""

import duckdb
import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint
from datetime import datetime

console = Console()
DB_PATH = Path("aquafast_scanntech.duckdb")


def check_database_exists():
    """Verifica se o banco existe."""
    if not DB_PATH.exists():
        console.print(f"[red]✗ Banco de dados não encontrado: {DB_PATH}[/red]")
        console.print("\nPrimeiro execute:")
        console.print("  python ingest_scanntech.py --arquivo caminho/para/scanntech.csv")
        return False
    return True


def run_diagnostic():
    """Executa diagnóstico completo."""
    if not check_database_exists():
        return
    
    con = duckdb.connect(str(DB_PATH), read_only=True)
    
    try:
        console.print("\n[bold cyan]🔍 DIAGNÓSTICO DE INTEGRIDADE DE DADOS[/bold cyan]\n")
        
        # 1. Verificar tabela principal
        console.print("[bold]1. Tabela Principal (scanntech)[/bold]")
        check_table_scanntech(con)
        
        # 2. Verificar views
        console.print("\n[bold]2. Views de Aggregação[/bold]")
        check_views(con)
        
        # 3. Verificar integridade de dados
        console.print("\n[bold]3. Integridade de Dados[/bold]")
        check_data_integrity(con)
        
        # 4. Verificar conversões de tipo
        console.print("\n[bold]4. Análise de Conversões de Tipo[/bold]")
        check_type_conversions(con)
        
    finally:
        con.close()


def check_table_scanntech(con: duckdb.DuckDBPyConnection):
    """Analisa a tabela principal."""
    try:
        # Contar registros
        total = con.execute("SELECT COUNT(*) FROM scanntech").fetchone()[0]
        console.print(f"  Total de registros: {total:,}")
        
        # Schema
        schema = con.execute("DESCRIBE scanntech").fetchdf()
        console.print(f"\n  Colunas encontradas: {len(schema)}")
        
        table = Table(show_header=True, header_style="bold blue")
        table.add_column("Coluna")
        table.add_column("Tipo")
        for _, row in schema.iterrows():
            table.add_column(str(row["column_name"]), str(row["column_type"]))
        
        # Mostra apenas primeiras 10 colunas
        for _, row in schema.head(10).iterrows():
            table.add_row(str(row["column_name"]), str(row["column_type"]))
        
        console.print(table)
        
        if len(schema) > 10:
            console.print(f"  [dim]... e mais {len(schema) - 10} colunas[/dim]")
            
    except Exception as e:
        console.print(f"[red]✗ Erro ao verificar tabela scanntech: {e}[/red]")


def check_views(con: duckdb.DuckDBPyConnection):
    """Verifica integridade das views."""
    views = ["ranking_clientes", "ranking_produtos", "vendas_por_mes"]
    
    for view in views:
        console.print(f"\n  📊 {view}")
        try:
            total = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
            console.print(f"     Registros: {total:,}")
            
            # Mostra sample
            sample = con.execute(f"SELECT * FROM {view} LIMIT 3").fetchdf()
            if sample.empty:
                console.print(f"     [yellow]⚠ Nenhum dado retornado![/yellow]")
            else:
                console.print(f"     Primeiros registros:")
                for idx, row in sample.iterrows():
                    console.print(f"       {dict(row)}")
                    
        except Exception as e:
            console.print(f"     [red]✗ Erro: {e}[/red]")


def check_data_integrity(con: duckdb.DuckDBPyConnection):
    """Verifica integridade geral dos dados."""
    console.print("\n  Checando valores nulos e vazios...")
    
    try:
        # Detecta automaticamente colunas de cliente, valor e data
        cols = con.execute("DESCRIBE scanntech").fetchdf()["column_name"].tolist()
        
        col_cliente = next((c for c in cols if any(k in c.lower() for k in ["cliente", "razao", "cnpj", "nome"])), None)
        col_valor = next((c for c in cols if any(k in c.lower() for k in ["valor", "total", "vl_", "preco"])), None)
        col_data = next((c for c in cols if any(k in c.lower() for k in ["data", "dt_", "date"])), None)
        
        if col_cliente:
            check_column_quality(con, col_cliente, "Cliente")
        if col_valor:
            check_column_quality(con, col_valor, "Valor", check_numeric=True)
        if col_data:
            check_column_quality(con, col_data, "Data", check_numeric=False)
            
    except Exception as e:
        console.print(f"[red]✗ Erro na análise: {e}[/red]")


def check_column_quality(con: duckdb.DuckDBPyConnection, col: str, label: str, check_numeric: bool = False):
    """Analisa qualidade de uma coluna específica."""
    try:
        total = con.execute("SELECT COUNT(*) FROM scanntech").fetchone()[0]
        
        stats = con.execute(f"""
            SELECT
                COUNT(*) as total,
                COUNT("{col}") as nao_nulos,
                COUNT(DISTINCT CAST("{col}" AS VARCHAR)) as valores_unicos,
                CASE WHEN SUM(CASE WHEN TRIM(CAST("{col}" AS VARCHAR)) = '' THEN 1 ELSE 0 END) > 0 
                     THEN SUM(CASE WHEN TRIM(CAST("{col}" AS VARCHAR)) = '' THEN 1 ELSE 0 END) 
                     ELSE 0 
                END as vazios,
                MIN(CAST("{col}" AS VARCHAR)) as min_valor,
                MAX(CAST("{col}" AS VARCHAR)) as max_valor
            FROM scanntech
        """).fetchone()
        
        nulos = total - stats[1]
        vazios = stats[4] or 0
        
        console.print(f"\n    [{label}]")
        console.print(f"      Total: {stats[0]:,} | Preenchidos: {stats[1]:,} | Nulos: {nulos} | Vazios: {vazios}")
        console.print(f"      Valores únicos: {stats[2]:,}")
        
        if nulos > total * 0.1:
            console.print(f"      [yellow]⚠️ Atenção: {nulos/total*100:.1f}% de valores nulos![/yellow]")
        
        if check_numeric and stats[1] > 0:
            # Verifica se consegue converter para número
            numeric_stats = con.execute(f"""
                SELECT
                    COUNT(*) as total_convertidos,
                    SUM(CASE WHEN TRY_CAST("{col}" AS DOUBLE) IS NULL THEN 1 ELSE 0 END) as falhas_conversao
                FROM scanntech
                WHERE "{col}" IS NOT NULL
            """).fetchone()
            
            if numeric_stats[1] > 0:
                console.print(f"      [yellow]⚠️ {numeric_stats[1]} valores NÃO conseguem converter para número![/yellow]")
                # Mostra exemplos de valores que não convertem
                bad_values = con.execute(f"""
                    SELECT DISTINCT CAST("{col}" AS VARCHAR) as valor
                    FROM scanntech
                    WHERE TRY_CAST("{col}" AS DOUBLE) IS NULL AND "{col}" IS NOT NULL
                    LIMIT 5
                """).fetchall()
                console.print(f"      Exemplos de valores inválidos: {[row[0] for row in bad_values]}")
                
    except Exception as e:
        console.print(f"    [red]✗ Erro: {e}[/red]")


def check_type_conversions(con: duckdb.DuckDBPyConnection):
    """Verifica problemas em conversões de tipo nas views."""
    console.print("\n  Verificando TRY_CAST nas views...")
    
    try:
        cols = con.execute("DESCRIBE scanntech").fetchdf()["column_name"].tolist()
        
        col_cliente = next((c for c in cols if any(k in c.lower() for k in ["cliente", "razao", "cnpj", "nome"])), None)
        col_valor = next((c for c in cols if any(k in c.lower() for k in ["valor", "total", "vl_", "preco"])), None)
        col_data = next((c for c in cols if any(k in c.lower() for k in ["data", "dt_", "date"])), None)
        
        if col_valor:
            console.print(f"\n    Analisando coluna de valor: {col_valor}")
            total = con.execute("SELECT COUNT(*) FROM scanntech").fetchone()[0]
            
            null_conversions = con.execute(f"""
                SELECT COUNT(*)
                FROM scanntech
                WHERE TRY_CAST("{col_valor}" AS DOUBLE) IS NULL 
                AND "{col_valor}" IS NOT NULL
                AND TRIM(CAST("{col_valor}" AS VARCHAR)) != ''
            """).fetchone()[0]
            
            if null_conversions > 0:
                pct = null_conversions / total * 100
                console.print(f"      [red]✗ {null_conversions} ({pct:.2f}%) conversões FALHANDO silenciosamente![/red]")
                
                # Mostra exemplos
                bad = con.execute(f"""
                    SELECT DISTINCT CAST("{col_valor}" AS VARCHAR) 
                    FROM scanntech
                    WHERE TRY_CAST("{col_valor}" AS DOUBLE) IS NULL 
                    AND "{col_valor}" IS NOT NULL
                    LIMIT 10
                """).fetchall()
                console.print(f"      Exemplos: {[row[0] for row in bad]}")
            else:
                console.print(f"      [green]✓ Todas as conversões de valor funcionaram[/green]")
                
    except Exception as e:
        console.print(f"[red]✗ Erro na análise de conversão: {e}[/red]")


def diagnose_empty_results():
    """Verifica se views estão retornando vazio."""
    console.print("\n[bold]5. Diagnóstico de Resultados Vazios[/bold]\n")
    
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        views = ["ranking_clientes", "ranking_produtos", "vendas_por_mes"]
        
        for view in views:
            try:
                count = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
                if count == 0:
                    console.print(f"  [red]✗ {view}: VAZIO![/red]")
                    
                    # Tenta descobrir por quê
                    if view == "ranking_clientes":
                        check_why_empty_clients(con)
                else:
                    console.print(f"  [green]✓ {view}: {count:,} registros[/green]")
                    
            except Exception as e:
                console.print(f"  [red]✗ {view}: Erro ao contar - {e}[/red]")
                
    finally:
        con.close()


def check_why_empty_clients(con: duckdb.DuckDBPyConnection):
    """Investiga por que ranking_clientes pode estar vazio."""
    console.print("\n    Investigando...")
    
    try:
        # Verifica se a tabela original tem dados
        total = con.execute("SELECT COUNT(*) FROM scanntech").fetchone()[0]
        console.print(f"    Tabela scanntech tem {total} registros")
        
        # Tenta executar o query manualmente
        test = con.execute("""
            SELECT COUNT(*)
            FROM scanntech
            GROUP BY 'cliente'
        """).fetchone()[0]
        
        console.print(f"    Tentativa de groupby retornou {test} linhas")
        
    except Exception as e:
        console.print(f"    Erro: {e}")


if __name__ == "__main__":
    run_diagnostic()
    diagnose_empty_results()
    
    console.print("\n[bold cyan]📋 Diagnóstico Concluído[/bold cyan]\n")
