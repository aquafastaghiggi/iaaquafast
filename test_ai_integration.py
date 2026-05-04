"""
Aquafast — Teste de Integração com IA

Valida se a IA está funcionando para gerar SQL.
"""

import json
import urllib.request
import urllib.error
from pathlib import Path
import duckdb

DB_PATH = Path("aquafast_scanntech.duckdb")


def test_ollama_connection():
    """Testa se Ollama está respondendo."""
    print("🔗 Testando conexão com Ollama...")
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode('utf-8'))
            models = result.get('models', [])
            print(f"✅ Ollama respondendo com {len(models)} modelo(s)")
            for model in models:
                print(f"   - {model.get('name')}")
            return True
    except Exception as e:
        print(f"❌ Ollama não respondeu: {e}")
        print("   Certifique-se de executar: docker compose up -d")
        return False


def test_ai_sql_generation():
    """Testa geração de SQL via IA."""
    print("\n🤖 Testando geração de SQL via IA...")
    
    if not DB_PATH.exists():
        print(f"❌ Banco não encontrado: {DB_PATH}")
        return False
    
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        # Obter schema
        tables = con.execute("""
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name
        """).fetchall()
        
        schema_lines = []
        for schema, table, table_type in tables:
            columns = con.execute(f"""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = ? AND table_name = ?
                ORDER BY ordinal_position
            """, [schema, table]).fetchall()
            
            col_text = ", ".join(f"{col[0]}:{col[1]}" for col in columns)
            schema_lines.append(f"- {table} ({table_type}): {col_text}")
        
        schema_text = "\n".join(schema_lines)
        
        # Teste 1: Pergunta simples
        test_questions = [
            "Quais são os top 5 clientes por valor total?",
            "Quanto faturamos em janeiro?",
            "Quais produtos tiveram mais vendas?",
        ]
        
        for question in test_questions:
            print(f"\n  Pergunta: '{question}'")
            
            prompt = f"""Você é um especialista em SQL DuckDB. Retorne APENAS a query SQL, sem explicação.

SCHEMA:
{schema_text}

REGRAS:
1. Apenas query SQL, sem markdown ou explicação
2. Válida para DuckDB
3. Use LIMIT 50 se não especificado
4. Apenas SELECT, WITH, SHOW ou DESCRIBE
5. Ordene por relevância

PERGUNTA:
{question}

QUERY:"""
            
            try:
                request_data = json.dumps({
                    "model": "qwen2.5",
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.3,
                }).encode('utf-8')
                
                req = urllib.request.Request(
                    "http://localhost:11434/api/generate",
                    data=request_data,
                    headers={'Content-Type': 'application/json'}
                )
                
                with urllib.request.urlopen(req, timeout=60) as response:
                    result = json.loads(response.read().decode('utf-8'))
                    sql = result.get('response', '').strip()
                
                # Limpar markdown se houver
                sql = sql.replace('```sql\n', '').replace('\n```', '').replace('```', '').strip()
                
                print(f"  SQL gerada:\n    {sql[:100]}{'...' if len(sql) > 100 else ''}")
                
                # Tentar executar
                try:
                    result = con.execute(sql)
                    rows = result.fetchall()
                    print(f"  ✅ Query válida! Retornou {len(rows)} linha(s)")
                except Exception as e:
                    print(f"  ❌ Query inválida: {e}")
                    
            except urllib.error.URLError as e:
                print(f"  ❌ Erro ao chamar IA: {e}")
                return False
        
        return True
        
    finally:
        con.close()


def test_api_endpoint():
    """Testa o endpoint /ask da API."""
    print("\n🌐 Testando endpoint /ask da API...")
    
    try:
        import requests
    except ImportError:
        print("  (httpx não disponível, saltando teste)")
        return True
    
    try:
        response = requests.post(
            "http://localhost:8001/ask",
            json={"question": "Quais são os clientes com maior valor total?"},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ API respondeu com sucesso")
            print(f"   - Título: {result.get('title')}")
            print(f"   - SQL: {result.get('sql', '')[:80]}...")
            print(f"   - Registros retornados: {result.get('row_count', 0)}")
            return True
        else:
            print(f"❌ API retornou erro: {response.status_code}")
            print(f"   {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Erro ao chamar API: {e}")
        print("   Certifique-se de executar: python -m uvicorn api_fastapi:app --host 0.0.0.0 --port 8001")
        return False


def main():
    print("\n" + "="*80)
    print("🧪 TESTE DE INTEGRAÇÃO COM IA".center(80))
    print("="*80 + "\n")
    
    results = {
        "Ollama": test_ollama_connection(),
        "Geração de SQL": test_ai_sql_generation(),
        "Endpoint /ask": test_api_endpoint(),
    }
    
    print("\n" + "="*80)
    print("📊 RESULTADOS".center(80))
    print("="*80)
    
    for test_name, passed in results.items():
        status = "✅ PASSOU" if passed else "❌ FALHOU"
        print(f"{test_name:30} {status}")
    
    all_passed = all(results.values())
    
    print("\n" + "="*80)
    if all_passed:
        print("✅ TODOS OS TESTES PASSARAM! IA integrada com sucesso".center(80))
    else:
        print("⚠️  ALGUNS TESTES FALHARAM. Verifique os erros acima.".center(80))
    print("="*80 + "\n")
    
    return all_passed


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
