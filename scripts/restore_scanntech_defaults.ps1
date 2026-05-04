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

cur.execute(
    \"SELECT id, chat FROM chat WHERE chat IS NOT NULL ORDER BY updated_at DESC LIMIT 1\"
)
row = cur.fetchone()
if row:
    chat_id, chat_json = row
    payload = json.loads(chat_json)
    payload['models'] = ['Scanntech Analyst']
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
