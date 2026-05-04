"""
Aquafast — Testes de Integridade de Dados

Testes automáticos para garantir que as views retornam valores corretos.
Execute com: python -m pytest tests/test_data_integrity.py -v
"""

import duckdb
import pytest
from pathlib import Path
from decimal import Decimal


@pytest.fixture
def db_connection():
    """Fixture que fornece conexão ao banco DuckDB."""
    db_path = Path("aquafast_scanntech.duckdb")
    if not db_path.exists():
        pytest.skip("Banco de dados não encontrado")
    
    con = duckdb.connect(str(db_path), read_only=True)
    yield con
    con.close()


class TestRankingClientes:
    """Testes para integridade da view ranking_clientes."""
    
    def test_ranking_clientes_nao_vazio(self, db_connection):
        """Deve retornar pelo menos um cliente."""
        result = db_connection.execute("SELECT COUNT(*) FROM ranking_clientes").fetchone()
        assert result[0] > 0, "ranking_clientes deve ter registros"
    
    def test_valor_total_e_positivo(self, db_connection):
        """Todos os valores totais devem ser positivos."""
        result = db_connection.execute("""
            SELECT COUNT(*) FROM ranking_clientes
            WHERE valor_total <= 0
        """).fetchone()
        assert result[0] == 0, "Não pode haver valor_total <= 0"
    
    def test_ticket_medio_correto(self, db_connection):
        """Ticket médio deve ser valor_total / total_pedidos."""
        resultado = db_connection.execute("""
            SELECT 
                cliente,
                total_pedidos,
                valor_total,
                ticket_medio,
                ROUND(valor_total / total_pedidos, 2) as ticket_esperado
            FROM ranking_clientes
            LIMIT 100
        """).fetchdf()
        
        erros = []
        for _, row in resultado.iterrows():
            if abs(float(row['ticket_medio']) - float(row['ticket_esperado'])) > 0.01:
                erros.append(
                    f"Cliente '{row['cliente']}': ticket_medio={row['ticket_medio']}, "
                    f"esperado={row['ticket_esperado']}"
                )
        
        assert len(erros) == 0, f"Cálculo de ticket_medio incorreto:\n" + "\n".join(erros)
    
    def test_datas_consistentes(self, db_connection):
        """Primeira compra deve ser <= última compra."""
        result = db_connection.execute("""
            SELECT COUNT(*) FROM ranking_clientes
            WHERE primeira_compra > ultima_compra
        """).fetchone()
        assert result[0] == 0, "Primeira compra não pode ser depois de última compra"
    
    def test_cliente_nao_vazio(self, db_connection):
        """Cliente não pode ser vazio."""
        result = db_connection.execute("""
            SELECT COUNT(*) FROM ranking_clientes
            WHERE cliente = '' OR cliente IS NULL
        """).fetchone()
        assert result[0] == 0, "Cliente não pode ser vazio ou NULL"
    
    def test_nao_usa_valor_unitario(self, db_connection):
        """Verifica se ticket_medio NÃO está usando valor_unitario."""
        # Se ticket_medio for a média de VALOR_UNITARIO, será muito baixo
        resultado = db_connection.execute("""
            SELECT AVG(ticket_medio) as media_tickets
            FROM ranking_clientes
        """).fetchone()
        
        media = float(resultado[0]) if resultado[0] else 0
        
        # Se fosse média de VALOR_UNITARIO (~50-100), seria muito baixo
        # Ticket médio correto deve ser bem maior (milhares)
        assert media > 500, (
            f"Ticket médio suspeitosamente baixo ({media:.2f}). "
            f"Pode estar usando VALOR_UNITARIO em vez de VALOR_TOTAL"
        )


class TestRankingProdutos:
    """Testes para integridade da view ranking_produtos."""
    
    def test_ranking_produtos_nao_vazio(self, db_connection):
        """Deve retornar pelo menos um produto."""
        result = db_connection.execute("SELECT COUNT(*) FROM ranking_produtos").fetchone()
        assert result[0] > 0, "ranking_produtos deve ter registros"
    
    def test_receita_e_positiva(self, db_connection):
        """Todas as receitas devem ser positivas."""
        result = db_connection.execute("""
            SELECT COUNT(*) FROM ranking_produtos
            WHERE receita_total <= 0
        """).fetchone()
        assert result[0] == 0, "Não pode haver receita_total <= 0"
    
    def test_receita_usa_valor_total(self, db_connection):
        """Receita não pode ser muito baixa (indicativo de uso de VALOR_UNITARIO)."""
        resultado = db_connection.execute("""
            SELECT AVG(receita_total) as media_receita
            FROM ranking_produtos
        """).fetchone()
        
        media = float(resultado[0]) if resultado[0] else 0
        
        # Se fosse apenas soma de VALOR_UNITARIO, seria muito baixo
        assert media > 1000, (
            f"Receita média suspeitosamente baixa ({media:.2f}). "
            f"Pode estar usando VALOR_UNITARIO em vez de VALOR_TOTAL"
        )
    
    def test_total_vendas_positivo(self, db_connection):
        """Total de vendas deve ser > 0."""
        result = db_connection.execute("""
            SELECT COUNT(*) FROM ranking_produtos
            WHERE total_vendas <= 0
        """).fetchone()
        assert result[0] == 0, "total_vendas deve ser > 0"
    
    def test_produto_nao_vazio(self, db_connection):
        """Produto não pode ser vazio."""
        result = db_connection.execute("""
            SELECT COUNT(*) FROM ranking_produtos
            WHERE produto = '' OR produto IS NULL
        """).fetchone()
        assert result[0] == 0, "Produto não pode ser vazio"


class TestVendasPorMes:
    """Testes para integridade da view vendas_por_mes."""
    
    def test_vendas_por_mes_nao_vazio(self, db_connection):
        """Deve retornar pelo menos um mês."""
        result = db_connection.execute("SELECT COUNT(*) FROM vendas_por_mes").fetchone()
        assert result[0] > 0, "vendas_por_mes deve ter registros"
    
    def test_receita_positiva(self, db_connection):
        """Todas as receitas mensais devem ser positivas."""
        result = db_connection.execute("""
            SELECT COUNT(*) FROM vendas_por_mes
            WHERE receita <= 0
        """).fetchone()
        assert result[0] == 0, "Receita mensal não pode ser <= 0"
    
    def test_total_pedidos_positivo(self, db_connection):
        """Total de pedidos deve ser > 0."""
        result = db_connection.execute("""
            SELECT COUNT(*) FROM vendas_por_mes
            WHERE total_pedidos <= 0
        """).fetchone()
        assert result[0] == 0, "total_pedidos deve ser > 0"
    
    def test_mes_formato_correto(self, db_connection):
        """Mes deve estar em formato YYYY-MM."""
        result = db_connection.execute("""
            SELECT COUNT(*) FROM vendas_por_mes
            WHERE mes NOT LIKE '____-__'
        """).fetchone()
        assert result[0] == 0, "Mes deve estar em formato YYYY-MM"
    
    def test_receita_nao_inventada(self, db_connection):
        """Receita mensal não pode ser muito baixa."""
        resultado = db_connection.execute("""
            SELECT AVG(receita) as media_receita
            FROM vendas_por_mes
        """).fetchone()
        
        media = float(resultado[0]) if resultado[0] else 0
        
        # Se fosse apenas soma de VALOR_UNITARIO, seria muito baixo
        assert media > 500, (
            f"Receita média mensal suspeitosamente baixa ({media:.2f}). "
            f"Pode estar usando VALOR_UNITARIO em vez de VALOR_TOTAL"
        )


class TestConsistenciaGeral:
    """Testes de consistência entre tables e views."""
    
    def test_soma_receita_mes_vs_clientes(self, db_connection):
        """Soma de receita em vendas_por_mes deve ~ bater com soma de ranking_clientes."""
        receita_mes = db_connection.execute("""
            SELECT SUM(receita) FROM vendas_por_mes
        """).fetchone()[0]
        
        receita_clientes = db_connection.execute("""
            SELECT SUM(valor_total) FROM ranking_clientes
        """).fetchone()[0]
        
        receita_mes = float(receita_mes) if receita_mes else 0
        receita_clientes = float(receita_clientes) if receita_clientes else 0
        
        # Devem ser aproximadamente iguais (pode ter pequenas variações de arredondamento)
        diferenca = abs(receita_mes - receita_clientes)
        tolerancia = receita_clientes * 0.01  # 1% de tolerância
        
        assert diferenca <= tolerancia, (
            f"Receita total inconsistente: "
            f"vendas_por_mes={receita_mes:.2f}, "
            f"ranking_clientes={receita_clientes:.2f}, "
            f"diferença={diferenca:.2f}"
        )
    
    def test_total_vendas_produtos_vs_clientes(self, db_connection):
        """Soma de vendas em ranking_produtos deve bater com total de linhas."""
        total_linhas = db_connection.execute("""
            SELECT COUNT(*) FROM scanntech
        """).fetchone()[0]
        
        total_vendas = db_connection.execute("""
            SELECT SUM(total_vendas) FROM ranking_produtos
        """).fetchone()[0]
        
        total_vendas = int(total_vendas) if total_vendas else 0
        
        assert total_vendas == total_linhas, (
            f"Total de vendas não confere: "
            f"scanntech={total_linhas}, "
            f"ranking_produtos={total_vendas}"
        )
    
    def test_nao_ha_valores_null_nas_views(self, db_connection):
        """Views não devem ter NULLs em campos críticos."""
        views_campos = {
            'ranking_clientes': ['cliente', 'total_pedidos', 'valor_total', 'ticket_medio'],
            'ranking_produtos': ['produto', 'total_vendas', 'receita_total'],
            'vendas_por_mes': ['mes', 'total_pedidos', 'receita'],
        }
        
        erros = []
        for view, campos in views_campos.items():
            for campo in campos:
                result = db_connection.execute(f"""
                    SELECT COUNT(*) FROM {view}
                    WHERE {campo} IS NULL
                """).fetchone()
                
                if result[0] > 0:
                    erros.append(f"{view}.{campo} tem {result[0]} NULLs")
        
        assert len(erros) == 0, "Campos críticos não devem ser NULL:\n" + "\n".join(erros)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
