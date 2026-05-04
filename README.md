# 🚀 Aquafast IA — Análise Scanntech Local

Stack completa de IA local para análise do arquivo Scanntech.
Tudo roda no seu PC, sem custo, sem dados saindo da empresa.

---

## O que está incluído

| Serviço | Porta | Para quê |
|---|---|---|
| **Open WebUI** | http://localhost:3000 | Chat estilo ChatGPT com os dados |
| **Scanntech API** | http://localhost:8001 | Consulta determinística ao DuckDB |
| **Metabase** | http://localhost:3001 | Dashboards e gráficos visuais |
| **Ollama** | http://localhost:11434 | Motor de IA local (interno) |

---

## Pré-requisitos

- Docker Desktop instalado e rodando
- Python 3.10+ instalado
- ~8GB de RAM disponível
- ~15GB de disco livre

---

## Passo 1 — Subir os containers

Abra o terminal na pasta do projeto e execute:

```bash
docker compose up -d
```

Aguarde ~2 minutos. Para verificar se subiu:

```bash
docker compose ps
```

Todos devem aparecer como `running`.

---

## Passo 2 — Baixar o modelo de IA

Com os containers rodando, baixe o modelo (só na primeira vez):

```bash
# Qwen 2.5 — melhor para análise estruturada e tabelas
docker exec aquafast_ollama ollama pull qwen2.5

# Aguarde o download (~2GB)
# Para ver o progresso, abra outro terminal e execute:
docker logs -f aquafast_ollama
```

> ⚠️ **Sem GPU:** O modelo qwen2.5 funciona bem em CPU.
> Resposta em ~10-30 segundos por mensagem — normal para CPU only.

---

## Passo 3 — Instalar dependências Python

```bash
pip install duckdb pandas rich chardet
```

---

## Passo 4 — Ingerir o arquivo Scanntech

Quando você tiver o arquivo CSV/TXT em mãos:

```bash
# Preview primeiro — não importa, só mostra as colunas
python ingest_scanntech.py --arquivo C:\caminho\scanntech.csv --preview-only

# Importação completa (demora alguns minutos para 200MB)
python ingest_scanntech.py --arquivo C:\caminho\scanntech.csv
```

O script vai:
1. Detectar encoding e separador automaticamente
2. Mostrar preview das primeiras linhas
3. Importar tudo para DuckDB (suporta arquivos gigantes)
4. Criar views prontas para consulta
5. Exportar CSVs para o Metabase

---

## Passo 5 — Acessar o chat

Abra: **http://localhost:3000**

Na primeira vez:
1. Crie uma conta de admin
2. Use o modelo `Scanntech Analyst`
3. Ele decide sozinho quando consultar o DuckDB e quando responder com `qwen2.5`
4. Se você pedir `Excel`, `planilha` ou `xlsx`, ele gera um arquivo `.xlsx` com a consulta mais recente

**Exemplos de perguntas:**
- "Quais são os 10 clientes que mais compraram?"
- "Tem algum cliente que não compra há mais de 3 meses?"
- "Qual produto tem maior volume de vendas?"

### Modelo grounded

`Scanntech Analyst` não tenta adivinhar.
Ele usa o `qwen2.5` para conversa livre e consulta o DuckDB local via `Scanntech API` quando a pergunta pede dados.
Se a pergunta não for suportada, ele responde isso explicitamente em vez de inventar.

### Como saber que a IA está funcionando

- Se você pedir algo analítico, o número vem do DuckDB.
- Se você pedir explicação, resumo executivo, comparação ou texto em linguagem natural, o `qwen2.5` entra em cena.
- O sinal mais claro de inteligência aqui é a interpretação da intenção e a forma de explicar o resultado, não a origem dos números.
- Exemplo bom para testar: `me explique em linguagem executiva o que significa esse top 20 de produtos`.

---

## Passo 6 — Acessar os dashboards (Metabase)

Abra: **http://localhost:3001**

Na primeira vez:
1. Complete o setup inicial
2. Em `Databases` > `Add database`:
   - Tipo: **CSV** (use os arquivos em `./exports/`)
   - Ou instale o driver DuckDB (ver METABASE_CONFIG.txt)
3. Crie seus dashboards com os dados Scanntech

---

## Consultas rápidas via terminal

Para consultar sem abrir o browser:

```bash
python query_scanntech.py
```

Menu interativo com consultas prontas:
- Top clientes por valor
- Produtos mais vendidos
- Vendas por mês
- Clientes em risco de churn
- SQL livre

---

## Parar os containers

```bash
docker compose stop
```

Para remover tudo (dados ficam nos volumes):

```bash
docker compose down
```

Para remover tudo incluindo dados:

```bash
docker compose down -v
```

---

## Estrutura de arquivos

```
aquafast-ia/
├── docker-compose.yml       ← sobe todos os serviços
├── ingest_scanntech.py      ← importa o CSV para DuckDB
├── query_scanntech.py       ← consultas via terminal
├── README.md                ← este arquivo
├── METABASE_CONFIG.txt      ← gerado após o ingest
├── aquafast_scanntech.duckdb ← gerado após o ingest
└── exports/
    ├── ranking_clientes.csv  ← gerado após o ingest
    ├── ranking_produtos.csv
    └── vendas_por_mes.csv
```

---

## Troubleshooting

**Open WebUI não abre:**
```bash
docker logs aquafast_webui
```

**Ollama lento demais:**
Esperado em CPU. Para acelerar, considere um modelo menor:
```bash
docker exec aquafast_ollama ollama pull phi3.5
```

**Erro no ingest do CSV:**
Execute com `--preview-only` primeiro e me mande as colunas que aparecem.
Ajustamos o script para o formato exato do seu arquivo.

**Metabase não conecta ao banco:**
Veja o arquivo `METABASE_CONFIG.txt` gerado após o ingest.

---

## Próximos passos (quando quiser evoluir)

- [ ] Conectar o n8n para automatizar relatórios por e-mail
- [ ] Criar API REST sobre o DuckDB para o Metabase consumir
- [ ] Adicionar Evolution API para responder perguntas via WhatsApp
- [ ] Migrar modelo para Claude API quando assinar o plano

---

*Projeto Aquafast IA — uso interno*
