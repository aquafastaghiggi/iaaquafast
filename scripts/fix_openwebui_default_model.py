#!/usr/bin/env python3
"""
Script para encontrar e corrigir o ID da função Scanntech Analyst no docker-compose.yml

Uso:
    python scripts/fix_openwebui_default_model.py [--auto-fix]

Opções:
    --auto-fix   Corrige o docker-compose.yml automaticamente após encontrar o ID
"""

import json
import re
import sys
import subprocess
from pathlib import Path
from typing import Optional


def get_openwebui_functions() -> Optional[dict]:
    """Extrai lista de funções do Open WebUI via API."""
    try:
        result = subprocess.run(
            ["curl", "-s", "http://localhost:3000/api/v1/functions"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (json.JSONDecodeError, subprocess.TimeoutExpired, FileNotFoundError):
        return None


def find_scanntech_analyst_id(functions: Optional[dict]) -> Optional[str]:
    """Procura pelo ID da função Scanntech Analyst."""
    if not functions:
        return None

    # Tenta como lista
    if isinstance(functions, list):
        for func in functions:
            if isinstance(func, dict):
                name = func.get("name", "").lower()
                if "scanntech" in name or "analyst" in name:
                    return func.get("id")

    # Tenta como dicionário
    if isinstance(functions, dict):
        for key, func in functions.items():
            if isinstance(func, dict):
                name = func.get("name", "").lower()
                if "scanntech" in name or "analyst" in name:
                    return func.get("id") or key

    return None


def get_docker_compose_path() -> Path:
    """Encontra o arquivo docker-compose.yml."""
    workspace = Path(__file__).parent.parent
    docker_file = workspace / "docker-compose.yml"
    if docker_file.exists():
        return docker_file
    raise FileNotFoundError(f"docker-compose.yml não encontrado em {workspace}")


def read_docker_compose(path: Path) -> str:
    """Lê o conteúdo do docker-compose.yml."""
    return path.read_text(encoding="utf-8")


def extract_function_id_from_docker(content: str) -> Optional[str]:
    """Extrai o ID da função atual do docker-compose.yml."""
    match = re.search(
        r"DEFAULT_MODELS=([a-f0-9\-]+)\.scanntech_analyst",
        content,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def update_docker_compose(path: Path, new_id: str) -> bool:
    """Atualiza o docker-compose.yml com o novo ID."""
    content = path.read_text(encoding="utf-8")

    # Padrão para DEFAULT_MODELS
    old_pattern = r"DEFAULT_MODELS=[a-f0-9\-]*\.scanntech_analyst"
    new_value = f"DEFAULT_MODELS={new_id}.scanntech_analyst"
    content_new = re.sub(old_pattern, new_value, content, flags=re.IGNORECASE)

    # Padrão para DEFAULT_PINNED_MODELS
    old_pattern = r"DEFAULT_PINNED_MODELS=[a-f0-9\-]*\.scanntech_analyst"
    new_value = f"DEFAULT_PINNED_MODELS={new_id}.scanntech_analyst"
    content_new = re.sub(old_pattern, new_value, content_new, flags=re.IGNORECASE)

    if content_new != content:
        path.write_text(content_new, encoding="utf-8")
        return True
    return False


def main():
    """Função principal."""
    auto_fix = "--auto-fix" in sys.argv

    print("=" * 70)
    print("🔍 Buscando ID da função Scanntech Analyst no Open WebUI...")
    print("=" * 70)

    # Tentar encontrar via API
    functions = get_openwebui_functions()
    found_id = find_scanntech_analyst_id(functions) if functions else None

    if found_id:
        print(f"\n✅ ID encontrado: {found_id}")
    else:
        print("\n❌ Não consegui encontrar o ID via API.")
        print("   Certifique-se de que:")
        print("   - O container Open WebUI está rodando (docker ps)")
        print("   - A URL http://localhost:3000 está acessível")
        print("\n   Alternativa: copiar o ID manualmente em:")
        print("   1. http://localhost:3000 → Settings → Functions")
        print("   2. Procure 'Scanntech Analyst' e copie o ID")
        return 1

    # Obter caminho do docker-compose
    try:
        docker_file = get_docker_compose_path()
        print(f"\n📄 Arquivo: {docker_file}")
    except FileNotFoundError as e:
        print(f"\n❌ {e}")
        return 1

    # Verificar ID atual
    content = read_docker_compose(docker_file)
    current_id = extract_function_id_from_docker(content)

    print(f"\n📋 ID atual no docker-compose: {current_id or 'nenhum (ou inválido)'}")
    print(f"📋 ID encontrado no Open WebUI: {found_id}")

    if current_id == found_id:
        print("\n✅ IDs batem! Nenhuma correção necessária.")
        return 0

    # Aplicar correção
    print("\n" + "=" * 70)
    if auto_fix:
        print("🔧 Aplicando correção automática...")
    else:
        print("⚠️  IDs NÃO batem. Para corrigir automaticamente, rode:")
        print(f"   python {Path(__file__).name} --auto-fix")
        print("\n   Ou edite manualmente no docker-compose.yml:")
        print(f"   DEFAULT_MODELS={found_id}.scanntech_analyst")
        print(f"   DEFAULT_PINNED_MODELS={found_id}.scanntech_analyst")
        return 1

    if update_docker_compose(docker_file, found_id):
        print(f"\n✅ docker-compose.yml atualizado com sucesso!")
        print(f"   DEFAULT_MODELS={found_id}.scanntech_analyst")
        print(f"   DEFAULT_PINNED_MODELS={found_id}.scanntech_analyst")

        print("\n🚀 Próximas ações:")
        print("   1. docker compose down open-webui")
        print("   2. docker compose up -d open-webui")
        print("   3. Aguardar ~30 segundos")
        print("   4. Acessar http://localhost:3000 e verificar novo chat")
        return 0
    else:
        print("\n❌ Nenhuma mudança foi necessária ou ocorreu erro.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
