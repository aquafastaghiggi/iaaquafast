# 🔧 Troubleshooting: Open WebUI caindo para modelo base

## Diagnóstico do Problema

**Sintoma:** O chat abre com `qwen2.5:latest` em vez de `Scanntech Analyst`, respondendo "genérico" e fora do contexto.

**Causa raiz:** O Open WebUI está ignorando a configuração padrão `DEFAULT_MODELS` no `docker-compose.yml`, ou o ID da função está incorreto.

---

## 🛡️ Proteção Automática (Implementada)

O pipe `Scanntech Analyst` agora **detecta e bloqueia automaticamente** quando alguém tenta usá-lo como modelo direto:

```
⚠️ ERRO: Modelo incorreto selecionado

Você selecionou `qwen2.5:latest` em vez de usar o pipe **Scanntech Analyst**.

O que fazer:
1. Clique no seletor de modelo no topo do chat
2. Procure por "Scanntech Analyst" (não por "qwen2.5")
3. Selecione "Scanntech Analyst"
4. Envie sua pergunta novamente
```

Mesmo que o modelo base abra acidentalmente, o pipe responde com essa instrução clara.

---

## 🔍 Como Encontrar o ID Correto da Função

### Opção 1: Via Arquivo de Configuração do Open WebUI

```bash
# Entre no container do Open WebUI
docker exec -it aquafast_webui bash

# Procure pelo arquivo de configuração da função
find /app/backend/data -name "*.json" | xargs grep -l "scanntech_analyst" 2>/dev/null

# Procure especificamente em:
cat /app/backend/data/webui.db  # ou /app/backend/data/functions.json
```

### Opção 2: Via Interface do Open WebUI

1. Acesse http://localhost:3000
2. Faça login
3. Clique em ⚙️ **Settings** → **Functions**
4. Procure por **"Scanntech Analyst"**
5. Copie o ID que aparece no URL ou na interface

### Opção 3: Via API do Open WebUI

```bash
# Listar todas as funções
curl -s http://localhost:3000/api/v1/functions | jq '.'

# Procure pela função "Scanntech Analyst" e copie o "id"
```

---

## 📝 Como Corrigir o docker-compose.yml

Após encontrar o ID correto, edite o arquivo `docker-compose.yml`:

```yaml
services:
  open-webui:
    environment:
      # Substitua "SEU_ID_AQUI" pelo ID encontrado acima
      - DEFAULT_MODELS=SEU_ID_AQUI.scanntech_analyst
      - DEFAULT_PINNED_MODELS=SEU_ID_AQUI.scanntech_analyst
```

**Exemplo completo:**
```yaml
- DEFAULT_MODELS=f1a2b3c4-5d6e-7f8g-9h0i-j1k2l3m4n5o6.scanntech_analyst
- DEFAULT_PINNED_MODELS=f1a2b3c4-5d6e-7f8g-9h0i-j1k2l3m4n5o6.scanntech_analyst
```

### Aplicar a Mudança

```bash
# Parar o Open WebUI
docker compose down open-webui

# Reiniciar com a nova configuração
docker compose up -d open-webui

# Aguardar ~30 segundos para inicializar
sleep 30

# Verificar logs
docker compose logs open-webui
```

---

## ✅ Verificação Pós-Configuração

1. Acesse http://localhost:3000
2. Crie um **novo chat**
3. **Observe o seletor de modelo no topo** — deve aparecer **"Scanntech Analyst"** como padrão
4. Se ainda aparecer `qwen2.5`, significa que o ID está errado ou não foi aplicado

---

## 🎯 Soluções Alternativas se o docker-compose.yml não funcionar

### Opção A: Lock manual via Open WebUI

Se `DEFAULT_MODELS` não funcionar, você pode:

1. Acessar Settings → Preferences
2. Selecionar manualmente **"Scanntech Analyst"** como favorito (⭐)
3. Desabilitar `qwen2.5:latest` se possível

### Opção B: Fixar modelo via Scripts de Inicialização

Criar um script de inicialização que:
- Verifica qual modelo está selecionado
- Se for `qwen2.5`, redireciona automaticamente
- (Já implementado no pipe com a proteção)

### Opção C: Modo Single-Model (Mais restritivo)

Se nada funcionar, remova todos os modelos exceto o Scanntech Analyst:

```bash
# Via API
curl -X DELETE http://localhost:3000/api/v1/models/qwen2.5:latest

# Ou manualmente via Settings → Models
```

---

## 📊 Resumo das 3 Causas e Soluções

| Causa | Solução | Prioridade |
|-------|---------|-----------|
| **ID da função incorreto no docker-compose** | Corrigir `DEFAULT_MODELS` com ID certo (Opção 2 ou 3 acima) | 🔴 Alta |
| **Usuário seleciona qwen2.5 acidentalmente** | Proteção automática no pipe avisa e redireciona | ✅ Implementado |
| **Open WebUI ignora DEFAULT_MODELS** | Usar solução alternativa: fixar via Interface ou Scripts | 🟡 Média |

---

## 🧪 Teste Rápido

```bash
# Enviar pergunta teste ao pipe (simula novo chat com modelo errado)
curl -X POST http://localhost:3000/api/v1/pipes \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:latest",
    "messages": [{"role": "user", "content": "Quantas lojas?"}]
  }'

# Resposta esperada: Bloqueio com instrução de redirecionamento
```

---

## 📚 Referências

- [Open WebUI Docs - Environment Variables](https://docs.openwebui.com)
- [Docker Compose Reference](https://docs.docker.com/compose/)
- `docker-compose.yml` - configuração atual do projeto
- `openwebui_scanntech_function.py` - implementação do pipe com proteção
