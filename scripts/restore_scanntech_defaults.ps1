param(
    [string]$ContainerName = "aquafast_webui"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$functionFile = Join-Path $repoRoot "openwebui_scanntech_function.py"
$composeFile = Join-Path $repoRoot "docker-compose.yml"

if (-not (Test-Path $functionFile)) {
    throw "Nao encontrei $functionFile"
}

if (-not (Test-Path $composeFile)) {
    throw "Nao encontrei $composeFile"
}

docker cp $functionFile "${ContainerName}:/tmp/scanntech_function.py" | Out-Null

$python = @"
import json
import sqlite3
import time
from pathlib import Path

db_path = Path('/app/backend/data/webui.db')
func_path = Path('/tmp/scanntech_function.py')

content = func_path.read_text(encoding='utf-8')

con = sqlite3.connect(str(db_path))
cur = con.cursor()

cur.execute(
    \"UPDATE function SET content = ?, is_active = 1, is_global = 1, updated_at = ? WHERE name = ?\",
    (content, int(time.time()), 'Scanntech Analyst'),
)

def normalize_chat_models(payload):
    payload['models'] = ['Scanntech Analyst']
    history = payload.get('history', {})
    messages = history.get('messages', {})
    for message in messages.values():
        if isinstance(message, dict):
            if message.get('model') == 'qwen2.5:latest':
                message['model'] = 'Scanntech Analyst'
            if message.get('models') == ['qwen2.5:latest']:
                message['models'] = ['Scanntech Analyst']
    for message in payload.get('messages', []):
        if isinstance(message, dict):
            if message.get('model') == 'qwen2.5:latest':
                message['model'] = 'Scanntech Analyst'
            if message.get('models') == ['qwen2.5:latest']:
                message['models'] = ['Scanntech Analyst']
    return payload

cur.execute(\"SELECT id, chat FROM chat WHERE chat IS NOT NULL\")
rows = cur.fetchall()
for chat_id, chat_json in rows:
    payload = json.loads(chat_json)
    payload = normalize_chat_models(payload)
    cur.execute(
        \"UPDATE chat SET chat = ?, updated_at = ? WHERE id = ?\",
        (json.dumps(payload, ensure_ascii=False), int(time.time()), chat_id),
    )

con.commit()
con.close()
print('Scanntech Analyst restaurado.')
"@

Push-Location $repoRoot
try {
    docker exec -i $ContainerName python -c $python | Out-Null
    docker compose -f $composeFile restart open-webui | Out-Null
}
finally {
    Pop-Location
}

Write-Host "Scanntech Analyst definido como padrao no Open WebUI."
