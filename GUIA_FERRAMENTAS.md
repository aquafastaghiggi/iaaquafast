```markdown
# 🛠️ GUIA DE USO - Ferramentas de Diagnóstico e Recuperação

## 📋 Resumo das Correções

Seu projeto tinha **3 problemas críticos** que foram corrigidos:

### Problemas Encontrados e Corrigidos:

| Problema | Efeito | Solução |
|----------|--------|---------|
| **Ticket médio** usando `AVG(VALOR_UNITARIO)` | Retornava R$ 55 em vez de R$ 2.800+ | Agora calcula `SUM(VALOR_TOTAL) / COUNT(*)` |
| **Receita de produtos** usando `VALOR_UNITARIO` | Inventava números baixos | Agora soma `VALOR_TOTAL` corretamente |
| **Receita mensal** usando `VALOR_UNITARIO` | Dados completamente errados | Agora usa `VALOR_TOTAL` |
| **Detecção de coluna de valor** | Pegava `VALOR_UNITARIO` em vez de `VALOR_TOTAL` | Agora prioriza `VALOR_TOTAL` |

---

## 🔧 Ferramentas Disponíveis

### 1. **recover_database.py** - Recuperação de Dados
Reconstrói as views com os cálculos corretos.

```bash
python recover_database.py
```

**O que faz:**
- ✅ Remove views antigas
- ✅ Detecta colunas corretas automaticamente
- ✅ Recria views com fórmulas corrigidas
- ✅ Valida integridade dos dados

**Quando usar:**
- Após atualizar o código do ingest
- Se suspeitar que os dados estão errados
- Quando migrar para novo arquivo CSV

---

### 2. **diagnose_data.py** - Diagnóstico Geral
Verifica a qualidade geral dos dados.

```bash
python diagnose_data.py
```

**Informações fornecidas:**
- 📊 Total de registros
- 📋 Schema detectado
- 🔍 Nulos e valores vazios por coluna
- ⚠️ Conversões de tipo falhando silenciosamente
- ✓ Status de cada view

---

### 3. **diagnose_detailed.py** - Análise Profunda
Examina dados linha por linha e valida cálculos.

```bash
python diagnose_detailed.py
```

**O que valida:**
- Primeiras 10 linhas (estrutura)
- Dados de uma view completa
- Agregações manuais vs views
- Exemplos de valores em cada coluna

---

### 4. **diagnose_views.py** - Análise de Views
Mostra as queries exatas das views e valida cálculos.

```bash
python diagnose_views.py
```

**Saída:**
- SQL exato de cada view
- Comparação de ticket_medio
- Validação de receita total

---

### 5. **tests/test_data_integrity.py** - Testes Automáticos
Suite de 19 testes para garantir integridade.

```bash
# Executar todos os testes
python -m pytest tests/test_data_integrity.py -v

# Executar apenas um teste
python -m pytest tests/test_data_integrity.py::TestRankingClientes -v

# Com output detalhado
python -m pytest tests/test_data_integrity.py -vv --tb=long
```

**Testes incluem:**
- ✅ Ticket médio calcula corretamente
- ✅ Receita usa VALOR_TOTAL (não VALOR_UNITARIO)
- ✅ Sem valores NULL críticos
- ✅ Somas consistentes entre views
- ✅ Datas logicamente ordenadas
- ✅ 19 validações no total

---

## 📊 Workflow Recomendado

### Quando Ingerir Novo Arquivo:

```bash
# 1. Ingerir novo arquivo (com código corrigido)
python ingest_scanntech.py --arquivo C:\caminho\seu_arquivo.csv

# 2. Recuperar o banco (recreia views)
python recover_database.py

# 3. Validar integridade
python -m pytest tests/test_data_integrity.py -v

# 4. Diagnóstico completo (opcional)
python diagnose_data.py
```

### Se Dados Parecerem Errados:

```bash
# 1. Diagnóstico rápido
python diagnose_data.py

# 2. Análise detalhada
python diagnose_views.py

# 3. Recuperar banco
python recover_database.py

# 4. Validar
python -m pytest tests/test_data_integrity.py -v
```

---

## ✨ Exemplo de Uso Real

```bash
# Seu arquivo tem dados novos
cd c:\xampp\htdocs\scantech

# Ingerir (com detecção automática)
python ingest_scanntech.py --arquivo scanntech_maio_2026.csv

# A API ainda está rodando com dados antigos?
# Recupere o banco:
python recover_database.py

# Veja o relatório
python diagnose_views.py

# Todos os testes passam?
python -m pytest tests/test_data_integrity.py -v
```

---

## 🚨 Sinais de Alerta

Se você vir algo assim:

| Sinal | Causa Provável | Solução |
|-------|----------------|---------|
| Ticket médio < R$ 500 | Usando VALOR_UNITARIO | `python recover_database.py` |
| Receita total muito baixa | Usando VALOR_UNITARIO | `python recover_database.py` |
| Testes falhando | Dados descalibrados | `python diagnose_data.py` |
| Views vazias | Problema na agregação | `python recover_database.py` |

---

## 📈 Métricas de Validação

Após as correções, esperamos ver:

```
✅ Ticket Médio: R$ 500 - R$ 5.000+ por cliente
✅ Receita Total: Valores em milhares/milhões
✅ Vendas por Mês: Distribuição lógica ao longo do tempo
✅ Todos os testes: PASSED (19/19)
```

---

## 🔐 Proteção Contra Erros Futuros

1. **Execute testes regularmente:**
   ```bash
   python -m pytest tests/test_data_integrity.py
   ```

2. **Use em CI/CD:**
   ```yaml
   # Seu workflow (GitHub Actions, etc)
   - name: Validate Data Integrity
     run: pytest tests/test_data_integrity.py -v
   ```

3. **Monitore com cron:**
   ```bash
   # Executar diagnóstico diariamente
   0 2 * * * cd /path/to/scantech && python diagnose_data.py >> diagnostico.log
   ```

---

## 📞 Próximos Passos

1. ✅ Banco de dados corrigido
2. ✅ Scripts de diagnóstico criados
3. ✅ Testes de integridade implementados
4. ⬜ (Opcional) Integrar testes no CI/CD
5. ⬜ (Opcional) Adicionar alertas se testes falharem

---

## 📖 Documentação Adicional

- [RELATORIO_CORRECOES.md](RELATORIO_CORRECOES.md) - Análise técnica dos problemas
- [README.md](README.md) - Guia geral do projeto
- [ingest_scanntech.py](ingest_scanntech.py) - Script de importação (corrigido)
```
