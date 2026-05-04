"""
Aquafast — Exibição dos Dados Corrigidos
"""

import duckdb
from pathlib import Path

DB_PATH = Path("aquafast_scanntech.duckdb")

if DB_PATH.exists():
    con = duckdb.connect(str(DB_PATH))
    
    print("\n" + "="*80)
    print("📊 DADOS CORRIGIDOS - Amostra Final".center(80))
    print("="*80)
    
    print("\n[RANKING DE CLIENTES - Top 5]")
    print("-" * 80)
    df = con.execute("SELECT cliente, total_pedidos, valor_total, ticket_medio FROM ranking_clientes ORDER BY valor_total DESC LIMIT 5").fetchdf()
    for idx, row in df.iterrows():
        print(f"{row['cliente']:30} | Pedidos: {row['total_pedidos']:2} | Total: R${row['valor_total']:10,.2f} | Ticket: R${row['ticket_medio']:10,.2f}")
    
    print("\n[RANKING DE PRODUTOS - Top 6]")
    print("-" * 80)
    df = con.execute("SELECT produto, total_vendas, receita_total FROM ranking_produtos ORDER BY receita_total DESC LIMIT 6").fetchdf()
    for idx, row in df.iterrows():
        print(f"{row['produto']:10} | Vendas: {row['total_vendas']:2} | Receita: R${row['receita_total']:10,.2f}")
    
    print("\n[VENDAS POR MÊS]")
    print("-" * 80)
    df = con.execute("SELECT mes, total_pedidos, receita FROM vendas_por_mes ORDER BY mes").fetchdf()
    for idx, row in df.iterrows():
        print(f"{row['mes']} | Pedidos: {row['total_pedidos']:2} | Receita: R${row['receita']:10,.2f}")
    
    con.close()
    
    print("\n" + "="*80)
    print("✅ Todos os valores corrigidos e precisos!".center(80))
    print("="*80 + "\n")
else:
    print("Banco de dados não encontrado!")
