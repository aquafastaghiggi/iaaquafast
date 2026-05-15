param(
    [string]$ContainerName = "aquafast_webui"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$functionFile = Join-Path $repoRoot "openwebui_scanntech_function.py"
$semanticsFile = Join-Path $repoRoot "aquafast_semantics.py"
$composeFile = Join-Path $repoRoot "docker-compose.yml"

if (-not (Test-Path $functionFile)) {
    throw "Nao encontrei $functionFile"
}

if (-not (Test-Path $semanticsFile)) {
    throw "Nao encontrei $semanticsFile"
}

if (-not (Test-Path $composeFile)) {
    throw "Nao encontrei $composeFile"
}

docker cp $functionFile "${ContainerName}:/tmp/scanntech_function.py" | Out-Null
docker cp $semanticsFile "${ContainerName}:/tmp/aquafast_semantics.py" | Out-Null

$python = @"
import json
import sqlite3
import time
from pathlib import Path
import sys

sys.path.insert(0, '/tmp')

from aquafast_semantics import list_official_questions

db_path = Path('/app/backend/data/webui.db')
func_path = Path('/tmp/scanntech_function.py')

content = func_path.read_text(encoding='utf-8')

con = sqlite3.connect(str(db_path))
cur = con.cursor()

cur.execute(
    \"UPDATE function SET content = ?, is_active = 1, is_global = 1, updated_at = ? WHERE name = ?\",
    (content, int(time.time()), 'Scanntech Analyst'),
)

official_questions = list_official_questions()
prompt_suggestions = [
    {
        'title': item.get('title_lines') or [item['title']],
        'content': item['examples'].split(' | ')[0] if item.get('examples') else item['title'],
    }
    for item in official_questions
]

cur.execute(\"SELECT data FROM config ORDER BY id DESC LIMIT 1\")
config_row = cur.fetchone()
config_data = {}
if config_row and config_row[0]:
    try:
        config_data = json.loads(config_row[0])
    except Exception:
        config_data = {}
config_data.setdefault('ui', {})
config_data['ui']['default_models'] = ['ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc.scanntech_analyst']
config_data['ui']['default_pinned_models'] = ['ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc.scanntech_analyst']
config_data['ui']['default_model'] = 'ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc.scanntech_analyst'
config_data['ui']['selected_model'] = 'ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc.scanntech_analyst'
config_data['ui']['prompt_suggestions'] = prompt_suggestions
if config_row:
    cur.execute(\"UPDATE config SET data = ?, updated_at = CURRENT_TIMESTAMP WHERE id = (SELECT id FROM config ORDER BY id DESC LIMIT 1)\", (json.dumps(config_data, ensure_ascii=False),))
else:
    cur.execute(\"INSERT INTO config (data, version) VALUES (?, ?)\", (json.dumps(config_data, ensure_ascii=False), 0))

cur.execute(\"SELECT id, settings FROM user\")
user_rows = cur.fetchall()
for user_id, settings_json in user_rows:
    settings_data = {}
    if settings_json:
        try:
            settings_data = json.loads(settings_json)
        except Exception:
            settings_data = {}
    settings_data.setdefault('ui', {})
    settings_data['ui']['models'] = ['ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc.scanntech_analyst']
    settings_data['ui']['pinnedModels'] = ['ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc.scanntech_analyst']
    settings_data['ui']['selectedModel'] = 'ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc.scanntech_analyst'
    settings_data['ui']['defaultModel'] = 'ceb51b31-8ecd-401c-b0cb-677a7f0d8ebc.scanntech_analyst'
    cur.execute(
        \"UPDATE user SET settings = ?, updated_at = ? WHERE id = ?\",
        (json.dumps(settings_data, ensure_ascii=False), int(time.time()), user_id),
    )

def normalize_chat_models(payload):
    payload['models'] = ['Scanntech Analyst']
    payload['pinnedModels'] = ['Scanntech Analyst']
    history = payload.get('history', {})
    messages = history.get('messages', {})
    for message in messages.values():
        if isinstance(message, dict):
            if message.get('model') == 'qwen2.5:latest':
                message['model'] = 'Scanntech Analyst'
            if message.get('models') == ['qwen2.5:latest']:
                message['models'] = ['Scanntech Analyst']
            if message.get('pinnedModels') == ['qwen2.5:latest']:
                message['pinnedModels'] = ['Scanntech Analyst']
    for message in payload.get('messages', []):
        if isinstance(message, dict):
            if message.get('model') == 'qwen2.5:latest':
                message['model'] = 'Scanntech Analyst'
            if message.get('models') == ['qwen2.5:latest']:
                message['models'] = ['Scanntech Analyst']
            if message.get('pinnedModels') == ['qwen2.5:latest']:
                message['pinnedModels'] = ['Scanntech Analyst']
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
