"""
Aquafast — Diagnóstico Detalhado de Queries

Examina as queries das views e identifica problemas de cálculo.
"""

import duckdb
from pathlib import Path
from rich.console import Console
from rich.table import Table

console = Console()
DB_PATH = Path("aquafast_scanntech.duckdb")


def main():
    if not DB_PATH.exists():
        console.print(f"[red]Banco não encontrado: {DB_PATH}[/red]")
        return
    
    con = duckdb.connect(str(DB_PATH), read_only=True)
    
    try:
        console.print("\n[bold cyan]📊 ANÁLISE DETALHADA DE DADOS[/bold cyan]\n")
        
        # 1. Examine a tabela de origem
        console.print("[bold]1. Tabela Original (scanntech)[/bold]\n")
        print_sample_data(con)
        
        # 2. Examine as views
        console.print("\n[bold]2. Views de Agregação[/bold]\n")
        print_view_data(con, "ranking_clientes")
        print_view_data(con, "ranking_produtos")
        print_view_data(con, "vendas_por_mes")
        
        # 3. Verifique cálculos
        console.print("\n[bold]3. Validação de Cálculos[/bold]\n")
        validate_calculations(con)
        
    finally:
        con.close()


def print_sample_data(con: duckdb.DuckDBPyConnection):
    """Mostra dados da tabela original."""
    df = con.execute("SELECT * FROM scanntech LIMIT 10").fetchdf()
    
    console.print(f"Total de colunas: {len(df.columns)}")
    console.print(f"Primeiras 10 linhas:\n")
    
    # Mostrar resumido
    for idx, row in df.iterrows():
        console.print(f"[dim]Linha {idx + 1}:[/dim]")
        for col, val in row.items():
            console.print(f"  {col}: {val}")
        console.print()


def print_view_data(con: duckdb.DuckDBPyConnection, view_name: str):
    """Mostra os dados de uma view."""
    try:
        df = con.execute(f"SELECT * FROM {view_name}").fetchdf()
        console.print(f"[cyan]{view_name}[/cyan]: {len(df)} registros")
        
        table = Table(show_header=True, header_style="bold blue")
        for col in df.columns:
            table.add_column(str(col)[:20])
        
        for _, row in df.iterrows():
            table.add_row(*[str(v)[:20] for v in row.values])
        
        console.print(table)
        console.print()
        
    except Exception as e:
        console.print(f"[red]Erro ao ler {view_name}: {e}[/red]\n")


def validate_calculations(con: duckdb.DuckDBPyConnection):
    """Valida se os cálculos das views estão corretos."""
    
    # Verifica coluna de valor usada
    console.print("Verificando coluna de VALOR usada...\n")
    
    schema = con.execute("DESCRIBE scanntech").fetchdf()
    cols = schema["column_name"].tolist()
    
    console.print("Colunas disponíveis que parecem ser valores:")
    for col in cols:
        if any(k in col.lower() for k in ["valor", "valor_", "vl_", "preco", "total"]):
            console.print(f"  - {col}")
    
    # Tenta reconhecer qual é usada
    console.print("\nTentando detectar coluna de valor usada na view ranking_clientes...")
    
    # Vamos examinar o que está sendo somado
    print("\nAnalisando dados base para verificação:\n")
    
    # Coleta dados de um cliente específico
    sample = con.execute("""
        SELECT * FROM scanntech
        LIMIT 3
    """).fetchdf()
    
    console.print("Primeiro registro (para análise):")
    for col, val in sample.iloc[0].items():
        console.print(f"  {col}: {val}")
    
    console.print("\nVerificando agregação manual de um cliente:")
    # Pega um cliente para verificar
    first_client = con.execute("""
        SELECT DISTINCT COALESCE(NULLIF(TRIM(CAST("RAZAO_SOCIAL" AS VARCHAR)), ''), 'NAO_INFORMADO') as cliente
        FROM scanntech
        LIMIT 1
    """).fetchone()[0]
    
    console.print(f"Verificando cliente: {first_client}\n")
    
    # Mostra registros deste cliente
    registros = con.execute(f"""
        SELECT "RAZAO_SOCIAL", "VALOR_TOTAL", "VALOR_UNITARIO", "DATA_VENDA"
        FROM scanntech
        WHERE COALESCE(NULLIF(TRIM(CAST("RAZAO_SOCIAL" AS VARCHAR)), ''), 'NAO_INFORMADO') = ?
        ORDER BY "DATA_VENDA"
    """, [first_client]).fetchdf()
    
    console.print(f"Registros do cliente (total: {len(registros)}):")
    table = Table(show_header=True, header_style="bold blue")
    table.add_column("RAZAO_SOCIAL")
    table.add_column("VALOR_TOTAL")
    table.add_column("VALOR_UNITARIO")
    table.add_column("DATA_VENDA")
    
    total_valor_total = 0
    total_valor_unitario = 0
    
    for _, row in registros.iterrows():
        table.add_row(
            str(row["RAZAO_SOCIAL"])[:20],
            str(row["VALOR_TOTAL"]),
            str(row["VALOR_UNITARIO"]),
            str(row["DATA_VENDA"])[:10]
        )
        try:
            total_valor_total += float(row["VALOR_TOTAL"]) if row["VALOR_TOTAL"] else 0
            total_valor_unitario += float(row["VALOR_UNITARIO"]) if row["VALOR_UNITARIO"] else 0
        except:
            pass
    
    console.print(table)
    
    console.print(f"\nSomas esperadas:")
    console.print(f"  VALOR_TOTAL: {total_valor_total}")
    console.print(f"  VALOR_UNITARIO: {total_valor_unitario}")
    
    # Compara com a view
    console.print(f"\nDados na view ranking_clientes:")
    view_data = con.execute("""
        SELECT * FROM ranking_clientes
        WHERE cliente = ?
    """, [first_client]).fetchdf()
    
    if not view_data.empty:
        for _, row in view_data.iterrows():
            console.print(f"  valor_total (na view): {row['valor_total']}")
            console.print(f"  ticket_medio (na view): {row['ticket_medio']}")
            console.print(f"  total_pedidos (na view): {row['total_pedidos']}")
    else:
        console.print("  [yellow]Cliente não encontrado na view![/yellow]")


if __name__ == "__main__":
    main()
