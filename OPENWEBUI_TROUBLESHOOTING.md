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
