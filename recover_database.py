"""
Aquafast — Recuperação de Banco de Dados

Reconstrói as views com os cálculos corrigidos.
Não deleta os dados originais, apenas recria as views.
"""

import duckdb
from pathlib import Path
from rich.console import Console

console = Console()
DB_PATH = Path("aquafast_scanntech.duckdb")


def main():
    if not DB_PATH.exists():
        console.print(f"[red]Banco não encontrado: {DB_PATH}[/red]")
        return
    
    console.print("\n[bold cyan]🔧 RECUPERAÇÃO DO BANCO DE DADOS[/bold cyan]\n")
    console.print("[yellow]Recriando views com cálculos corrigidos...[/yellow]\n")
    
    con = duckdb.connect(str(DB_PATH))
    
    try:
        # Detecta as colunas corretas
        schema = con.execute("DESCRIBE scanntech").fetchdf()
        colunas = schema["column_name"].tolist()
        
        print(f"Colunas encontradas: {colunas}\n")
        
        # Detecta coluna de valor (prioriza VALOR_TOTAL)
        col_valor = None
        for prioridade in ["valor_total", "valor_liquido", "total", "valor"]:
            col_valor = next((c for c in colunas if prioridade in c.lower()), None)
            if col_valor:
                console.print(f"[green]✓[/green] Usando coluna de valor: {col_valor}")
                break
        
        if not col_valor:
            console.print("[red]✗ Nenhuma coluna de valor encontrada![/red]")
            return
        
        # Detecta outras colunas
        col_cliente = None
        for prioridade in ["razao_social", "razao", "cliente", "nome_cliente", "nome_fantasia"]:
            col_cliente = next((c for c in colunas if prioridade in c.lower()), None)
            if col_cliente:
                break
        if not col_cliente:
            col_cliente = next((c for c in colunas if "cnpj" in c.lower()), None)
        col_data = next((c for c in colunas if any(k in c.lower() for k in ["data", "date", "dt_"])), None)
        col_produto = next((c for c in colunas if any(k in c.lower() for k in ["produto", "sku", "cod_"])), None)
        
        console.print(f"[green]✓[/green] Coluna de cliente: {col_cliente}")
        console.print(f"[green]✓[/green] Coluna de data: {col_data}")
        console.print(f"[green]✓[/green] Coluna de produto: {col_produto}\n")
        
        # Remove views antigas
        console.print("[yellow]Removendo views antigas...[/yellow]")
        for view in ["ranking_clientes", "ranking_produtos", "vendas_por_mes"]:
            try:
                con.execute(f"DROP VIEW IF EXISTS {view}")
                console.print(f"  [dim]✓ {view} removida[/dim]")
            except Exception as e:
                console.print(f"  [dim]⚠ {view}: {e}[/dim]")
        
        console.print()
        
        # Recria ranking_clientes com cálculo correto
        if col_cliente and col_valor and col_data:
            console.print("[yellow]Recriando ranking_clientes...[/yellow]")
            try:
                con.execute(f"""
                    CREATE VIEW ranking_clientes AS
                    SELECT 
                        COALESCE(NULLIF(TRIM(CAST("{col_cliente}" AS VARCHAR)), ''), 'NAO_INFORMADO') as cliente,
                        COUNT(*) as total_pedidos,
                        ROUND(SUM(TRY_CAST("{col_valor}" AS DOUBLE)), 2) as valor_total,
                        ROUND(SUM(TRY_CAST("{col_valor}" AS DOUBLE)) / COUNT(*), 2) as ticket_medio,
                        MIN(CAST("{col_data}" AS VARCHAR)) as primeira_compra,
                        MAX(CAST("{col_data}" AS VARCHAR)) as ultima_compra
                    FROM scanntech
                    GROUP BY COALESCE(NULLIF(TRIM(CAST("{col_cliente}" AS VARCHAR)), ''), 'NAO_INFORMADO')
                    ORDER BY valor_total DESC NULLS LAST
                """)
                console.print("[green]✓[/green] ranking_clientes recriada com sucesso!\n")
            except Exception as e:
                console.print(f"[red]✗ Erro ao recriar ranking_clientes: {e}\n[/red]")
        
        # Recria ranking_produtos com cálculo correto
        if col_produto and col_valor:
            console.print("[yellow]Recriando ranking_produtos...[/yellow]")
            try:
                con.execute(f"""
                    CREATE VIEW ranking_produtos AS
                    SELECT 
                        COALESCE(NULLIF(TRIM(CAST("{col_produto}" AS VARCHAR)), ''), 'NAO_INFORMADO') as produto,
                        COUNT(*) as total_vendas,
                        ROUND(SUM(TRY_CAST("{col_valor}" AS DOUBLE)), 2) as receita_total
                    FROM scanntech
                    GROUP BY COALESCE(NULLIF(TRIM(CAST("{col_produto}" AS VARCHAR)), ''), 'NAO_INFORMADO')
                    ORDER BY receita_total DESC NULLS LAST
                """)
                console.print("[green]✓[/green] ranking_produtos recriada com sucesso!\n")
            except Exception as e:
                console.print(f"[red]✗ Erro ao recriar ranking_produtos: {e}\n[/red]")
        
        # Recria vendas_por_mes com cálculo correto
        if col_data and col_valor:
            console.print("[yellow]Recriando vendas_por_mes...[/yellow]")
            try:
                con.execute(f"""
                    CREATE VIEW vendas_por_mes AS
                    SELECT 
                        SUBSTR(CAST("{col_data}" AS VARCHAR), 1, 7) as mes,
                        COUNT(*) as total_pedidos,
                        ROUND(SUM(TRY_CAST("{col_valor}" AS DOUBLE)), 2) as receita
                    FROM scanntech
                    GROUP BY 1
                    ORDER BY 1
                """)
                console.print("[green]✓[/green] vendas_por_mes recriada com sucesso!\n")
            except Exception as e:
                console.print(f"[red]✗ Erro ao recriar vendas_por_mes: {e}\n[/red]")
        
        # Valida
        console.print("[bold cyan]Validação:[/bold cyan]\n")
        for view in ["ranking_clientes", "ranking_produtos", "vendas_por_mes"]:
            try:
                count = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
                console.print(f"  [green]✓[/green] {view}: {count} registros")
            except Exception as e:
                console.print(f"  [red]✗[/red] {view}: Erro - {e}")
        
    finally:
        con.close()
    
    console.print("\n[bold green]✅ Recuperação concluída![/bold green]\n")


if __name__ == "__main__":
    main()
