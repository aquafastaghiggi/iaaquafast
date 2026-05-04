"""
Aquafast — Diagnóstico de Views

Examina as queries das views para identificar problemas de cálculo.
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
    
    con = duckdb.connect(str(DB_PATH), read_only=True)
    
    try:
        console.print("\n[bold cyan]🔍 ANÁLISE DE VIEWS[/bold cyan]\n")
        
        # Mostra a DDL de cada view
        views = ["ranking_clientes", "ranking_produtos", "vendas_por_mes"]
        
        for view in views:
            try:
                # Tenta mostrar a definição da view
                console.print(f"[bold]{view}[/bold]")
                
                ddl = con.execute(f"""
                    SELECT sql FROM duckdb_views() WHERE view_name = '{view}'
                """).fetchone()
                
                if ddl:
                    console.print(f"[dim]{ddl[0]}[/dim]\n")
                else:
                    console.print("[yellow]Não conseguiu obter SQL da view[/yellow]\n")
                    
            except Exception as e:
                console.print(f"[red]Erro: {e}[/red]\n")
        
        # Verifica cálculos específicos
        console.print("\n[bold]Verificação de Cálculos Específicos[/bold]\n")
        
        # Valida ticket_medio
        console.print("Validando ticket_medio:\n")
        
        test = con.execute("""
            SELECT
                cliente,
                total_pedidos,
                valor_total,
                ROUND(valor_total / total_pedidos, 2) as ticket_correto,
                ticket_medio as ticket_na_view
            FROM ranking_clientes
            ORDER BY valor_total DESC
            LIMIT 5
        """).fetchdf()
        
        console.print("Cliente | Pedidos | Valor Total | Ticket Correto | Ticket View | Match?")
        console.print("-" * 80)
        for _, row in test.iterrows():
            match = "✓" if abs(row['ticket_correto'] - row['ticket_na_view']) < 0.01 else "✗"
            console.print(f"{str(row['cliente'])[:20]:20} | {row['total_pedidos']:7} | {row['valor_total']:11.2f} | {row['ticket_correto']:14.2f} | {row['ticket_na_view']:11.2f} | {match}")
        
        # Valida somas de produtos
        console.print("\n\nValidando receita total dos produtos:\n")
        
        test2 = con.execute("""
            SELECT
                produto,
                total_vendas,
                receita_total,
                ROUND(COUNT(*) * AVG(CAST(VALOR_UNITARIO AS DOUBLE)), 2) as receita_unitaria_esperada
            FROM ranking_produtos rp
            LEFT JOIN scanntech s ON rp.produto = s.COD_PRODUTO
            GROUP BY rp.produto, rp.total_vendas, rp.receita_total
            ORDER BY receita_total DESC
        """).fetchdf()
        
        console.print("Produto | Vendas | Receita View | Receita Unitária (esperada) | Match?")
        console.print("-" * 80)
        
        for _, row in test2.iterrows():
            if row['receita_unitaria_esperada'] is None or row['receita_unitaria_esperada'] == 0:
                match = "?"
            else:
                match = "✓" if abs(float(row['receita_total']) - float(row['receita_unitaria_esperada'])) < 0.01 else "✗"
            
            console.print(f"{str(row['produto'])[:10]:10} | {row['total_vendas']:6} | {row['receita_total']:12.2f} | {str(row['receita_unitaria_esperada'])[:26]:26} | {match}")
        
    finally:
        con.close()


if __name__ == "__main__":
    main()
