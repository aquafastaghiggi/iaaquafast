# Handoff - Open WebUI sem modelos listados (2026-05-06)

## Contexto
- Projeto: `iaaquafast` (Aquafast IA local com Open WebUI + Ollama + scanntech-api).
- Objetivo da sessão: deixar apenas o `Scanntech Analyst` disponível e padrão, consultando base Scanntech.
- Estado final reportado pelo usuário: **não funcionou**; no fim, o Open WebUI ficou em estado de **nenhum modelo disponível** em alguns testes.

## Sintoma principal
- UI mostra "Selecione um modelo" e "Nenhum modelo disponível".
- Em outros momentos, o topo mostrava `scanntech-analyst:latest`, mas as respostas eram genéricas (sem consulta na base), indicando fallback para LLM puro.

## Causa observada durante a sessão
- A função pipe `Scanntech Analyst` oscilou entre ativo/inativo (`function.is_active`).
- Houve erro de carregamento da função no Open WebUI por BOM UTF-8:
  - `invalid non-printable character U+FEFF`
- Quando o pipe falha/inativa, a UI cai para modelos locais do Ollama (ou fica sem modelo se filtro bloqueia tudo).

## IDs importantes
- `function.id`: `ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc`
- `pipe model id` esperado no Open WebUI:
  - `ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc.scanntech_analyst`

## Arquivos alterados nesta linha de trabalho
- `docker-compose.yml`
- `openwebui_scanntech_function.py`
- `scripts/push_scanntech_function_to_db.py`
- `scripts/fix_scanntech_pipe_mode.py`
- `scripts/fix_openwebui_default_model.py`
- `OPENWEBUI_TROUBLESHOOTING.md`

## O que foi tentado
1. Forçar default no `docker-compose.yml` para o pipe id (`DEFAULT_MODELS`, `DEFAULT_PINNED_MODELS`, `MODEL_FILTER_LIST`).
2. Regravar `config`, `user.settings` e `chat.chat` no `webui.db` para o pipe id.
3. Reativar `function.is_active=1`.
4. Remover fallback local (`qwen2.5` e/ou alias `scanntech-analyst:latest`) para impedir respostas genéricas.
5. Reescrever conteúdo da função sem BOM e reiniciar container.

## Estado final desta sessão
- Usuário confirmou: **ainda não funcional** para uso esperado.
- Última exigência do usuário: **não tentar corrigir agora**, apenas documentar e versionar.

## Observações para o próximo responsável
- Confirmar no `webui.db` se `function.content` inicia com `"` (sem BOM), não com `\ufeff`.
- Confirmar se o Open WebUI carrega o pipe sem erro no log.
- Evitar misturar "modelo local Ollama" e "pipe id" no seletor ao mesmo tempo.
- Validar sempre via **Novo Chat** após cada alteração de default.

## Comandos úteis (referência)
- Ver função/modelo no DB:
  - `docker exec aquafast_webui python -c "import sqlite3; c=sqlite3.connect('/app/backend/data/webui.db'); cur=c.cursor(); print(cur.execute('select id,name,is_active from function').fetchall()); print(cur.execute('select id,name,is_active from model').fetchall()); c.close()"`
- Ver saúde da API Scanntech:
  - `docker exec aquafast_scanntech_api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').read().decode())"`

