# Open WebUI + Scanntech Analyst Troubleshooting

## Ordem correta de operacao

0. Prepare as variaveis do MySQL:

```bash
Copy-Item .env.example .env
```

Ou exporte no shell as variaveis `AQUAFAST_MYSQL_HOST`, `AQUAFAST_MYSQL_PORT`, `AQUAFAST_MYSQL_USER`, `AQUAFAST_MYSQL_PASSWORD` e `AQUAFAST_MYSQL_DATABASE`.

1. Suba a stack:

```bash
docker compose up -d
```

2. Regrave o pipe no banco do Open WebUI:

```bash
python scripts/push_scanntech_function_to_db.py
```

3. Rode o doctor antes de abrir o chat:

```bash
python scripts/doctor_openwebui.py
```

4. Abra o Open WebUI e valide em `Novo Chat`.

## O que validar no Novo Chat

- O seletor de modelo deve mostrar `Scanntech Analyst`.
- O chat nao deve cair para `qwen2.5` ou outro modelo generico.
- As perguntas oficiais da Aquafast devem consultar a base local.
- Se o seletor mostrar `Nenhum modelo disponivel`, rode o doctor primeiro.

## Sugestoes iniciais

- A lista `DEFAULT_PROMPT_SUGGESTIONS` agora traz as perguntas oficiais mais uteis da Aquafast.
- Se a interface do Open WebUI mostrar apenas parte das sugestoes na home, isso e uma limitacao visual da propria UI.
- Neste repositorio nao existe o frontend do Open WebUI para aplicar CSS/Tailwind ou grid aqui dentro.
- Alternativa segura: usar a pergunta fixa `Mostrar perguntas disponíveis` para listar todas as perguntas no proprio pipe.

## Persistencia no banco

O Open WebUI persiste configuracoes de sugestoes no `webui.db`.

Se voce trocar o `docker-compose.yml` e o container ja estiver rodando, o valor da variavel no processo pode ficar antigo ate recriar o container.

Quando houver divergencia entre:

- `DEFAULT_PROMPT_SUGGESTIONS` no compose
- `ui.prompt_suggestions` no `webui.db`
- `ui.default_prompt_suggestions` no `webui.db`

use o script de sincronizacao:

```bash
python scripts/sync_openwebui_prompt_suggestions.py
```

Se quiser apenas inspecionar sem gravar:

```bash
python scripts/sync_openwebui_prompt_suggestions.py --dry-run
```

## Resposta fixa no pipe

O pipe `Scanntech Analyst` responde diretamente a estas frases:

- `mostrar perguntas disponíveis`
- `quais perguntas posso fazer`
- `listar sugestões`

Ele devolve a lista completa em texto simples, sem depender da tela inicial do Open WebUI.

## Quando reativar o filtro de modelos

O filtro visual do Open WebUI deve ficar desligado por padrao.

So reative `ENABLE_MODEL_FILTER` e `MODEL_FILTER_LIST` depois que:

- `python scripts/doctor_openwebui.py` reportar `OK` para:
  - container `aquafast_webui`
  - function ativa
  - function sem BOM
  - Scanntech API `/health`
  - Ollama `/api/tags`

Depois de reativar o filtro, reinicie o Open WebUI:

```bash
docker compose up -d open-webui
```

## Quando o doctor apontar falha

- `Function content starts with BOM`
  - Regrave com `python scripts/push_scanntech_function_to_db.py`.
- `Function is inactive`
  - Regrave com `python scripts/push_scanntech_function_to_db.py`.
- `Scanntech API /health` falhando
  - Veja o container `aquafast_scanntech_api`.
- `Ollama /api/tags` falhando
  - Veja o container `aquafast_ollama`.
- `Open WebUI logs` com `Import error`, `U+FEFF` ou `function load error`
  - O pipe ainda nao carregou corretamente.

## Comandos uteis

```bash
docker logs aquafast_webui --since 1h --tail 300
docker logs aquafast_scanntech_api --since 1h --tail 200
docker logs aquafast_ollama --since 1h --tail 200
```

## Arquivos relacionados

- [openwebui_scanntech_function.py](./openwebui_scanntech_function.py)
- [scripts/push_scanntech_function_to_db.py](./scripts/push_scanntech_function_to_db.py)
- [scripts/doctor_openwebui.py](./scripts/doctor_openwebui.py)
- [docker-compose.yml](./docker-compose.yml)
- [.env.example](./.env.example)
