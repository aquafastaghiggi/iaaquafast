"""
==============================================================
 AQUAFAST — Console de consultas Scanntech
 Permite fazer perguntas em SQL direto no terminal
==============================================================

 Uso:
   python query_scanntech.py

 Requisitos:
   pip install duckdb rich

 Consultas úteis pré-definidas:
   1. Top 20 clientes por valor
   2. Produtos mais vendidos
   3. Vendas por mês
   4. Clientes sem compra há 90 dias
   5. SQL livre
==============================================================
"""

import duckdb
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint
import sys

console = Console()
DB_PATH = "aquafast_scanntech.duckdb"

CONSULTAS_PRONTAS = {
    "1": {
        "titulo": "Top 20 clientes por valor total",
        "sql": "SELECT * FROM ranking_clientes LIMIT 20"
    },
    "2": {
        "titulo": "Top 20 produtos mais vendidos",
        "sql": "SELECT * FROM ranking_produtos LIMIT 20"
    },
    "3": {
        "titulo": "Vendas por mês",
        "sql": "SELECT * FROM vendas_por_mes ORDER BY mes"
    },
    "4": {
        "titulo": "Clientes sem compra há mais de 90 dias",
        "sql": """
            SELECT cliente, ultima_compra, total_pedidos, valor_total
            FROM ranking_clientes
            WHERE ultima_compra < CURRENT_DATE - INTERVAL '90 days'
            ORDER BY valor_total DESC
            LIMIT 50
        """
    },
    "5": {
        "titulo": "Clientes com apenas 1 compra (risco de churn)",
        "sql": """
            SELECT cliente, total_pedidos, valor_total, primeira_compra, ultima_compra
            FROM ranking_clientes
            WHERE total_pedidos = 1
            ORDER BY valor_total DESC
            LIMIT 50
        """
    },
    "6": {
        "titulo": "Resumo geral do arquivo",
        "sql": """
            SELECT 
                COUNT(*) as total_registros,
                COUNT(DISTINCT cliente) as total_clientes,
                ROUND(SUM(valor_total), 2) as receita_total,
                ROUND(AVG(ticket_medio), 2) as ticket_medio_geral,
                MIN(primeira_compra) as periodo_inicio,
                MAX(ultima_compra) as periodo_fim
            FROM ranking_clientes
        """
    },
}


def exibir_resultado(df, titulo: str = "Resultado"):
    """Exibe dataframe como tabela formatada."""
    if df.empty:
        console.print("[yellow]Nenhum resultado encontrado.[/yellow]")
        return
    
    table = Table(title=titulo, show_header=True, header_style="bold blue", row_styles=["", "dim"])
    
    for col in df.columns:
        table.add_column(str(col), overflow="fold")
    
    for _, row in df.iterrows():
        table.add_row(*[str(v) if v is not None else "" for v in row.values])
    
    console.print(table)
    console.print(f"[dim]{len(df)} linha(s) retornadas[/dim]")


def menu_principal(con: duckdb.DuckDBPyConnection):
    """Menu interativo de consultas."""
    
    while True:
        console.print(Panel.fit(
            "\n".join([
                "[bold]Consultas prontas:[/bold]",
                *[f"  [cyan]{k}[/cyan] → {v['titulo']}" for k, v in CONSULTAS_PRONTAS.items()],
                "",
                "  [cyan]s[/cyan] → SQL livre",
                "  [cyan]c[/cyan] → Ver colunas disponíveis",
                "  [cyan]q[/cyan] → Sair",
            ]),
            title="🚀 Aquafast — Análise Scanntech",
            border_style="blue"
        ))
        
        escolha = input("\nEscolha: ").strip().lower()
        
        if escolha == "q":
            console.print("[green]Até logo![/green]")
            break
        
        elif escolha == "c":
            schema = con.execute("DESCRIBE scanntech").fetchdf()
            exibir_resultado(schema, "Colunas disponíveis na tabela scanntech")
        
        elif escolha == "s":
            console.print("[dim]Digite sua consulta SQL (termine com ';' e Enter):[/dim]")
            linhas = []
            while True:
                linha = input("SQL> ")
                linhas.append(linha)
                if linha.strip().endswith(";"):
                    break
            sql = " ".join(linhas).rstrip(";")
            try:
                df = con.execute(sql).fetchdf()
                exibir_resultado(df, "Resultado SQL livre")
            except Exception as e:
                console.print(f"[red]Erro: {e}[/red]")
        
        elif escolha in CONSULTAS_PRONTAS:
            q = CONSULTAS_PRONTAS[escolha]
            console.print(f"\n[bold]{q['titulo']}[/bold]")
            try:
                df = con.execute(q["sql"]).fetchdf()
                exibir_resultado(df, q["titulo"])
            except Exception as e:
                console.print(f"[red]Erro ao executar consulta: {e}[/red]")
                console.print("[dim]As views podem não ter sido criadas. Execute o ingest primeiro.[/dim]")
        
        else:
            console.print("[yellow]Opção inválida.[/yellow]")
        
        input("\n[Enter para continuar]")


def main():
    try:
        con = duckdb.connect(DB_PATH, read_only=True)
        console.print(f"[green]✓[/green] Conectado ao banco: [cyan]{DB_PATH}[/cyan]")
        
        total = con.execute("SELECT COUNT(*) FROM scanntech").fetchone()[0]
        console.print(f"[green]✓[/green] Registros disponíveis: [bold]{total:,}[/bold]\n")
        
        menu_principal(con)
        con.close()
        
    except Exception as e:
        console.print(f"[red]Erro ao abrir banco: {e}[/red]")
        console.print(f"[dim]Execute primeiro: python ingest_scanntech.py --arquivo seu_arquivo.csv[/dim]")
        sys.exit(1)


if __name__ == "__main__":
    main()
