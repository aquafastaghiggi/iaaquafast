"""
title: Scanntech Analyst
author: Codex
version: 3.0.15
requirements: httpx
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, "/app/backend")

import httpx
from pydantic import BaseModel, Field

try:
    from aquafast_semantics import (
        OFFICIAL_QUESTION_ROUTES,
        normalize_business_question,
        repair_mojibake,
        match_route,
        resolve_official_route,
        safe_output_text,
    )
except Exception:
    OFFICIAL_QUESTION_ROUTES: tuple[Any, ...] = tuple()

    def safe_output_text(value: Any) -> str:
        if value is None:
            return ""
        text = str(value)
        if not text:
            return ""
        stripped = text.strip()
        if not stripped or stripped.lower() == "none":
            return ""
        repaired = text
        for _ in range(3):
            next_text = repaired
            for encoding in ("latin1", "cp1252"):
                try:
                    next_text = next_text.encode(encoding).decode("utf-8")
                    break
                except Exception:
                    pass
            for bad, good in (
                ("ÃƒÂª", "ê"),
                ("ÃƒÂ³", "ó"),
                ("ÃƒÂ­", "í"),
                ("ÃƒÂ§", "ç"),
                ("ÃƒÂ£", "ã"),
                ("ÃƒÂ¡", "á"),
                ("ÃƒÂ©", "é"),
                ("Ãª", "ê"),
                ("Ã³", "ó"),
                ("Ã­", "í"),
                ("Ã§", "ç"),
                ("Ã£", "ã"),
                ("Ã¡", "á"),
                ("Ã©", "é"),
                ("Âº", "º"),
                ("Âª", "ª"),
                ("Â·", "·"),
            ):
                next_text = next_text.replace(bad, good)
            if next_text == repaired:
                break
            repaired = next_text
        return repaired

    def safe_output_text(text: Any) -> str:
        if text is None:
            return ''
        try:
            return str(text)
        except Exception:
            return ''

    def normalize_business_question(text: str) -> str:
        q = safe_output_text(text)
        q = unicodedata.normalize("NFKD", q)
        q = q.encode("ascii", "ignore").decode("ascii")
        q = " ".join(q.strip().lower().split())
        q = q.replace("_", " ")
        replacements = (
            (r"\bpontos de venda\b", "lojas"),
            (r"\bpdv?s?\b", "lojas"),
            (r"\bpresente hoje\b", "hoje"),
            (r"\bpresenca hoje\b", "hoje"),
            (r"\bconcorrente principal\b", "maior concorrente"),
            (r"\bprincipal concorrente\b", "maior concorrente"),
            (r"\bteriam mais potencial\b", "potencial de venda"),
            (r"\bproduto[s]? com potencial\b", "potencial de venda"),
            (r"\bo que vender\b", "potencial de venda"),
            (r"\bmix\b", "categoria"),
            (r"\bportifolio\b", "portfolio"),
        )
        for pattern, replacement in replacements:
            q = re.sub(pattern, replacement, q)
        return " ".join(q.split())

    def match_route(question: str) -> str | None:
        return None

    def resolve_official_route(question: str):
        return None


def safe_text(text: Any) -> str:
    value = "" if text is None else str(text)
    if not value:
        return ""
    if "Ã" not in value and "Â" not in value:
        return value
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except Exception:
        return value
    return repaired or value


AVAILABLE_QUESTION_SUGGESTIONS: tuple[dict[str, str], ...] = (
    {"title": "Insights de Vendas", "content": "Quais foram os produtos mais vendidos no último mês?"},
    {"title": "Insights de Vendas", "content": "Mostre a evolução de vendas da Aquafast por mês."},
    {"title": "Insights de Vendas", "content": "Quais clientes mais compraram Aquafast?"},
    {"title": "Análise de Concorrência", "content": "Compare a Aquafast com os principais concorrentes."},
    {"title": "Mapa de Oportunidades", "content": "Quais produtos têm maior oportunidade de crescimento?"},
    {"title": "Insights de Vendas", "content": "Quais estados têm melhor desempenho de vendas?"},
    {"title": "Auditoria de Dados", "content": "Existem produtos sem subgrupo ou com dados inconsistentes?"},
    {"title": "Performance de Produtos", "content": "Mostre um resumo executivo da performance comercial."},
)

PRIMARY_QUESTION_PROMPTS: tuple[str, ...] = (
    "Insights de Vendas",
    "Performance de Produtos",
    "Análise de Concorrência",
    "Mapa de Oportunidades",
    "Auditoria de Dados",
    "Quais foram os produtos mais vendidos no último mês?",
    "Mostre a evolução de vendas da Aquafast por mês.",
    "Quais clientes mais compraram Aquafast?",
    "Compare a Aquafast com os principais concorrentes.",
    "Quais produtos têm maior oportunidade de crescimento?",
)


AGENT_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "title": "Insights de Vendas",
        "label": "Insights de Vendas",
        "description": "Análise de vendas, faturamento, evolução mensal e desempenho por cliente/UF.",
        "aliases": ("insights vendas", "vendas aquafast", "performance vendas", "ranking lojas", "vendas"),
        "questions": (
            "Quais foram os produtos mais vendidos no último mês?",
            "Mostre a evolução de vendas da Aquafast por mês.",
            "Quais clientes mais compraram Aquafast?",
            "Quais estados têm melhor desempenho de vendas?",
        ),
    },
    {
        "title": "Performance de Produtos",
        "label": "Performance de Produtos",
        "description": "Ranking de SKU, categorias, volume em caixas e leitura executiva de portfólio.",
        "aliases": ("performance produtos", "produtos aquafast", "ranking produtos", "portfolio", "produto", "sku"),
        "questions": (
            "Quais foram os produtos mais vendidos no último mês?",
            "Mostre um resumo executivo da performance comercial.",
        ),
    },
    {
        "title": "Análise de Concorrência",
        "label": "Análise de Concorrência",
        "description": "Comparação com concorrentes, participação de mercado e posicionamento comercial.",
        "aliases": ("concorrencia", "market share", "competidores", "posicionamento", "share", "mercado"),
        "questions": (
            "Compare a Aquafast com os principais concorrentes.",
        ),
    },
    {
        "title": "Mapa de Oportunidades",
        "label": "Mapa de Oportunidades",
        "description": "Identificação de potencial de crescimento, lacunas de cobertura e prioridade de atuação.",
        "aliases": ("oportunidades", "potencial venda", "gaps cobertura", "crescimento", "oportunidade", "gap"),
        "questions": (
            "Quais produtos têm maior oportunidade de crescimento?",
        ),
    },
    {
        "title": "Auditoria de Dados",
        "label": "Auditoria de Dados",
        "description": "Validação de integridade da base, inconsistências e problemas de classificação.",
        "aliases": (
            "auditoria dados",
            "qualidade dados",
            "integridade",
            "padronizacao",
            "auditoria",
            "inconsistencia",
            "sem subgrupo",
            "diagnostico",
        ),
        "questions": (
            "Existem produtos sem subgrupo ou com dados inconsistentes?",
        ),
    },
)

GROUP_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Insights de Vendas": (
        "venda", "vendas", "sell-out", "faturamento", "clientes", "estado", "uf", "mes", "evolucao", "crescimento", "queda",
    ),
    "Performance de Produtos": (
        "produto", "sku", "ranking", "categoria", "subgrupo", "mix", "embalagem", "volume", "caixas",
    ),
    "Análise de Concorrência": (
        "concorrencia", "concorrente", "share", "participacao", "mercado", "comparacao", "marcas", "market share",
    ),
    "Mapa de Oportunidades": (
        "oportunidade", "potencial", "expansao", "crescer", "priorizar", "lacuna", "gap", "onde atuar",
    ),
    "Auditoria de Dados": (
        "auditoria", "inconsistencia", "qualidade", "sem subgrupo", "erro", "divergencia", "historico", "diagnostico",
    ),
}

OFF_TOPIC_SIGNALS: tuple[str, ...] = (
    "capital",
    "presidente",
    "historia",
    "geografia",
    "receita",
    "culinaria",
    "esporte",
    "clima",
    "tempo",
    "temperatura",
    "traducao",
    "significado",
    "definicao",
    "quem inventou",
    "quando nasceu",
    "filme",
    "musica",
    "livro",
)

ROUTE_TO_LABEL: dict[str, str] = {
    "lojas_hoje": "Lojas na base",
    "pontos_venda": "Pontos de venda",
    "top_clientes": "Top clientes",
    "top_produtos": "Top produtos",
    "receita_total": "Faturamento total",
    "ticket_medio": "Ticket medio",
    "vendas_mes": "Vendas por mes",
    "vendas_estado": "Vendas por estado",
    "vendas_por_cidade": "Presença por cidade",
    "ranking_redes": "Ranking de redes",
    "total_produtos": "Total de produtos",
    "resumo_geral": "Resumo geral",
    "market_share": "Market share",
    "maior_concorrente": "Maior concorrente",
    "maior_estado": "Maior estado",
    "lojas_90d": "Lojas ativas 90 dias",
    "potencial_venda": "Potencial de venda",
    "lojas_com_concorrente_sem_aquafast": "Oportunidades",
}

INTENT_ROUTER_SYSTEM_PROMPT = """
Você é um roteador de intenções para um sistema de dados de varejo.
Sua única função é identificar qual tipo de análise o usuário quer.

Responda APENAS com uma das categorias abaixo, sem nenhum texto adicional:
- top_produtos
- top_clientes
- ranking_redes
- receita_total
- lojas_hoje
- market_share
- concorrentes_por_categoria
- oportunidades
- evolucao_mensal
- resumo_geral
- fora_de_contexto

Exemplos:
- "quais produtos mais vendem" -> top_produtos
- "como estão as vendas" -> evolucao_mensal
- "aquafast vs concorrentes" -> concorrentes_por_categoria

Não explique. Não invente dados. Não use conhecimento próprio.
Se a pergunta não for sobre dados de varejo, responda: fora_de_contexto
""".strip()

FORMAT_WITH_LLM_SYSTEM_PROMPT = "Você é um analista de dados de varejo."

FORMAT_WITH_LLM_USER_PROMPT_TEMPLATE = """
Você é um analista de dados de varejo. Responda a pergunta do usuário
usando EXCLUSIVAMENTE os dados abaixo. Não adicione informações externas.
Não invente números. Se os dados não responderem a pergunta, diga
"Os dados disponíveis não cobrem essa análise."

Pergunta: {question}

Dados reais da base:
{data}

Responda de forma clara e executiva, em português.
""".strip()


class Pipe:
    # Invariante do projeto:
    # - O nome visivel e a porta de entrada principal precisam permanecer como "Scanntech Analyst".
    # - O modelo interno continua sendo llama3.2:3b, mas so para raciocinio e resposta.
    class Valves(BaseModel):
        API_BASE_URL: str = Field(
            default="http://scanntech-api:8000",
            description="Base URL da API local de analise",
        )
        OLLAMA_BASE_URL: str = Field(
            default="http://ollama:11434",
            description="Base URL do Ollama local",
        )
        CHAT_MODEL: str = Field(
            default="llama3.2:3b",
            description="Modelo usado para conversa livre e geracao de SQL",
        )
        TIMEOUT_SECONDS: float = Field(
            default=180.0,
            description="Timeout HTTP da Scanntech API (consultas pesadas em CPU)",
        )
        OLLAMA_TIMEOUT_SECONDS: float = Field(
            default=240.0,
            description="Timeout das chamadas ao Ollama (geracao/correcao de SQL e chat)",
        )
        LEGACY_ASK_TIMEOUT_SECONDS: float = Field(
            default=45.0,
            description="Timeout so para POST /ask (consultas pre-mapeadas, sem LLM)",
        )
        OLLAMA_SQL_TIMEOUT_SECONDS: float = Field(
            default=120.0,
            description="Timeout para gerar/corrigir SQL no Ollama (menor que o chat para nao ficar minutos parado)",
        )
        SQL_CONTEXT_MESSAGES: int = Field(
            default=4,
            description="Quantas mensagens recentes entram no prompt de SQL",
        )
        SUMMARY_ENABLED: bool = Field(
            default=False,
            description="Reservado: o resumo analitico e deterministico (tabela + metricas). LLM nao reescreve numeros.",
        )
        MAX_MODEL_TOKENS: int = Field(
            default=220,
            description="Limite de tokens no modo chat (respostas curtas)",
        )
        SQL_MAX_TOKENS: int = Field(
            default=900,
            description="Limite de tokens para gerar/corrigir SQL (220 truncava consultas longas)",
        )
        SQL_SAFETY_ROW_CAP: int = Field(
            default=2000,
            description="Se o SQL nao tiver LIMIT final, envolve em subselect com este teto (alinha com a API /query)",
        )
        SCHEMA_CACHE_TTL_SECONDS: int = Field(
            default=600,
            description="TTL do cache do schema (segundos)",
        )
        MAX_MESSAGES: int = Field(
            default=12,
            description="Quantidade de mensagens recentes para contexto",
        )

    def __init__(self):
        self.valves = self.Valves()
        self._schema_cache: dict[str, Any] | None = None
        self._schema_cache_ts: float = 0.0

    def pipes(self):
        return [{"id": "scanntech_analyst", "name": "Scanntech Analyst"}]

    def _normalize_text(self, text: str) -> str:
        text = safe_output_text(text)
        normalized = unicodedata.normalize("NFKD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        return " ".join(ascii_text.lower().split())

    def _content_to_text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return safe_output_text(content)
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")).strip())
            return "\n".join(part for part in parts if part).strip()
        return str(content).strip()

    def _extract_question(self, body: dict) -> str:
        messages = body.get("messages", [])
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            content = self._content_to_text(message.get("content", ""))
            if content:
                return content
        return self._content_to_text(body.get("prompt", ""))

    def _combined_user_text(self, body: dict) -> str:
        messages = body.get("messages", [])
        parts = []
        for message in messages:
            if message.get("role") != "user":
                continue
            content = self._content_to_text(message.get("content", ""))
            if content:
                parts.append(content)
        return "\n".join(parts).strip()

    def _is_chart_request(self, question: str) -> bool:
        q = self._normalize_text(question)
        return any(term in q for term in ["grafico", "chart", "plot", "visualizar em grafico"])

    def _is_access_question(self, question: str) -> bool:
        q = self._normalize_text(question)
        access_terms = [
            "tem acesso",
            "acesso a base",
            "acesso a dados",
            "acessar a base",
            "consegue acessar",
            "voce tem acesso",
            "base de dados",
            "dados da aquafast",
            "base da aquafast",
        ]
        return self._contains_any(q, access_terms)

    def _answer_access_question(self) -> str:
        return safe_output_text(
            "Tenho acesso ao banco local do projeto Aquafast conectado ao DuckDB e Ã  API interna da stack. "
            "Consigo consultar os dados ingeridos no ambiente local, gerar anÃ¡lises, grÃ¡ficos e exportaÃ§Ãµes. "
            "NÃ£o tenho acesso a bases externas ou confidenciais fora deste ambiente."
        )
    def _is_excel_request(self, question: str) -> bool:
        q = self._normalize_text(question)
        return any(
            term in q
            for term in [
                "excel",
                "xlsx",
                "planilha",
                "exportar",
                "exporta",
                "gerar arquivo",
                "baixar",
                "download",
            ]
        )

    def _contains_any(self, text: str, terms: list[str]) -> bool:
        return any(term in text for term in terms)

    def _safe_text(self, value: Any, default: str = "") -> str:
        if value is None:
            return default
        text = safe_output_text(value) if isinstance(value, str) else str(value)
        if text is None:
            return default
        cleaned = str(text).strip()
        if not cleaned or cleaned.lower() == "none":
            return default
        return cleaned

    def _route_for_category(self, category: str):
        normalized = self._normalize_text(category)
        if not normalized:
            return None
        category_map = {
            "top_produtos": "top_produtos",
            "top_clientes": "top_clientes",
            "ranking_redes": "ranking_redes",
            "receita_total": "receita_total",
            "lojas_hoje": "lojas_hoje",
            "market_share": "market_share",
            "concorrentes_por_categoria": "concorrentes_por_categoria",
            "oportunidades": "lojas_com_concorrente_sem_aquafast",
            "evolucao_mensal": "vendas_mes",
            "resumo_geral": "resumo_geral",
        }
        route_id = category_map.get(normalized, normalized)
        for route in OFFICIAL_QUESTION_ROUTES:
            if route.id == route_id:
                return route
        return None

    def _route_for_question(self, question: str, category: str | None = None):
        route = resolve_official_route(question)
        if route is not None:
            return route
        route_id = match_route(question)
        if route_id:
            for route in OFFICIAL_QUESTION_ROUTES:
                if route.id == route_id:
                    return route
        if category:
            route = self._route_for_category(category)
            if route is not None:
                return route
        return None

    def _inline_prompt(self, value: Any, default: str = "") -> str:
        # Open WebUI nao oferece uma acao de clique do pipe que execute a pergunta na mesma conversa.
        # Por isso renderizamos opcoes copiaveis como inline code spans em vez de links de navegacao.
        text = safe_text(value)
        cleaned = text or default
        if not cleaned:
            return default
        escaped = cleaned.replace("`", "\\`")
        return f"`{escaped}`"

    def _selected_questions(self, limit: int | None = None) -> list[dict[str, str]]:
        items = [
            {
                "title": safe_text(item.get("title", "")),
                "content": safe_text(item.get("content", "")),
            }
            for item in AVAILABLE_QUESTION_SUGGESTIONS
        ]
        if limit is None:
            return items

        normalized_items = [
            (self._normalize_text(item["title"]), self._normalize_text(item["content"]), item)
            for item in items
        ]
        selected: list[dict[str, str]] = []
        seen: set[str] = set()

        for prompt in PRIMARY_QUESTION_PROMPTS:
            normalized_prompt = self._normalize_text(prompt)
            for title_norm, content_norm, item in normalized_items:
                key = self._normalize_text(item["content"] or item["title"])
                if normalized_prompt in {title_norm, content_norm, key} and key not in seen:
                    selected.append(item)
                    seen.add(key)
                    break
            if len(selected) >= limit:
                return selected[:limit]

        for item in items:
            key = self._normalize_text(item["content"] or item["title"])
            if key in seen:
                continue
            selected.append(item)
            seen.add(key)
            if len(selected) >= limit:
                break

        return selected[:limit]

    def _format_questions_block(self, limit: int | None = None) -> str:
        selected = self._selected_questions(limit=limit)
        lines = [safe_text("Perguntas disponíveis:"), ""]
        for idx, item in enumerate(selected, start=1):
            title = safe_text(item.get("title", ""))
            content = safe_text(item.get("content", "")) or title
            if limit is None:
                lines.append(f"{idx}. {self._inline_prompt(title)}")
                if content and content != title:
                    lines.append(f"   {self._inline_prompt(content)}")
            else:
                lines.append(f"- {self._inline_prompt(content)}")
        lines.append("")
        lines.append(safe_text("Digite uma opção acima ou use `Mostrar perguntas disponíveis`."))
        return "\n".join(lines).strip()

    def _is_available_questions_request(self, question: str) -> bool:
        q = self._normalize_text(question)
        return self._contains_any(
            q,
            [
                "mostrar perguntas disponiveis",
                "quais perguntas posso fazer",
                "listar sugestoes",
                "mostrar sugestoes",
                "perguntas disponiveis",
                "sugestoes disponiveis",
            ],
        )

    def _answer_available_questions(self) -> str:
        lines = ["## Perguntas disponíveis", ""]
        for idx, item in enumerate(AVAILABLE_QUESTION_SUGGESTIONS, start=1):
            title = safe_text(item["title"])
            content = safe_text(item["content"])
            lines.append(f"{idx}. {title}")
            if content and content != title:
                lines.append(f"   {content}")
        lines.append("")
        lines.append(
            "Se quiser ver a lista completa na interface, clique em uma sugestÃ£o ou pergunte: "
            '"Mostrar perguntas disponÃ­veis".'
        )
        return "\n".join(lines).strip()

    def _looks_like_edit_request(self, question: str) -> bool:
        q = self._normalize_text(question)
        edit_verbs = [
            "melhore",
            "revise",
            "reescreva",
            "corrija",
            "ajuste",
            "traduza",
            "resuma",
            "explique",
        ]
        edit_objects = [
            "texto",
            "mensagem",
            "email",
            "e-mail",
            "paragrafo",
            "parÃƒÂ¡grafo",
            "frase",
            "prompt",
            "documento",
            "relatorio",
            "relatÃƒÂ³rio",
        ]
        if any(re.search(rf"\\b{re.escape(v)}\\b", q) for v in edit_verbs) and self._contains_any(q, edit_objects):
            return True
        return False

    def _is_explicit_chat_question(self, question: str) -> bool:
        q = self._normalize_text(question)

        chat_terms = [
            "como funciona",
            "como voce funciona",
            "explique",
            "resuma",
            "escreva",
            "revise",
            "ajude",
            "o que e",
            "quem e voce",
            "qual sua funcao",
            "tem acesso",
            "acesso a base",
            "acessar a base",
            "consegue acessar",
            "voce tem acesso",
            "por que",
            "porque",
            "conserte",
            "traduza",
            "oi",
            "ola",
            "bom dia",
            "boa tarde",
            "boa noite",
            "obrigado",
            "valeu",
        ]

        chat_patterns = [
            r"\b(como funciona|como voce funciona|explique|resuma|escreva|revise|melhore|ajude|traduza)\b",
            r"\b(tem acesso|acesso a base|acessar a base|consegue acessar|voce tem acesso)\b",
            r"\b(quem e voce|qual sua funcao|o que e|por que|porque)\b",
            r"^\s*(oi|ol[áa]|bom dia|boa tarde|boa noite|obrigado|valeu)\s*[!?.,]*\s*$",
        ]

        # evita falso positivo de substring (ex.: "melhores" vs "melhore")
        if self._contains_any(q, chat_terms) and not self._looks_like_data_question(q):
            return True
        if self._looks_like_edit_request(q):
            return True

        if any(re.search(pattern, q) for pattern in chat_patterns):
            # Ex.: "qual sua funcao e me de o top 5 clientes" nao pode cair so no chat livre.
            if self._looks_like_data_question(q):
                return False
            return True

        return False

    def _looks_like_data_question(self, question: str) -> bool | None:
        q = normalize_business_question(question)
        q = self._normalize_text(q)

        if any(signal in q for signal in OFF_TOPIC_SIGNALS):
            return False

        data_terms = [
            "cliente",
            "clientes",
            "produto",
            "produtos",
            "sku",
            "vendido",
            "vendidos",
            "mais vendidos",
            "mais comprados",
            "top",
            "ranking",
            "venda",
            "vendas",
            "receita",
            "faturamento",
            "valor total",
            "ticket medio",
            "ticket",
            "churn",
            "razao social",
            "cnpj",
            "uf",
            "cidade",
            "canal",
            "mes",
            "periodo",
            "quantos",
            "quanto",
            "maior",
            "maiores",
            "menor",
            "menores",
            "melhor",
            "melhores",
            "piores",
            "lista",
            "listar",
            "mostrar",
            "mostre",
            "analise",
            "analisar",
            "consulta",
            "duckdb",
            "sql",
            "loja",
            "lojas",
            "pontos de venda",
            "pdv",
            "ponto de venda",
            "rede",
            "bandeira",
            "mix",
            "categoria",
            "marca",
            "marcas",
            "abc",
            "curva",
            "comparar",
            "comparacao",
            "concorrente",
            "concorrentes",
            "concorrencia",
            "competidor",
            "competidores",
            "municipio",
            "regiao",
            "estoque",
            "participacao",
            "share",
            "market",
            "volume",
            "item",
            "caixa",
            "caixas",
            "portifolio",
            "portfolio",
            "aquafast",
            "litragem",
            "sell-out",
            "evolucao",
            "crescimento",
            "queda",
            "subgrupo",
            "inconsistencia",
            "divergencia",
            "diagnostico",
            "oportunidade",
            "potencial",
            "lacuna",
            "gap",
            "resumo executivo",
            "participacao de mercado",
            "market share",
        ]

        chat_terms = [
            "como funciona",
            "como voce funciona",
            "explique",
            "resuma",
            "escreva",
            "revise",
            "melhore",
            "ajude",
            "o que e",
            "quem e voce",
            "qual sua funcao",
            "tem acesso",
            "acesso a base",
            "acessar a base",
            "consegue acessar",
            "voce tem acesso",
            "por que",
            "porque",
            "conserte",
            "traduza",
        ]

        data_patterns = [
            r"\b(top|ranking|lista|listar|mostrar|mostre|quais|qual|quantos|quanto|maior|maiores|menor|menores|melhor|piores)\b",
            r"\b(cliente|clientes|produto|produtos|sku|venda|vendas|receita|faturamento|ticket|churn)\b",
            r"\b(razao social|cnpj|uf|cidade|canal|mes|m[eÃƒÂª]s|periodo)\b",
            r"\b(mais vendidos|mais comprados|valor total|ticket medio)\b",
        ]
        chat_patterns = [
            r"\b(como funciona|como voce funciona|explique|resuma|escreva|revise|melhore|ajude|traduza)\b",
            r"\b(tem acesso|acesso a base|acessar a base|consegue acessar|voce tem acesso)\b",
            r"\b(quem e voce|qual sua funcao|o que e|por que|porque)\b",
        ]

        if self._contains_any(q, chat_terms) and not self._contains_any(q, data_terms):
            return False

        if self._contains_any(q, data_terms):
            return True

        if any(re.search(pattern, q) for pattern in data_patterns):
            return True

        if any(re.search(pattern, q) for pattern in chat_patterns):
            return False

        return None

    def _find_last_sql(self, body: dict) -> str | None:
        messages = body.get("messages", [])
        for message in reversed(messages[:-1]):
            if message.get("role") != "assistant":
                continue
            content = self._content_to_text(message.get("content", ""))
            match = re.search(r"Consulta executada:\s*`([^`]+)`", content)
            if match:
                return match.group(1).strip().rstrip(";")
        return None

    def _find_last_table(self, body: dict) -> tuple[list[str], list[list[str]]] | None:
        messages = body.get("messages", [])
        for message in reversed(messages[:-1]):
            if message.get("role") != "assistant":
                continue
            content = self._content_to_text(message.get("content", ""))
            # Find the last markdown table in the assistant response.
            lines = [line.rstrip() for line in content.splitlines()]
            for idx in range(len(lines) - 2):
                if not lines[idx].lstrip().startswith("|"):
                    continue
                if idx + 1 >= len(lines) or "| ---" not in lines[idx + 1]:
                    continue
                # capture contiguous table lines
                table_lines = []
                j = idx
                while j < len(lines) and lines[j].lstrip().startswith("|"):
                    table_lines.append(lines[j])
                    j += 1
                if len(table_lines) < 3:
                    continue
                header = [cell.strip() for cell in table_lines[0].strip().strip("|").split("|")]
                rows: list[list[str]] = []
                for row_line in table_lines[2:]:
                    cells = [cell.strip() for cell in row_line.strip().strip("|").split("|")]
                    if len(cells) != len(header):
                        continue
                    rows.append(cells)
                if header and rows:
                    return header, rows
        return None

    def _looks_like_period_question(self, question: str) -> bool:
        q = self._normalize_text(question)
        return any(term in q for term in ["periodo", "periodos", "quando", "mes", "mÃƒÂªs", "data", "primeira", "ultima"])

    def _looks_like_client_question(self, question: str) -> bool:
        q = self._normalize_text(question)
        return any(term in q for term in ["cliente", "clientes", "razao social", "razÃƒÂ£o social", "cnpj"])

    def _looks_like_city_question(self, question: str) -> bool:
        q = self._normalize_text(question)
        return any(term in q for term in ["cidade", "cidades", "municipio", "municÃƒÂ­pio", "uf", "estado"])

    def _looks_like_product_name_question(self, question: str) -> bool:
        q = self._normalize_text(question)
        # _normalize_text remove acentos, entao "descriÃƒÂ§ÃƒÂ£o" vira "descricao"
        return any(term in q for term in ["nome", "descricao", "desc_produto", "descr"])

    def _looks_like_ticket_question(self, question: str) -> bool:
        q = self._normalize_text(question)
        return any(term in q for term in ["ticket", "ticket medio", "preco medio", "valor medio"])

    def _looks_like_last_sale_question(self, question: str) -> bool:
        q = self._normalize_text(question)
        return any(
            term in q
            for term in [
                "ultimo valor",
                "ultima venda",
                "ultimo preco",
                "preco praticado",
                "valor praticado",
            ]
        )

    def _extract_product_codes(self, body: dict, question: str | None = None) -> list[str]:
        """
        Descobre codigos de produto a partir do ultimo resultado (tabela markdown)
        e, se necessario, do texto da pergunta.
        """
        codes: list[str] = []

        last_table = self._find_last_table(body)
        if last_table:
            cols, rows = last_table
            lower = [c.lower() for c in cols]
            pick = None
            for key in ["codigo", "cod_produto", "cod produto", "produto", "sku"]:
                for i, c in enumerate(lower):
                    if key == c or key in c:
                        pick = i
                        break
                if pick is not None:
                    break
            if pick is not None:
                for r in rows:
                    if not r or len(r) <= pick:
                        continue
                    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", str(r[pick]))
                    if cleaned:
                        codes.append(cleaned)

        if not codes and question:
            for match in re.findall(r"\b([A-Za-z]{2,}\d{1,}|sku\d+)\b", str(question), flags=re.IGNORECASE):
                cleaned = re.sub(r"[^A-Za-z0-9_-]", "", str(match))
                if cleaned:
                    codes.append(cleaned)

        seen = set()
        unique: list[str] = []
        for c in codes:
            if c in seen:
                continue
            seen.add(c)
            unique.append(c)
        return unique[:50]

    def _build_product_names_sql(self, products: list[str]) -> str:
        safe = []
        for item in products:
            cleaned = re.sub(r"[^A-Za-z0-9_-]", "", str(item))
            if cleaned:
                safe.append(cleaned)
        if not safe:
            raise ValueError("Nao encontrei codigos de produto para buscar o nome.")
        in_list = ", ".join(f"'{p}'" for p in safe[:50])
        return (
            "SELECT\n"
            "  COD_PRODUTO AS codigo,\n"
            "  MIN(DESC_PRODUTO) AS nome\n"
            "FROM scanntech\n"
            f"WHERE COD_PRODUTO IN ({in_list})\n"
            "  AND NULLIF(TRIM(DESC_PRODUTO), '') IS NOT NULL\n"
            "GROUP BY COD_PRODUTO\n"
            "ORDER BY codigo\n"
        )

    def _build_ticket_sql_for_products(self, products: list[str]) -> str:
        safe = []
        for item in products:
            cleaned = re.sub(r"[^A-Za-z0-9_-]", "", str(item))
            if cleaned:
                safe.append(cleaned)
        if not safe:
            raise ValueError("Nao encontrei codigos de produto para calcular ticket medio.")
        in_list = ", ".join(f"'{p}'" for p in safe[:50])
        return (
            "SELECT\n"
            "  COD_PRODUTO AS codigo,\n"
            "  MIN(DESC_PRODUTO) AS nome,\n"
            "  ROUND(SUM(VALOR_TOTAL) / NULLIF(SUM(QTD), 0), 2) AS ticket_medio_unitario,\n"
            "  ROUND(AVG(VALOR_UNITARIO), 2) AS preco_medio_unitario,\n"
            "  SUM(QTD) AS qtd_total,\n"
            "  ROUND(SUM(VALOR_TOTAL), 2) AS faturamento_total,\n"
            "  MIN(DATA_VENDA) AS primeira_venda,\n"
            "  MAX(DATA_VENDA) AS ultima_venda\n"
            "FROM scanntech\n"
            f"WHERE COD_PRODUTO IN ({in_list})\n"
            "GROUP BY COD_PRODUTO\n"
            "ORDER BY faturamento_total DESC\n"
        )

    def _build_last_sale_sql_for_products(self, products: list[str]) -> str:
        safe = []
        for item in products:
            cleaned = re.sub(r"[^A-Za-z0-9_-]", "", str(item))
            if cleaned:
                safe.append(cleaned)
        if not safe:
            raise ValueError("Nao encontrei codigos de produto para buscar o ultimo valor de venda.")
        in_list = ", ".join(f"'{p}'" for p in safe[:50])
        return (
            "SELECT codigo, nome, data_venda, qtd, valor_unitario, valor_total\n"
            "FROM (\n"
            "  SELECT\n"
            "    COD_PRODUTO AS codigo,\n"
            "    DESC_PRODUTO AS nome,\n"
            "    DATA_VENDA AS data_venda,\n"
            "    QTD AS qtd,\n"
            "    VALOR_UNITARIO AS valor_unitario,\n"
            "    VALOR_TOTAL AS valor_total,\n"
            "    ROW_NUMBER() OVER (PARTITION BY COD_PRODUTO ORDER BY DATA_VENDA DESC) AS rn\n"
            "  FROM scanntech\n"
            f"  WHERE COD_PRODUTO IN ({in_list})\n"
            ")\n"
            "WHERE rn = 1\n"
            "ORDER BY data_venda DESC, codigo\n"
        )

    def _build_clients_sql_for_months(self, months: list[str]) -> str:
        safe = []
        for m in months:
            mm = str(m).strip()
            if re.match(r"^\d{4}-\d{2}$", mm):
                safe.append(mm)
        if not safe:
            raise ValueError("Nao encontrei meses (YYYY-MM) para montar a consulta de clientes.")
        in_list = ", ".join(f"'{m}'" for m in safe[:36])
        return (
            "SELECT\n"
            "  SUBSTR(CAST(DATA_VENDA AS VARCHAR), 1, 7) AS mes,\n"
            "  RAZAO_SOCIAL AS cliente,\n"
            "  COUNT(*) AS total_pedidos,\n"
            "  ROUND(SUM(VALOR_TOTAL), 2) AS receita_total\n"
            "FROM scanntech\n"
            f"WHERE SUBSTR(CAST(DATA_VENDA AS VARCHAR), 1, 7) IN ({in_list})\n"
            "GROUP BY 1, 2\n"
            "ORDER BY receita_total DESC\n"
        )

    def _build_cities_sql_for_clients(self, clients: list[str]) -> str:
        safe = []
        for c in clients:
            cc = str(c).strip()
            if not cc:
                continue
            cc = cc.replace("'", "''")
            safe.append(cc)
        if not safe:
            raise ValueError("Nao encontrei clientes para montar a consulta de cidades.")
        in_list = ", ".join(f"'{c}'" for c in safe[:200])
        return (
            "SELECT DISTINCT\n"
            "  s.RAZAO_SOCIAL AS cliente,\n"
            "  c.PDV_STATE AS uf,\n"
            "  c.PDV_LOCATION AS cidade\n"
            "FROM scanntech s\n"
            "JOIN scanntech_clientes_raw c\n"
            "  ON LOWER(TRIM(s.RAZAO_SOCIAL)) = LOWER(TRIM(COALESCE(c.PDV_SOCIAL_NAME, c.PDV_NAME)))\n"
            f"WHERE s.RAZAO_SOCIAL IN ({in_list})\n"
            "ORDER BY cliente, uf, cidade\n"
        )

    def _build_period_sql_for_products(self, products: list[str]) -> str:
        safe = []
        for item in products:
            cleaned = re.sub(r"[^A-Za-z0-9_-]", "", str(item))
            if cleaned:
                safe.append(cleaned)
        if not safe:
            raise ValueError("Nao encontrei codigos de produto para montar a consulta de periodo.")
        in_list = ", ".join(f"'{p}'" for p in safe[:50])
        return (
            "SELECT\n"
            "  COD_PRODUTO AS codigo,\n"
            "  DESC_PRODUTO AS nome,\n"
            "  MIN(DATA_VENDA) AS primeira_venda,\n"
            "  MAX(DATA_VENDA) AS ultima_venda,\n"
            "  SUM(QTD) AS qtd_total,\n"
            "  ROUND(SUM(VALOR_TOTAL), 2) AS faturamento_total\n"
            "FROM scanntech\n"
            f"WHERE COD_PRODUTO IN ({in_list})\n"
            "GROUP BY COD_PRODUTO, DESC_PRODUTO\n"
            "ORDER BY faturamento_total DESC\n"
        )

    async def _fetch_schema(self) -> dict[str, Any]:
        import time

        now = time.time()
        if self._schema_cache and (now - self._schema_cache_ts) < float(self.valves.SCHEMA_CACHE_TTL_SECONDS):
            return self._schema_cache

        async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
            response = await client.get(f"{self.valves.API_BASE_URL}/schema")
            response.raise_for_status()
            data = response.json()

        self._schema_cache = data
        self._schema_cache_ts = now
        return data

    async def _query_sql(self, sql: str, title: str = "Analise Aquafast") -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{self.valves.API_BASE_URL}/query",
                json={"sql": sql, "title": title},
            )
            response.raise_for_status()
            return response.json()

    async def _export_sql(self, sql: str, title: str = "Exportacao Excel") -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{self.valves.API_BASE_URL}/export",
                json={"sql": sql, "title": title},
            )
            response.raise_for_status()
            return response.json()

    def _extract_sql_block(self, text: str) -> str | None:
        patterns = [
            r"```sql\s*(.*?)```",
            r"```\s*(SELECT.*?)(?:```|$)",
            r"(?is)(select\b.*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            sql = match.group(1).strip()
            sql = sql.split("\n\n")[0].strip()
            sql = sql.rstrip(";")
            if sql:
                return sql
        return None

    def _is_revenue_request(self, question: str) -> bool:
        q = self._normalize_text(question)
        return any(term in q for term in ["receita", "faturamento", "valor total", "valor_total", "receita_total"])

    def _is_product_request(self, question: str) -> bool:
        q = self._normalize_text(question)
        return any(term in q for term in ["produto", "produtos", "item", "itens", "sku", "codigo", "cÃƒÂ³digo"])

    def _sql_looks_like_row_level(self, sql: str) -> bool:
        s = self._normalize_text(sql)
        has_sum = "sum(" in s
        has_group = "group by" in s
        # Row-level query often selects from scanntech and orders by a value column without aggregation.
        return (" from scanntech" in s) and (not has_sum) and (not has_group)

    def _validate_sql_against_question(self, question: str, sql: str) -> str | None:
        q = self._normalize_text(question)
        s = self._normalize_text(sql)
        if self._is_revenue_request(q) and self._is_product_request(q) and self._sql_looks_like_row_level(s):
            return (
                "A pergunta pede ranking agregado por produto (faturamento/receita), "
                "mas o SQL parece estar em nivel de linha. Use SUM(...) e GROUP BY (produto/codigo e descricao)."
            )
        return None

    def _as_float(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).replace(",", "."))
        except Exception:
            return None

    def _pick_metric_column(self, question: str, columns: list[str], rows: list[list[Any]]) -> str | None:
        q = self._normalize_text(question)
        lower = [c.lower() for c in columns]
        prefer_revenue = ["receita_total", "valor_total", "receita", "faturamento"]
        prefer_qty = ["total_vendas", "total_pedidos", "qtd", "quantidade"]
        prefer_ticket = ["ticket_medio", "ticket"]

        preferred = []
        if any(term in q for term in ["concorrente", "concorrentes", "concorrencia", "competidor", "competidores", "market share", "participacao", "share"]):
            preferred = ["market_share_pct", "total_receita", "receita_total", "receita", "valor_total"]
        if any(term in q for term in ["receita", "faturamento", "valor total"]):
            preferred = prefer_revenue
        elif "venda" in q or "vendas" in q:
            # "maiores vendas" tende a significar receita quando existe uma coluna monetaria.
            if any(col in lower for col in ["receita", "receita_total", "valor_total", "faturamento"]):
                preferred = prefer_revenue
            else:
                preferred = prefer_qty
        elif any(term in q for term in ["quantidade", "qtd", "vendidos", "vendas", "pedidos"]):
            preferred = prefer_qty
        elif "ticket" in q:
            preferred = prefer_ticket

        for key in preferred:
            for idx, col in enumerate(lower):
                if key == col or key in col:
                    return columns[idx]

        # fallback: first mostly-numeric column
        for idx, col in enumerate(columns):
            values = [self._as_float(r[idx]) for r in rows[: min(len(rows), 30)]]
            numeric = [v for v in values if v is not None]
            if numeric and (len(numeric) / max(1, len(values))) >= 0.7:
                return col
        return None

    def _pick_label_column(self, columns: list[str], rows: list[list[Any]], metric_col: str | None) -> str | None:
        if not columns or not rows:
            return None
        metric_idx = columns.index(metric_col) if metric_col in columns else -1
        # choose first non-numeric column (or the first column if unsure)
        for idx, col in enumerate(columns):
            if idx == metric_idx:
                continue
            values = [rows[r][idx] for r in range(min(len(rows), 10))]
            numeric = 0
            for v in values:
                if self._as_float(v) is not None:
                    numeric += 1
            if numeric <= 2:
                return col
        return columns[0]

    def _finalize_output(self, text: str) -> str:
        return safe_output_text(text)

    def _format_metric(self, value: float, metric_col: str | None) -> str:
        metric = (metric_col or "").lower()
        if any(k in metric for k in ["receita", "faturamento", "valor_total", "valor total"]):
            return f"R$ {self._format_ptbr_number(value)}"
        if value.is_integer():
            return self._format_ptbr_number(int(value))
        return self._format_ptbr_number(value)

    def _format_ptbr_number(self, value: float | int) -> str:
        if isinstance(value, int):
            return f"{value:,}".replace(",", ".")
        if float(value).is_integer():
            return f"{int(value):,}".replace(",", ".")
        text = f"{float(value):,.2f}"
        return text.replace(",", "X").replace(".", ",").replace("X", ".")

    def _deterministic_summary(self, question: str, columns: list[str], rows: list[list[Any]]) -> str:
        if not rows:
            return "Nenhum resultado encontrado para essa consulta."

        metric_col = self._pick_metric_column(question, columns, rows)
        label_col = self._pick_label_column(columns, rows, metric_col)
        if not metric_col or metric_col not in columns:
            return "Resultado retornado. Veja a tabela abaixo."

        metric_idx = columns.index(metric_col)
        label_idx = columns.index(label_col) if label_col in columns else 0

        if len(rows) == 1:
            row = rows[0]
            metric_value = self._as_float(row[metric_idx])
            if metric_value is not None:
                formatted = self._format_metric(metric_value, metric_col)
                if label_col in columns and label_col != metric_col:
                    label_value = str(row[label_idx])
                    return f"{label_value}: {formatted}"
                return f"{metric_col}: {formatted}"

        points = []
        for row in rows:
            m = self._as_float(row[metric_idx])
            if m is None:
                continue
            points.append((str(row[label_idx]), m))

        if not points:
            return "Resultado retornado. Veja a tabela abaixo."

        points.sort(key=lambda x: x[1], reverse=True)
        total = sum(v for _, v in points)
        top = points[:3]
        lines = []
        lines.append(f"Metricas: `{metric_col}` (ordenado desc).")
        lines.append("Top 3:")
        for i, (name, v) in enumerate(top, start=1):
            lines.append(f"{i}. {name} - {self._format_metric(v, metric_col)}")
        if total > 0 and len(points) >= 3:
            share = sum(v for _, v in top) / total * 100.0
            lines.append(f"Participacao do top 3 no total listado: {share:.1f}%")
        return "\n".join(lines)

    def _source_note_from_result(self, question: str, result: dict[str, Any]) -> str:
        note = str(result.get("source_note", "") or "").strip()
        if note:
            return note

        title = str(result.get("title", "") or "")
        sql = str(result.get("sql", "") or "")
        text = self._normalize_text(" ".join([question, title, sql]))

        if "potencial de venda" in text or "maior potencial" in text:
            return (
                "Fonte: `top_produtos_categoria`. "
                "A consulta usa a presenca em PDVs e o volume em caixas como proxy de potencial de venda."
            )
        if any(
            term in text
            for term in [
                "lojas com concorrente sem aquafast",
            ]
        ):
            return (
                "Fonte: `lojas_com_concorrente_sem_aquafast`. "
                "A consulta usa PDV_ID como chave principal e expÃµe `status_loja` quando a ligaÃƒÂ§ÃƒÂ£o nao existir."
            )
        if any(
            term in text
            for term in [
                "concorrentes por categoria",
                "share aquafast por categoria",
                "top concorrentes por cidade",
                "concorrentes em crescimento 90 dias",
            ]
        ):
            return (
                "Fonte: views deterministicas de concorrencia. "
                "A consulta usa o universo do mercado carregado e separa Aquafast de concorrentes sem chamar LLM."
            )
        if any(term in text for term in ["maior concorrente", "concorrente", "concorrentes", "concorrencia", "competidor", "competidores"]):
            return (
                "Fonte: `ms_mercado_aquafast`. "
                "A consulta compara os fabricantes do mercado da categoria e exclui a Aquafast para apontar concorrentes."
            )
        if any(term in text for term in ["market share", "participacao", "share"]):
            return (
                "Fonte: `ms_mercado_aquafast`. "
                "A consulta mede a participacao de cada fabricante dentro do mercado da categoria."
            )
        if any(term in text for term in ["ponto de venda", "pontos de venda", "loja", "lojas", "pdv"]):
            return (
                "Fonte: `ranking_clientes`. "
                "A consulta conta as lojas/PDVs que aparecem com venda Aquafast no periodo carregado."
            )
        if any(term in text for term in ["produto por categoria", "categoria", "litragem", "mix"]):
            return (
                "Fonte: `top_produtos_categoria`. "
                "A consulta cruza o portfolio Aquafast com caixas para enxergar o mix por categoria, "
                "consolidando pelo mapeamento oficial de `SUBGRUPO_CIGAM`."
            )
        if any(term in text for term in ["vendas por mes", "vendas por mÃƒÂªs", "mensal", "serie mensal", "sÃƒÂ©rie mensal"]):
            return (
                "Fonte: `vendas_por_mes`. "
                "A consulta consolida caixas e receita ao longo do tempo para mostrar tendencia mensal."
            )
        if any(term in text for term in ["vendas por estado", "estado", "uf"]):
            return (
                "Fonte: `vendas_caixas_estado`. "
                "A consulta cruza as vendas Aquafast com a UF para mostrar distribuicao geografica."
            )
        if any(term in text for term in ["top produtos", "ranking produtos", "mais vendidos", "receita por produto", "volume de vendas"]):
            return (
                "Fonte: `ranking_produtos`. "
                "A consulta lista os produtos Aquafast com maior volume em caixas e receita, "
                "consolidando pelo mapeamento oficial de `SUBGRUPO_CIGAM`."
            )
        if any(term in text for term in ["subgrupo cigam", "padronizacao", "padronizaÃ§Ã£o", "nao casam com o portfolio", "nao casam com o portifolio"]):
            return (
                "Fonte: `auditoria_produtos_sem_subgrupo_cigam`. "
                "A consulta lista os produtos Aquafast sem correspondencia no portfolio e sugere `SUBGRUPO_CIGAM` apenas quando a similaridade e transparente."
            )
        if any(term in text for term in ["historico de consultas", "historico consultas", "ultimas consultas", "quais relatorios eu consultei"]):
            return (
                "Fonte: `aquafast_query_history`. "
                "A consulta mostra as 20 consultas deterministicas mais recentes registradas pelo Scanntech Analyst."
            )
        if any(term in text for term in ["clientes", "lojas", "churn", "compra"]):
            return (
                "Fonte: `ranking_clientes`. "
                "A consulta resume as lojas Aquafast por caixas vendidas, receita e recorrencia."
            )
        return "Fonte: consulta local no DuckDB usando as views semanticas da Aquafast."

    def _history_block_from_result(self, question: str, result: dict[str, Any]) -> str:
        report_name = str(result.get("history_report_name", "") or "").strip()
        timestamp = str(result.get("history_timestamp", "") or "").strip()
        if not report_name and not timestamp:
            return ""
        lines = ["Historico desta consulta:", f"- relatorio: {report_name or 'desconhecido'}", f"- pergunta: {question or ''}"]
        if timestamp:
            lines.append(f"- executado em: {timestamp}")
        return "\n".join(lines)

    def _ensure_select_only(self, sql: str) -> str:
        normalized = self._normalize_text(sql)
        if not re.match(r"^(select|with|show|describe)\b", normalized):
            raise ValueError("SQL gerado nao parece ser uma consulta somente leitura.")
        return sql.strip().rstrip(";")

    def _wrap_sql_for_safe_rows(self, sql: str, *, for_export: bool) -> str:
        """
        Evita SELECT sem LIMIT puxando milhoes de linhas (lento no DuckDB e no chat).
        Exportacao Excel usa so o teto da API (EXPORT); nao aplica este wrap.
        """
        if for_export:
            return sql.strip().rstrip(";")
        s = sql.strip().rstrip(";")
        low = s.lower()
        if not (low.startswith("select") or low.startswith("with")):
            return s
        collapsed = re.sub(r"\s+", " ", low).strip()
        if re.search(r"\blimit\s+\d+(\s+offset\s+\d+)?\s*$", collapsed):
            return s
        cap = max(1, int(self.valves.SQL_SAFETY_ROW_CAP))
        return f"SELECT * FROM ({s}) AS _aquafast_safe LIMIT {cap}"

    async def _generate_sql(self, body: dict, question: str, schema_text: str, previous_sql: str | None = None) -> str:
        messages = body.get("messages", [])[-int(self.valves.SQL_CONTEXT_MESSAGES) :]
        user_context = []
        for message in messages:
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = self._content_to_text(message.get("content", ""))
            if not content:
                continue
        # evita mandar tabelas gigantes pro modelo
            if "| --- |" in content or content.count("\n|") > 5:
                continue
            user_context.append(f"{role.upper()}: {content[:600]}")
        context_text = "\n".join(user_context) if user_context else "sem contexto adicional"
        previous_sql_text = f"\n\nSQL anterior (para modificar/continuar se fizer sentido):\n```sql\n{previous_sql}\n```" if previous_sql else ""

        prompt = [
            {
                "role": "system",
                "content": (
                    "Voce e um analista de dados especializado no portfolio Aquafast sobre DuckDB. "
                    "A regra padrao e analisar apenas o mercado Aquafast, usando caixas como base de negocio e evitando a leitura do universo bruto da Scanntech. "
                    "Para perguntas operacionais de resultado, ranking e evolucao, considere apenas os itens Aquafast (is_aquafast = 1). "
                    "Use o universo completo da categoria apenas quando a pergunta for explicitamente de concorrencia, market share ou comparacao de mercado. "
                    "Gere apenas SQL valido e somente leitura. "
                    "Use apenas tabelas, views e colunas existentes no schema fornecido. "
                    "Responda com um unico bloco de codigo Markdown ```sql ... ``` e nada mais. "
                    "Se a pergunta pedir top 20, use LIMIT 20. "
                    "Sempre termine consultas exploratorias com LIMIT (ex.: 200 ou 500) quando nao houver agregacao que ja reduza o resultado. "
                    "Prefira as views ranking_clientes, ranking_produtos, vendas_por_mes, ms_mercado_aquafast, vendas_caixas_estado e top_produtos_categoria quando elas atenderem a pergunta. "
                    "Nao invente colunas. Nao use INSERT, UPDATE, DELETE, DROP ou ALTER."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Schema DuckDB/Aquafast:\n{schema_text}\n\n"
                    f"Pergunta do usuario: {question}\n\n"
                    f"Contexto recente:\n{context_text}{previous_sql_text}"
                ),
            },
        ]

        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": int(self.valves.SQL_MAX_TOKENS)},
        }

        sql_timeout = min(
            float(self.valves.OLLAMA_TIMEOUT_SECONDS),
            float(self.valves.OLLAMA_SQL_TIMEOUT_SECONDS),
        )
        async with httpx.AsyncClient(timeout=sql_timeout) as client:
            response = await client.post(f"{self.valves.OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = str(message.get("content", "")).strip()
        sql = self._extract_sql_block(content)
        if not sql:
            raise ValueError("O modelo nao retornou SQL em formato valido.")
        return self._ensure_select_only(sql)

    async def _repair_sql(self, body: dict, question: str, schema_text: str, bad_sql: str, error_text: str) -> str:
        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Voce corrige SQL para DuckDB. Retorne apenas um bloco de codigo Markdown com a consulta corrigida. "
                        "Use somente leitura."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Schema:\n{schema_text}\n\n"
                        f"Pergunta: {question}\n\n"
                        f"SQL com erro:\n```sql\n{bad_sql}\n```\n\n"
                        f"Erro retornado pelo DuckDB:\n{error_text}"
                    ),
                },
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": int(self.valves.SQL_MAX_TOKENS)},
        }

        sql_timeout = min(
            float(self.valves.OLLAMA_TIMEOUT_SECONDS),
            float(self.valves.OLLAMA_SQL_TIMEOUT_SECONDS),
        )
        async with httpx.AsyncClient(timeout=sql_timeout) as client:
            response = await client.post(f"{self.valves.OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = str(message.get("content", "")).strip()
        sql = self._extract_sql_block(content)
        if not sql:
            raise ValueError("Nao foi possivel corrigir o SQL.")
        return self._ensure_select_only(sql)

    async def _summarize_result(self, question: str, sql: str, markdown_table: str) -> str:
        # Para performance, nao envie tabela completa. Use apenas as primeiras linhas.
        snippet_lines = markdown_table.splitlines()[:14]
        snippet = "\n".join(snippet_lines)
        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": [
                {
                    "role": "system",
                "content": (
                "Voce e o Aquafast IA. Explique o resultado de forma objetiva, executiva e honesta. "
                "Nao invente numeros. Use exatamente os valores fornecidos na tabela."
            ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Pergunta: {question}\n\n"
                        f"SQL executado:\n```sql\n{sql}\n```\n\n"
                        f"Resultado (amostra):\n{snippet}\n\n"
                        "Resuma o que o resultado mostra em portugues, em 3 a 6 linhas, "
                        "e destaque a principal leitura de negocio."
                    ),
                },
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": int(self.valves.MAX_MODEL_TOKENS)},
        }

        async with httpx.AsyncClient(timeout=self.valves.OLLAMA_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{self.valves.OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = str(message.get("content", "")).strip()
        return content or "Analise concluida."

    async def _classify_intent_with_llm(self, question: str) -> str:
        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": [
                {"role": "system", "content": INTENT_ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 12},
        }
        timeout = min(float(self.valves.OLLAMA_TIMEOUT_SECONDS), 10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{self.valves.OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = self._normalize_text(str(message.get("content", "")).strip())
        category = content.split()[0] if content else "fora_de_contexto"
        valid = {
            "top_produtos",
            "top_clientes",
            "ranking_redes",
            "receita_total",
            "lojas_hoje",
            "market_share",
            "concorrentes_por_categoria",
            "oportunidades",
            "evolucao_mensal",
            "resumo_geral",
            "fora_de_contexto",
        }
        return category if category in valid else "fora_de_contexto"

    async def _format_with_llm(self, question: str, data: dict[str, Any]) -> str:
        payload_data = {
            "title": data.get("title"),
            "route": data.get("route"),
            "group": data.get("group"),
            "intent": data.get("intent"),
            "columns": data.get("columns", []),
            "rows": data.get("rows", []),
            "row_count": data.get("row_count", 0),
            "markdown": data.get("markdown", ""),
        }
        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": FORMAT_WITH_LLM_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": FORMAT_WITH_LLM_USER_PROMPT_TEMPLATE.format(
                        question=question,
                        data=json.dumps(payload_data, ensure_ascii=False),
                    ),
                },
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": int(self.valves.MAX_MODEL_TOKENS)},
        }
        timeout = min(float(self.valves.OLLAMA_TIMEOUT_SECONDS), 10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{self.valves.OLLAMA_BASE_URL}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
            message = data.get("message", {}) if isinstance(data, dict) else {}
            content = str(message.get("content", "")).strip()
            return content or ""
        except Exception:
            return ""

    def _http_status_error_message(self, exc: httpx.HTTPStatusError) -> str:
        detail = ""
        request_url = ""
        if exc.response is not None:
            try:
                detail = exc.response.text.strip()
            except Exception:
                detail = ""
            try:
                request_url = str(exc.request.url)
            except Exception:
                request_url = ""
        if len(detail) > 800:
            detail = detail[:797] + "..."
        code = exc.response.status_code if exc.response is not None else "?"
        lower_detail = detail.lower()
        lower_url = request_url.lower()

        # Evita spinner infinito quando o fallback depende de modelo Ollama ausente.
        if code == 404 and ("model" in lower_detail and "not found" in lower_detail):
            model_name = safe_output_text(getattr(self.valves, "CHAT_MODEL", "")).strip() or "llama3.2:3b"
            return safe_output_text(
                "Nao consegui concluir esta consulta porque o modelo de fallback nao esta disponivel no Ollama.\n\n"
                f"Modelo configurado: `{model_name}`.\n"
                "A pergunta predefinida continua funcionando via API deterministica, mas para fallback por chat "
                "e necessario carregar este modelo no Ollama."
            )

        return safe_output_text(
            f"Erro HTTP {code} na API Aquafast.\n\n"
            f"{detail or '(sem detalhe no corpo da resposta)'}\n\n"
            "Confirme se o servico da API esta no ar, a URL em Valves (ex.: `http://scanntech-api:8000`) "
            "bate com o `docker compose` e se o arquivo `aquafast_scanntech.duckdb` existe no container."
        )
    def _build_analysis_response(self, question: str, result: dict[str, Any], sql_hint: str) -> str:
        summary = safe_output_text(self._deterministic_summary(question, result.get("columns", []), result.get("rows", [])))
        source_note = safe_output_text(self._source_note_from_result(question, result))
        markdown = safe_output_text(result.get("markdown", ""))
        history_block = safe_output_text(self._history_block_from_result(question, result))
        cap_note = ""
        if result.get("truncated"):
            cap = result.get("row_cap")
            cap_note = safe_output_text(
                f"\n\n_Amostra limitada pela API ({cap} linhas no maximo). "
                "Refine a pergunta com filtros (mes, cliente, produto) ou use LIMIT menor no SQL para ver tudo no Excel._"
            )
        return self._finalize_output("\n".join(
            [
                safe_output_text("## Análise Aquafast"),
                "",
                summary,
                "",
                source_note,
                "",
                markdown,
                "",
                safe_output_text(f"_Linhas retornadas: {result.get('row_count', 0)}_"),
                "",
                history_block,
                cap_note,
            ]
        ).strip())
    async def _try_legacy_ask(self, question: str) -> str | None:
        """Respostas instantaneas via POST /ask quando a pergunta casa com legacy_question_to_sql na API."""
        base = self.valves.API_BASE_URL.rstrip("/")
        url = f"{base}/ask"
        timeout = min(float(self.valves.LEGACY_ASK_TIMEOUT_SECONDS), float(self.valves.TIMEOUT_SECONDS))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json={"question": question.strip()})
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except Exception:
            return None
        if not data.get("ok"):
            return None
        sql_hint = str(data.get("sql", "") or "")
        return self._build_analysis_response(question, data, sql_hint)

    async def _run_data_pipeline(
        self,
        body: dict,
        question: str,
        export: bool = False,
        chart: bool = False,
        sql_override: str | None = None,
        intent_group: str | None = None,
    ) -> str:
        started = time.time()
        group = intent_group or "Insights de Vendas"
        if not export and sql_override is None:
            legacy_reply = await self._try_legacy_ask(question)
            if legacy_reply is not None:
                self._log_agent_query(
                    group=group,
                    route="/ask",
                    mode="deterministic",
                    started_at=started,
                    status="ok",
                    rows=None,
                )
                return legacy_reply

        schema = await self._fetch_schema()
        schema_text = schema.get("summary_text", "")
        previous_sql = self._find_last_sql(body)
        sql = sql_override or await self._generate_sql(body, question, schema_text, previous_sql=previous_sql)
        validation_error = self._validate_sql_against_question(question, sql)
        if validation_error:
            # tenta uma vez regenerar com instrucao extra, sem depender do usuario.
            sql = await self._generate_sql(
                body,
                f"{question}\n\nIMPORTANTE: {validation_error}",
                schema_text,
                previous_sql=previous_sql,
            )

        try:
            if export:
                result = await self._export_sql(sql, "Exportacao Excel")
                download_url = result.get("download_url", "")
                self._log_agent_query(
                    group=group,
                    route="/export",
                    mode="deterministic",
                    started_at=started,
                    status="ok",
                    rows=result.get("row_count"),
                )
                return "\n".join(
                    [
                        "## Exportacao Excel",
                        "",
                        "Arquivo Excel gerado com sucesso.",
                        f"[Baixar o arquivo]({download_url})",
                        "",
                        f"_Consulta executada: `{result.get('sql', sql)}`_",
                        f"_Linhas exportadas: {result.get('row_count', 0)}_",
                    ]
                )

            sql_for_api = self._wrap_sql_for_safe_rows(sql, for_export=False)
            result = await self._query_sql(sql_for_api, "Analise Aquafast")
        except httpx.HTTPStatusError as exc:
            detail = str(exc.response.text) if exc.response is not None else ""
            if exc.response is not None and exc.response.status_code == 400:
                try:
                    repaired_sql = await self._repair_sql(body, question, schema_text, sql, detail)
                    if export:
                        result = await self._export_sql(repaired_sql, "Exportacao Excel")
                        download_url = result.get("download_url", "")
                        return "\n".join(
                            [
                                "## Exportacao Excel",
                                "",
                                "Arquivo Excel gerado com sucesso.",
                                f"[Baixar o arquivo]({download_url})",
                                "",
                                f"_Consulta executada: `{result.get('sql', repaired_sql)}`_",
                                f"_Linhas exportadas: {result.get('row_count', 0)}_",
                            ]
                        )
                    sql = repaired_sql
                    sql_for_api = self._wrap_sql_for_safe_rows(sql, for_export=False)
                    result = await self._query_sql(sql_for_api, "Analise Aquafast")
                except httpx.TimeoutException:
                    self._log_agent_query(
                        group=group,
                        route="/query",
                        mode="deterministic",
                        started_at=started,
                        status="error",
                        rows=None,
                        error="timeout_repair_sql",
                    )
                    return (
                        "Timeout ao corrigir ou reexecutar o SQL (Ollama ou API demorou demais). "
                        "Tente de novo em instantes; perguntas comuns respondem direto pela API sem LLM."
                    )
                except httpx.HTTPStatusError as exc2:
                    self._log_agent_query(
                        group=group,
                        route="/query",
                        mode="deterministic",
                        started_at=started,
                        status="error",
                        rows=None,
                        error=f"http_status_{exc2.response.status_code if exc2.response is not None else '?'}",
                    )
                    return self._http_status_error_message(exc2)
                except Exception as fix_exc:
                    self._log_agent_query(
                        group=group,
                        route="/query",
                        mode="deterministic",
                        started_at=started,
                        status="error",
                        rows=None,
                        error=type(fix_exc).__name__,
                    )
                    fix_msg = str(fix_exc).strip()
                    if len(fix_msg) > 400:
                        fix_msg = fix_msg[:397] + "..."
                    orig = detail.strip()
                    if len(orig) > 500:
                        orig = orig[:497] + "..."
                    return (
                        "Nao consegui executar a consulta apos tentar corrigir o SQL automaticamente.\n\n"
                        f"Resposta da API na primeira tentativa: {orig or '(vazio)'}\n\n"
                        f"Erro na segunda tentativa: {fix_msg}"
                    )
            else:
                self._log_agent_query(
                    group=group,
                    route="/query",
                    mode="deterministic",
                    started_at=started,
                    status="error",
                    rows=None,
                    error=f"http_status_{exc.response.status_code if exc.response is not None else '?'}",
                )
                return self._finalize_output(self._http_status_error_message(exc))

        if export:
            # defensive fallback; normally handled earlier
            download_url = result.get("download_url", "")
            self._log_agent_query(
                group=group,
                route="/export",
                mode="deterministic",
                started_at=started,
                status="ok",
                rows=result.get("row_count"),
            )
            return "\n".join(
                [
                    "## Exportacao Excel",
                    "",
                    "Arquivo Excel gerado com sucesso.",
                    f"[Baixar o arquivo]({download_url})",
                    "",
                    f"_Consulta executada: `{result.get('sql', sql)}`_",
                    f"_Linhas exportadas: {result.get('row_count', 0)}_",
                ]
            )

        self._log_agent_query(
            group=group,
            route="/query",
            mode="deterministic",
            started_at=started,
            status="ok",
            rows=result.get("row_count"),
        )
        return self._build_analysis_response(question, result, sql)

    def _render_chart(self, title: str, columns: list[str], rows: list[list[Any]]) -> str:
        if not rows:
            return "_Nenhum dado encontrado para montar o grafico._"

        labels = ["cliente", "produto", "mes", "periodo", "categoria", "name"]
        values = ["valor_total", "receita_total", "receita", "total_vendas", "total_pedidos", "qtd", "quantity"]

        lower_map = {column.lower(): column for column in columns}
        label_col = next((original for key in labels for lower, original in lower_map.items() if key == lower or key in lower), None)
        value_col = next((original for key in values for lower, original in lower_map.items() if key == lower or key in lower), None)

        if not label_col and columns:
            label_col = columns[0]
        if not value_col and len(columns) > 1:
            value_col = columns[1]

        if not label_col or not value_col:
            return "_Nao foi possivel identificar colunas para o grafico._"

        label_idx = columns.index(label_col)
        value_idx = columns.index(value_col)
        points = []
        for row in rows[:12]:
            label = str(row[label_idx])
            value = row[value_idx]
            try:
                numeric = float(value)
            except Exception:
                continue
            points.append((label, numeric))

        if not points:
            return "_Nao encontrei valores numericos suficientes para montar o grafico._"

        max_value = max(v for _, v in points)
        if max_value <= 0:
            max_value = 1.0

        chart_lines = [
            "```mermaid",
            "xychart-beta",
            f'    title "{title}"',
            f'    x-axis {json.dumps([label for label, _ in points], ensure_ascii=False)}',
            f'    y-axis "{value_col}" 0 --> {int(max_value * 1.1) if max_value > 0 else 1}',
            f"    bar {json.dumps([round(value, 2) for _, value in points], ensure_ascii=False)}",
            "```",
        ]
        return self._finalize_output("\n".join(chart_lines))

    def _answer_available_questions(self) -> str:
        lines = ["# Perguntas disponíveis", ""]
        for group in AGENT_GROUPS:
            label = safe_text(group.get("label") or group.get("title") or "Categoria")
            lines.append(f"## {label}")
            for item in group.get("questions", ()):
                item_text = safe_text(item)
                if item_text:
                    lines.append(f"- {item_text}")
            lines.append("")
        lines.append("Se preferir, envie uma pergunta direta sobre vendas, produtos, concorrência, oportunidades ou auditoria da base.")
        return self._finalize_output("\n".join(lines).strip())

    def _find_agent_group(self, question: str) -> dict[str, Any] | None:
        q = self._normalize_text(question)
        if not q:
            return None

        best_group: dict[str, Any] | None = None
        best_score = 0
        for group in AGENT_GROUPS:
            aliases = {
                self._normalize_text(str(group.get("title", ""))),
                self._normalize_text(str(group.get("label", ""))),
            }
            aliases.update(self._normalize_text(alias) for alias in group.get("aliases", ()))
            if q in aliases:
                return group
            score = 0
            for kw in GROUP_INTENT_KEYWORDS.get(str(group.get("label", "")), ()):
                token = self._normalize_text(kw)
                if token and token in q:
                    score += 1
            if score > best_score:
                best_score = score
                best_group = group
        if best_score > 0:
            return best_group
        return None

    def _is_agent_request(self, question: str) -> bool:
        q = self._normalize_text(question)
        if not q:
            return False
        if q in {self._normalize_text(g.get("title", "")) for g in AGENT_GROUPS}:
            return True
        if q in {self._normalize_text(g.get("label", "")) for g in AGENT_GROUPS}:
            return True
        return any(token in q for token in ("agente", "categoria"))

    def _answer_agent_group(self, question: str) -> str:
        group = self._find_agent_group(question)
        if group is None:
            return ""
        heading = safe_text(group.get("label") or group.get("title") or "Agente") or "Agente"
        lines = [f"## {heading}", ""]
        
        # Add description if available
        if group.get("description"):
            lines.append(safe_text(group.get("description")))
            lines.append("")
        
        questions = [
            safe_text(item)
            for item in group.get("questions", ())
        ]
        for idx, item in enumerate(questions, start=1):
            if item:
                lines.append(f"{idx}. {self._inline_prompt(item)}")
        lines.append("")
        lines.append(safe_text("Clique em uma pergunta para copiar, cole no campo de mensagem e envie."))
        lines.append("Ou use `Mostrar perguntas disponíveis` para ver todas as categorias.")
        return self._finalize_output("\n".join(lines).strip())

    def _intent_group_label(self, question: str) -> str:
        group = self._find_agent_group(question)
        if group is None:
            return "Não reconhecido"
        return safe_text(group.get("label") or group.get("title") or "Não reconhecido")

    def _out_of_scope_guidance(self) -> str:
        return (
            "Posso ajudar com vendas, produtos, concorrência, oportunidades ou auditoria da base. "
            "Tente uma pergunta como: `Quais foram os produtos mais vendidos no último mês?`"
        )

    def _canonicalize_deterministic_question(self, question: str) -> str:
        q = self._normalize_text(question)
        mappings: list[tuple[tuple[str, ...], str]] = [
            (("ranking de produtos", "produtos mais vendidos", "top produtos"), "Quais foram os produtos mais vendidos no último mês?"),
            (("ranking de clientes", "clientes que mais compraram", "top clientes"), "Quais clientes mais compraram Aquafast?"),
            (("evolucao de vendas", "vendas por mes"), "Mostre a evolução de vendas da Aquafast por mês."),
            (("vendas por estado", "vendas por uf", "melhor desempenho de vendas"), "Quais estados têm melhor desempenho de vendas?"),
            (("compare a aquafast", "principais concorrentes", "concorrentes"), "Compare a Aquafast com os principais concorrentes."),
            (("market share", "participacao de mercado", "share"), "Compare a Aquafast com os principais concorrentes."),
            (("sem subgrupo", "dados inconsistentes", "inconsistencia"), "Mostre os produtos sem SUBGRUPO_CIGAM"),
            (("oportunidade de crescimento", "potencial de crescimento", "lacuna"), "Quais produtos teriam mais potencial de venda?"),
            (("resumo executivo", "performance comercial"), "Mostre um resumo executivo da performance comercial."),
        ]
        for aliases, canonical in mappings:
            if any(a in q for a in aliases):
                return canonical
        return question

    def _log_agent_query(
        self,
        *,
        group: str,
        route: str,
        mode: str,
        started_at: float,
        status: str,
        rows: Any = None,
        error: str | None = None,
    ) -> None:
        duration_ms = int((time.time() - started_at) * 1000)
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "agent": safe_text(group) or "Nao reconhecido",
            "route": route,
            "mode": mode,
            "duration_ms": duration_ms,
            "status": status,
            "rows": int(rows) if isinstance(rows, int) else (int(rows) if isinstance(rows, float) else None),
        }
        if error:
            payload["error"] = safe_text(error)[:160]

        candidates = [
            Path(r"C:\xampp\htdocs\scantech\logs\agent_queries.log"),
            Path("/workspace/logs/agent_queries.log"),
            Path("/app/backend/data/logs/agent_queries.log"),
            Path("/tmp/agent_queries.log"),
        ]
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        for path in candidates:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                break
            except Exception:
                continue

    def _format_metric(self, value: float, metric_col: str | None) -> str:
        metric = (metric_col or "").lower()
        if any(k in metric for k in ["receita", "faturamento", "valor_total", "valor total"]):
            return f"R$ {self._format_ptbr_number(value)}"
        if value.is_integer():
            return self._format_ptbr_number(int(value))
        return self._format_ptbr_number(value)

    def _format_ptbr_number(self, value: float | int) -> str:
        if isinstance(value, int):
            return f"{value:,}".replace(",", ".")
        if float(value).is_integer():
            return f"{int(value):,}".replace(",", ".")
        text = f"{float(value):,.2f}"
        return text.replace(",", "X").replace(".", ",").replace("X", ".")

    def _deterministic_summary(self, question: str, columns: list[str], rows: list[list[Any]]) -> str:
        if not rows:
            return "Nenhum resultado encontrado para essa consulta."

        metric_col = self._pick_metric_column(question, columns, rows)
        label_col = self._pick_label_column(columns, rows, metric_col)
        if not metric_col or metric_col not in columns:
            return "Resultado retornado. Veja a tabela abaixo."

        metric_idx = columns.index(metric_col)
        label_idx = columns.index(label_col) if label_col in columns else 0

        if len(rows) == 1:
            row = rows[0]
            metric_value = self._as_float(row[metric_idx])
            if metric_value is not None:
                formatted = self._format_metric(metric_value, metric_col)
                if label_col in columns and label_col != metric_col:
                    label_value = str(row[label_idx])
                    return f"{label_value}: {formatted}"
                return f"{metric_col}: {formatted}"

        points = []
        for row in rows:
            m = self._as_float(row[metric_idx])
            if m is None:
                continue
            points.append((str(row[label_idx]), m))

        if not points:
            return "Resultado retornado. Veja a tabela abaixo."

        points.sort(key=lambda x: x[1], reverse=True)
        total = sum(v for _, v in points)
        top = points[:3]
        lines = []
        lines.append(f"Metricas: `{metric_col}` (ordenado desc).")
        lines.append("Top 3:")
        for i, (name, v) in enumerate(top, start=1):
            lines.append(f"{i}. {name} - {self._format_metric(v, metric_col)}")
        if total > 0 and len(points) >= 3:
            share = sum(v for _, v in top) / total * 100.0
            lines.append(f"Participacao do top 3 no total listado: {share:.1f}%")
        return "\n".join(lines)

    def _source_note_from_result(self, question: str, result: dict[str, Any]) -> str:
        note = str(result.get("source_note", "") or "").strip()
        if note:
            return note

        title = str(result.get("title", "") or "")
        sql = str(result.get("sql", "") or "")
        text = self._normalize_text(" ".join([question, title, sql]))

        if "potencial de venda" in text or "maior potencial" in text:
            return (
                "Fonte: `top_produtos_categoria`. "
                "A consulta usa a presenca em PDVs e o volume em caixas como proxy de potencial de venda."
            )
        if any(
            term in text
            for term in [
                "lojas com concorrente sem aquafast",
            ]
        ):
            return (
                "Fonte: `lojas_com_concorrente_sem_aquafast`. "
                "A consulta usa PDV_ID como chave principal e expÃµe `status_loja` quando a ligaÃƒÂ§ÃƒÂ£o nao existir."
            )
        if any(
            term in text
            for term in [
                "concorrentes por categoria",
                "share aquafast por categoria",
                "top concorrentes por cidade",
                "concorrentes em crescimento 90 dias",
            ]
        ):
            return (
                "Fonte: views deterministicas de concorrencia. "
                "A consulta usa o universo do mercado carregado e separa Aquafast de concorrentes sem chamar LLM."
            )
        if any(term in text for term in ["maior concorrente", "concorrente", "concorrentes", "concorrencia", "competidor", "competidores"]):
            return (
                "Fonte: `ms_mercado_aquafast`. "
                "A consulta compara os fabricantes do mercado da categoria e exclui a Aquafast para apontar concorrentes."
            )
        if any(term in text for term in ["market share", "participacao", "share"]):
            return (
                "Fonte: `ms_mercado_aquafast`. "
                "A consulta mede a participacao de cada fabricante dentro do mercado da categoria."
            )
        if any(term in text for term in ["ponto de venda", "pontos de venda", "loja", "lojas", "pdv"]):
            return (
                "Fonte: `ranking_clientes`. "
                "A consulta conta as lojas/PDVs que aparecem com venda Aquafast no periodo carregado."
            )
        if any(term in text for term in ["produto por categoria", "categoria", "litragem", "mix"]):
            return (
                "Fonte: `top_produtos_categoria`. "
                "A consulta cruza o portfolio Aquafast com caixas para enxergar o mix por categoria, "
                "consolidando pelo mapeamento oficial de `SUBGRUPO_CIGAM`."
            )
        if any(term in text for term in ["vendas por mes", "vendas por mÃƒÂªs", "mensal", "serie mensal", "sÃƒÂ©rie mensal"]):
            return (
                "Fonte: `vendas_por_mes`. "
                "A consulta consolida caixas e receita ao longo do tempo para mostrar tendencia mensal."
            )
        if any(term in text for term in ["vendas por estado", "estado", "uf"]):
            return (
                "Fonte: `vendas_caixas_estado`. "
                "A consulta cruza as vendas Aquafast com a UF para mostrar distribuicao geografica."
            )
        if any(term in text for term in ["top produtos", "ranking produtos", "mais vendidos", "receita por produto", "volume de vendas"]):
            return (
                "Fonte: `ranking_produtos`. "
                "A consulta lista os produtos Aquafast com maior volume em caixas e receita, "
                "consolidando pelo mapeamento oficial de `SUBGRUPO_CIGAM`."
            )
        if any(term in text for term in ["subgrupo cigam", "padronizacao", "padronizaÃ§Ã£o", "nao casam com o portfolio", "nao casam com o portifolio"]):
            return (
                "Fonte: `auditoria_produtos_sem_subgrupo_cigam`. "
                "A consulta lista os produtos Aquafast sem correspondencia no portfolio e sugere `SUBGRUPO_CIGAM` apenas quando a similaridade e transparente."
            )
        if any(term in text for term in ["historico de consultas", "historico consultas", "ultimas consultas", "quais relatorios eu consultei"]):
            return (
                "Fonte: `aquafast_query_history`. "
                "A consulta mostra as 20 consultas deterministicas mais recentes registradas pelo Scanntech Analyst."
            )
        if any(term in text for term in ["clientes", "lojas", "churn", "compra"]):
            return (
                "Fonte: `ranking_clientes`. "
                "A consulta resume as lojas Aquafast por caixas vendidas, receita e recorrencia."
            )
        return "Fonte: consulta local no DuckDB usando as views semanticas da Aquafast."

    def _history_block_from_result(self, question: str, result: dict[str, Any]) -> str:
        report_name = str(result.get("history_report_name", "") or "").strip()
        timestamp = str(result.get("history_timestamp", "") or "").strip()
        if not report_name and not timestamp:
            return ""
        lines = ["Historico desta consulta:", f"- relatorio: {report_name or 'desconhecido'}", f"- pergunta: {question or ''}"]
        if timestamp:
            lines.append(f"- executado em: {timestamp}")
        return "\n".join(lines)

    def _ensure_select_only(self, sql: str) -> str:
        normalized = self._normalize_text(sql)
        if not re.match(r"^(select|with|show|describe)\b", normalized):
            raise ValueError("SQL gerado nao parece ser uma consulta somente leitura.")
        return sql.strip().rstrip(";")

    def _wrap_sql_for_safe_rows(self, sql: str, *, for_export: bool) -> str:
        """
        Evita SELECT sem LIMIT puxando milhoes de linhas (lento no DuckDB e no chat).
        Exportacao Excel usa so o teto da API (EXPORT); nao aplica este wrap.
        """
        if for_export:
            return sql.strip().rstrip(";")
        s = sql.strip().rstrip(";")
        low = s.lower()
        if not (low.startswith("select") or low.startswith("with")):
            return s
        collapsed = re.sub(r"\s+", " ", low).strip()
        if re.search(r"\blimit\s+\d+(\s+offset\s+\d+)?\s*$", collapsed):
            return s
        cap = max(1, int(self.valves.SQL_SAFETY_ROW_CAP))
        return f"SELECT * FROM ({s}) AS _aquafast_safe LIMIT {cap}"

    async def _generate_sql(self, body: dict, question: str, schema_text: str, previous_sql: str | None = None) -> str:
        messages = body.get("messages", [])[-int(self.valves.SQL_CONTEXT_MESSAGES) :]
        user_context = []
        for message in messages:
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = self._content_to_text(message.get("content", ""))
            if not content:
                continue
        # evita mandar tabelas gigantes pro modelo
            if "| --- |" in content or content.count("\n|") > 5:
                continue
            user_context.append(f"{role.upper()}: {content[:600]}")
        context_text = "\n".join(user_context) if user_context else "sem contexto adicional"
        previous_sql_text = f"\n\nSQL anterior (para modificar/continuar se fizer sentido):\n```sql\n{previous_sql}\n```" if previous_sql else ""

        prompt = [
            {
                "role": "system",
                "content": (
                    "Voce e um analista de dados especializado no portfolio Aquafast sobre DuckDB. "
                    "A regra padrao e analisar apenas o mercado Aquafast, usando caixas como base de negocio e evitando a leitura do universo bruto da Scanntech. "
                    "Para perguntas operacionais de resultado, ranking e evolucao, considere apenas os itens Aquafast (is_aquafast = 1). "
                    "Use o universo completo da categoria apenas quando a pergunta for explicitamente de concorrencia, market share ou comparacao de mercado. "
                    "Gere apenas SQL valido e somente leitura. "
                    "Use apenas tabelas, views e colunas existentes no schema fornecido. "
                    "Responda com um unico bloco de codigo Markdown ```sql ... ``` e nada mais. "
                    "Se a pergunta pedir top 20, use LIMIT 20. "
                    "Sempre termine consultas exploratorias com LIMIT (ex.: 200 ou 500) quando nao houver agregacao que ja reduza o resultado. "
                    "Prefira as views ranking_clientes, ranking_produtos, vendas_por_mes, ms_mercado_aquafast, vendas_caixas_estado e top_produtos_categoria quando elas atenderem a pergunta. "
                    "Nao invente colunas. Nao use INSERT, UPDATE, DELETE, DROP ou ALTER."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Schema DuckDB/Aquafast:\n{schema_text}\n\n"
                    f"Pergunta do usuario: {question}\n\n"
                    f"Contexto recente:\n{context_text}{previous_sql_text}"
                ),
            },
        ]

        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": int(self.valves.SQL_MAX_TOKENS)},
        }

        sql_timeout = min(
            float(self.valves.OLLAMA_TIMEOUT_SECONDS),
            float(self.valves.OLLAMA_SQL_TIMEOUT_SECONDS),
        )
        async with httpx.AsyncClient(timeout=sql_timeout) as client:
            response = await client.post(f"{self.valves.OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = str(message.get("content", "")).strip()
        sql = self._extract_sql_block(content)
        if not sql:
            raise ValueError("O modelo nao retornou SQL em formato valido.")
        return self._ensure_select_only(sql)

    async def _repair_sql(self, body: dict, question: str, schema_text: str, bad_sql: str, error_text: str) -> str:
        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Voce corrige SQL para DuckDB. Retorne apenas um bloco de codigo Markdown com a consulta corrigida. "
                        "Use somente leitura."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Schema:\n{schema_text}\n\n"
                        f"Pergunta: {question}\n\n"
                        f"SQL com erro:\n```sql\n{bad_sql}\n```\n\n"
                        f"Erro retornado pelo DuckDB:\n{error_text}"
                    ),
                },
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": int(self.valves.SQL_MAX_TOKENS)},
        }

        sql_timeout = min(
            float(self.valves.OLLAMA_TIMEOUT_SECONDS),
            float(self.valves.OLLAMA_SQL_TIMEOUT_SECONDS),
        )
        async with httpx.AsyncClient(timeout=sql_timeout) as client:
            response = await client.post(f"{self.valves.OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = str(message.get("content", "")).strip()
        sql = self._extract_sql_block(content)
        if not sql:
            raise ValueError("Nao foi possivel corrigir o SQL.")
        return self._ensure_select_only(sql)

    async def _summarize_result(self, question: str, sql: str, markdown_table: str) -> str:
        # Para performance, nao envie tabela completa. Use apenas as primeiras linhas.
        snippet_lines = markdown_table.splitlines()[:14]
        snippet = "\n".join(snippet_lines)
        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": [
                {
                    "role": "system",
                "content": (
                "Voce e o Aquafast IA. Explique o resultado de forma objetiva, executiva e honesta. "
                "Nao invente numeros. Use exatamente os valores fornecidos na tabela."
            ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Pergunta: {question}\n\n"
                        f"SQL executado:\n```sql\n{sql}\n```\n\n"
                        f"Resultado (amostra):\n{snippet}\n\n"
                        "Resuma o que o resultado mostra em portugues, em 3 a 6 linhas, "
                        "e destaque a principal leitura de negocio."
                    ),
                },
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": int(self.valves.MAX_MODEL_TOKENS)},
        }

        async with httpx.AsyncClient(timeout=self.valves.OLLAMA_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{self.valves.OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = str(message.get("content", "")).strip()
        return content or "Analise concluida."

    def _http_status_error_message(self, exc: httpx.HTTPStatusError) -> str:
        detail = ""
        request_url = ""
        if exc.response is not None:
            try:
                detail = exc.response.text.strip()
            except Exception:
                detail = ""
            try:
                request_url = str(exc.request.url)
            except Exception:
                request_url = ""
        if len(detail) > 800:
            detail = detail[:797] + "..."
        code = exc.response.status_code if exc.response is not None else "?"
        lower_detail = detail.lower()
        lower_url = request_url.lower()
        if code == 404 and ("model" in lower_detail and "not found" in lower_detail):
            model_name = safe_output_text(getattr(self.valves, "CHAT_MODEL", "")).strip() or "llama3.2:3b"
            backend_hint = "Ollama" if "11434" in lower_url or "/api/chat" in lower_url else "modelo de fallback"
            return safe_output_text(
                f"Nao consegui concluir esta consulta porque o {backend_hint} nao esta disponivel.\n\n"
                f"Modelo configurado: `{model_name}`.\n"
                "Perguntas predefinidas continuam funcionando pela API deterministica. "
                "Para fallback por chat, carregue o modelo no Ollama."
            )
        return safe_output_text(
            f"Erro HTTP {code} na API Aquafast.\n\n"
            f"{detail or '(sem detalhe no corpo da resposta)'}\n\n"
            "Confirme se o servico da API esta no ar, a URL em Valves (ex.: `http://scanntech-api:8000`) "
            "bate com o `docker compose` e se o arquivo `aquafast_scanntech.duckdb` existe no container."
        )
    def _build_analysis_response(self, question: str, result: dict[str, Any], sql_hint: str) -> str:
        summary = safe_output_text(self._deterministic_summary(question, result.get("columns", []), result.get("rows", [])))
        source_note = safe_output_text(self._source_note_from_result(question, result))
        markdown = safe_output_text(result.get("markdown", ""))
        history_block = safe_output_text(self._history_block_from_result(question, result))
        cap_note = ""
        if result.get("truncated"):
            cap = result.get("row_cap")
            cap_note = safe_output_text(
                f"\n\n_Amostra limitada pela API ({cap} linhas no maximo). "
                "Refine a pergunta com filtros (mes, cliente, produto) ou use LIMIT menor no SQL para ver tudo no Excel._"
            )
        return self._finalize_output("\n".join(
            [
                safe_output_text("## Análise Aquafast"),
                "",
                summary,
                "",
                source_note,
                "",
                markdown,
                "",
                safe_output_text(f"_Linhas retornadas: {result.get('row_count', 0)}_"),
                "",
                history_block,
                cap_note,
            ]
        ).strip())
    async def _try_legacy_ask(self, question: str) -> str | None:
        """Respostas instantaneas via POST /ask quando a pergunta casa com legacy_question_to_sql na API."""
        base = self.valves.API_BASE_URL.rstrip("/")
        url = f"{base}/ask"
        timeout = min(float(self.valves.LEGACY_ASK_TIMEOUT_SECONDS), float(self.valves.TIMEOUT_SECONDS))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json={"question": question.strip()})
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except Exception:
            return None
        if not data.get("ok"):
            return None
        sql_hint = str(data.get("sql", "") or "")
        return self._build_analysis_response(question, data, sql_hint)

    async def _run_data_pipeline(
        self,
        body: dict,
        question: str,
        export: bool = False,
        chart: bool = False,
        sql_override: str | None = None,
        intent_group: str | None = None,
    ) -> str:
        started = time.time()
        group = intent_group or self._intent_group_label(question)
        if not export and sql_override is None:
            legacy_reply = await self._try_legacy_ask(question)
            if legacy_reply is not None:
                self._log_agent_query(group=group, route="/ask", mode="deterministic", started_at=started, status="ok")
                return legacy_reply

        schema = await self._fetch_schema()
        schema_text = schema.get("summary_text", "")
        previous_sql = self._find_last_sql(body)
        sql = sql_override or await self._generate_sql(body, question, schema_text, previous_sql=previous_sql)
        validation_error = self._validate_sql_against_question(question, sql)
        if validation_error:
            # tenta uma vez regenerar com instrucao extra, sem depender do usuario.
            sql = await self._generate_sql(
                body,
                f"{question}\n\nIMPORTANTE: {validation_error}",
                schema_text,
                previous_sql=previous_sql,
            )

        try:
            if export:
                result = await self._export_sql(sql, "Exportacao Excel")
                download_url = result.get("download_url", "")
                self._log_agent_query(
                    group=group,
                    route="/export",
                    mode="deterministic",
                    started_at=started,
                    status="ok",
                    rows=result.get("row_count"),
                )
                return "\n".join(
                    [
                        "## Exportacao Excel",
                        "",
                        "Arquivo Excel gerado com sucesso.",
                        f"[Baixar o arquivo]({download_url})",
                        "",
                        f"_Consulta executada: `{result.get('sql', sql)}`_",
                        f"_Linhas exportadas: {result.get('row_count', 0)}_",
                    ]
                )

            sql_for_api = self._wrap_sql_for_safe_rows(sql, for_export=False)
            result = await self._query_sql(sql_for_api, "Analise Aquafast")
        except httpx.HTTPStatusError as exc:
            detail = str(exc.response.text) if exc.response is not None else ""
            if exc.response is not None and exc.response.status_code == 400:
                try:
                    repaired_sql = await self._repair_sql(body, question, schema_text, sql, detail)
                    if export:
                        result = await self._export_sql(repaired_sql, "Exportacao Excel")
                        download_url = result.get("download_url", "")
                        return "\n".join(
                            [
                                "## Exportacao Excel",
                                "",
                                "Arquivo Excel gerado com sucesso.",
                                f"[Baixar o arquivo]({download_url})",
                                "",
                                f"_Consulta executada: `{result.get('sql', repaired_sql)}`_",
                                f"_Linhas exportadas: {result.get('row_count', 0)}_",
                            ]
                        )
                    sql = repaired_sql
                    sql_for_api = self._wrap_sql_for_safe_rows(sql, for_export=False)
                    result = await self._query_sql(sql_for_api, "Analise Aquafast")
                except httpx.TimeoutException:
                    return (
                        "Timeout ao corrigir ou reexecutar o SQL (Ollama ou API demorou demais). "
                        "Tente de novo em instantes; perguntas comuns respondem direto pela API sem LLM."
                    )
                except httpx.HTTPStatusError as exc2:
                    return self._http_status_error_message(exc2)
                except Exception as fix_exc:
                    fix_msg = str(fix_exc).strip()
                    if len(fix_msg) > 400:
                        fix_msg = fix_msg[:397] + "..."
                    orig = detail.strip()
                    if len(orig) > 500:
                        orig = orig[:497] + "..."
                    return (
                        "Nao consegui executar a consulta apos tentar corrigir o SQL automaticamente.\n\n"
                        f"Resposta da API na primeira tentativa: {orig or '(vazio)'}\n\n"
                        f"Erro na segunda tentativa: {fix_msg}"
                    )
            else:
                self._log_agent_query(
                    group=group,
                    route="/query",
                    mode="deterministic",
                    started_at=started,
                    status="error",
                    error=f"http_status_{exc.response.status_code if exc.response is not None else '?'}",
                )
                return self._finalize_output(self._http_status_error_message(exc))

        if export:
            # defensive fallback; normally handled earlier
            download_url = result.get("download_url", "")
            self._log_agent_query(
                group=group,
                route="/export",
                mode="deterministic",
                started_at=started,
                status="ok",
                rows=result.get("row_count"),
            )
            return "\n".join(
                [
                    "## Exportacao Excel",
                    "",
                    "Arquivo Excel gerado com sucesso.",
                    f"[Baixar o arquivo]({download_url})",
                    "",
                    f"_Consulta executada: `{result.get('sql', sql)}`_",
                    f"_Linhas exportadas: {result.get('row_count', 0)}_",
                ]
            )

        self._log_agent_query(
            group=group,
            route="/query",
            mode="deterministic",
            started_at=started,
            status="ok",
            rows=result.get("row_count"),
        )
        return self._build_analysis_response(question, result, sql)

    def _render_chart(self, title: str, columns: list[str], rows: list[list[Any]]) -> str:
        if not rows:
            return "_Nenhum dado encontrado para montar o grafico._"

        labels = ["cliente", "produto", "mes", "periodo", "categoria", "name"]
        values = ["valor_total", "receita_total", "receita", "total_vendas", "total_pedidos", "qtd", "quantity"]

        lower_map = {column.lower(): column for column in columns}
        label_col = next((original for key in labels for lower, original in lower_map.items() if key == lower or key in lower), None)
        value_col = next((original for key in values for lower, original in lower_map.items() if key == lower or key in lower), None)

        if not label_col and columns:
            label_col = columns[0]
        if not value_col and len(columns) > 1:
            value_col = columns[1]

        if not label_col or not value_col:
            return "_Nao foi possivel identificar colunas para o grafico._"

        label_idx = columns.index(label_col)
        value_idx = columns.index(value_col)
        points = []
        for row in rows[:12]:
            label = str(row[label_idx])
            value = row[value_idx]
            try:
                numeric = float(value)
            except Exception:
                continue
            points.append((label, numeric))

        if not points:
            return "_Nao encontrei valores numericos suficientes para montar o grafico._"

        max_value = max(v for _, v in points)
        if max_value <= 0:
            max_value = 1.0

        chart_lines = [
            "```mermaid",
            "xychart-beta",
            f'    title "{title}"',
            f'    x-axis {json.dumps([label for label, _ in points], ensure_ascii=False)}',
            f'    y-axis "{value_col}" 0 --> {int(max_value * 1.1) if max_value > 0 else 1}',
            f"    bar {json.dumps([round(value, 2) for _, value in points], ensure_ascii=False)}",
            "```",
        ]
        return self._finalize_output("\n".join(chart_lines))

    def _answer_available_questions(self) -> str:
        lines = ["# Perguntas disponíveis", ""]
        for group in AGENT_GROUPS:
            label = safe_text(group.get("label") or group.get("title") or "Categoria")
            lines.append(f"## {label}")
            for item in group.get("questions", ()):
                item_text = safe_text(item)
                if item_text:
                    lines.append(f"- {item_text}")
            lines.append("")
        return self._finalize_output("\n".join(lines).strip())

    def _find_agent_group(self, question: str) -> dict[str, Any] | None:
        q = self._normalize_text(question)
        if not q:
            return None
        best_group = None
        best_score = 0
        for group in AGENT_GROUPS:
            aliases = {
                self._normalize_text(str(group.get("title", ""))),
                self._normalize_text(str(group.get("label", ""))),
            }
            aliases.update(self._normalize_text(alias) for alias in group.get("aliases", ()))
            if q in aliases:
                return group
            score = 0
            for kw in GROUP_INTENT_KEYWORDS.get(str(group.get("label", "")), ()):
                token = self._normalize_text(kw)
                if token and token in q:
                    score += 1
            if score > best_score:
                best_score = score
                best_group = group
        return best_group if best_score > 0 else None

    def _is_agent_request(self, question: str) -> bool:
        q = self._normalize_text(question)
        if not q:
            return False
        if q in {self._normalize_text(g.get("title", "")) for g in AGENT_GROUPS}:
            return True
        if q in {self._normalize_text(g.get("label", "")) for g in AGENT_GROUPS}:
            return True
        return any(token in q for token in ("agente", "categoria"))

    def _answer_agent_group(self, question: str) -> str:
        group = self._find_agent_group(question)
        if group is None:
            return ""
        heading = safe_text(group.get("label") or group.get("title") or "Agente") or "Agente"
        lines = [f"## {heading}", ""]
        
        # Add description if available
        if group.get("description"):
            lines.append(safe_text(group.get("description")))
            lines.append("")
        
        questions = [
            safe_text(item)
            for item in group.get("questions", ())
        ]
        for idx, item in enumerate(questions, start=1):
            if item:
                lines.append(f"{idx}. {self._inline_prompt(item)}")
        lines.append("")
        lines.append(safe_text("Clique em uma pergunta para copiar, cole no campo de mensagem e envie."))
        lines.append("Ou use `Mostrar perguntas disponíveis`.")
        return self._finalize_output("\n".join(lines).strip())

    def _intent_group_label(self, question: str) -> str:
        group = self._find_agent_group(question)
        if group is None:
            return "Não reconhecido"
        return safe_text(group.get("label") or group.get("title") or "Não reconhecido")

    def _out_of_scope_guidance(self) -> str:
        return (
            "Posso ajudar com vendas, produtos, concorrência, oportunidades ou auditoria da base. "
            "Tente uma pergunta como: `Quais foram os produtos mais vendidos no último mês?`"
        )

    def _canonicalize_deterministic_question(self, question: str) -> str:
        q = self._normalize_text(question)
        mappings = [
            (("ranking de produtos", "produtos mais vendidos", "top produtos"), "Quais foram os produtos mais vendidos no último mês?"),
            (("ranking de clientes", "clientes que mais compraram", "top clientes"), "Quais clientes mais compraram Aquafast?"),
            (("evolucao de vendas", "vendas por mes"), "Mostre a evolução de vendas da Aquafast por mês."),
            (("vendas por estado", "vendas por uf", "melhor desempenho de vendas"), "Quais estados têm melhor desempenho de vendas?"),
            (("compare a aquafast", "principais concorrentes", "concorrentes"), "Compare a Aquafast com os principais concorrentes."),
            (("market share", "participacao de mercado", "share"), "Compare a Aquafast com os principais concorrentes."),
            (("sem subgrupo", "dados inconsistentes", "inconsistencia"), "Existem produtos sem subgrupo ou com dados inconsistentes?"),
            (("oportunidade de crescimento", "potencial de crescimento", "lacuna"), "Quais produtos têm maior oportunidade de crescimento?"),
            (("resumo executivo", "performance comercial"), "Mostre um resumo executivo da performance comercial."),
        ]
        for aliases, canonical in mappings:
            if any(a in q for a in aliases):
                return canonical
        return question

    def _log_agent_query(
        self,
        *,
        group: str,
        route: str,
        mode: str,
        started_at: float,
        status: str,
        rows: Any = None,
        error: str | None = None,
    ) -> None:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "agent": safe_text(group) or "Nao reconhecido",
            "route": route,
            "mode": mode,
            "duration_ms": int((time.time() - started_at) * 1000),
            "status": status,
            "rows": int(rows) if isinstance(rows, int) else (int(rows) if isinstance(rows, float) else None),
        }
        if error:
            payload["error"] = safe_text(error)[:160]
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        for path in (
            Path("/workspace/logs/agent_queries.log"),
            Path("/app/backend/data/logs/agent_queries.log"),
            Path("/app/backend/logs/agent_queries.log"),
            Path("/tmp/agent_queries.log"),
            Path(r"C:\xampp\htdocs\scantech\logs\agent_queries.log"),
        ):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                break
            except Exception:
                continue

    def _format_metric(self, value: float, metric_col: str | None) -> str:
        metric = (metric_col or "").lower()
        if any(k in metric for k in ["receita", "faturamento", "valor_total", "valor total"]):
            return f"R$ {self._format_ptbr_number(value)}"
        if value.is_integer():
            return self._format_ptbr_number(int(value))
        return self._format_ptbr_number(value)

    def _format_ptbr_number(self, value: float | int) -> str:
        if isinstance(value, int):
            return f"{value:,}".replace(",", ".")
        if float(value).is_integer():
            return f"{int(value):,}".replace(",", ".")
        text = f"{float(value):,.2f}"
        return text.replace(",", "X").replace(".", ",").replace("X", ".")

    def _deterministic_summary(self, question: str, columns: list[str], rows: list[list[Any]]) -> str:
        if not rows:
            return "Nenhum resultado encontrado para essa consulta."

        metric_col = self._pick_metric_column(question, columns, rows)
        label_col = self._pick_label_column(columns, rows, metric_col)
        if not metric_col or metric_col not in columns:
            return "Resultado retornado. Veja a tabela abaixo."

        metric_idx = columns.index(metric_col)
        label_idx = columns.index(label_col) if label_col in columns else 0

        if len(rows) == 1:
            row = rows[0]
            metric_value = self._as_float(row[metric_idx])
            if metric_value is not None:
                formatted = self._format_metric(metric_value, metric_col)
                if label_col in columns and label_col != metric_col:
                    label_value = str(row[label_idx])
                    return f"{label_value}: {formatted}"
                return f"{metric_col}: {formatted}"

        points = []
        for row in rows:
            m = self._as_float(row[metric_idx])
            if m is None:
                continue
            points.append((str(row[label_idx]), m))

        if not points:
            return "Resultado retornado. Veja a tabela abaixo."

        points.sort(key=lambda x: x[1], reverse=True)
        total = sum(v for _, v in points)
        top = points[:3]
        lines = []
        lines.append(f"Metricas: `{metric_col}` (ordenado desc).")
        lines.append("Top 3:")
        for i, (name, v) in enumerate(top, start=1):
            lines.append(f"{i}. {name} - {self._format_metric(v, metric_col)}")
        if total > 0 and len(points) >= 3:
            share = sum(v for _, v in top) / total * 100.0
            lines.append(f"Participacao do top 3 no total listado: {share:.1f}%")
        return "\n".join(lines)

    def _source_note_from_result(self, question: str, result: dict[str, Any]) -> str:
        note = str(result.get("source_note", "") or "").strip()
        if note:
            return note

        title = str(result.get("title", "") or "")
        sql = str(result.get("sql", "") or "")
        text = self._normalize_text(" ".join([question, title, sql]))

        if "potencial de venda" in text or "maior potencial" in text:
            return (
                "Fonte: `top_produtos_categoria`. "
                "A consulta usa a presenca em PDVs e o volume em caixas como proxy de potencial de venda."
            )
        if any(
            term in text
            for term in [
                "lojas com concorrente sem aquafast",
            ]
        ):
            return (
                "Fonte: `lojas_com_concorrente_sem_aquafast`. "
                "A consulta usa PDV_ID como chave principal e expÃµe `status_loja` quando a ligaÃƒÂ§ÃƒÂ£o nao existir."
            )
        if any(
            term in text
            for term in [
                "concorrentes por categoria",
                "share aquafast por categoria",
                "top concorrentes por cidade",
                "concorrentes em crescimento 90 dias",
            ]
        ):
            return (
                "Fonte: views deterministicas de concorrencia. "
                "A consulta usa o universo do mercado carregado e separa Aquafast de concorrentes sem chamar LLM."
            )
        if any(term in text for term in ["maior concorrente", "concorrente", "concorrentes", "concorrencia", "competidor", "competidores"]):
            return (
                "Fonte: `ms_mercado_aquafast`. "
                "A consulta compara os fabricantes do mercado da categoria e exclui a Aquafast para apontar concorrentes."
            )
        if any(term in text for term in ["market share", "participacao", "share"]):
            return (
                "Fonte: `ms_mercado_aquafast`. "
                "A consulta mede a participacao de cada fabricante dentro do mercado da categoria."
            )
        if any(term in text for term in ["ponto de venda", "pontos de venda", "loja", "lojas", "pdv"]):
            return (
                "Fonte: `ranking_clientes`. "
                "A consulta conta as lojas/PDVs que aparecem com venda Aquafast no periodo carregado."
            )
        if any(term in text for term in ["produto por categoria", "categoria", "litragem", "mix"]):
            return (
                "Fonte: `top_produtos_categoria`. "
                "A consulta cruza o portfolio Aquafast com caixas para enxergar o mix por categoria, "
                "consolidando pelo mapeamento oficial de `SUBGRUPO_CIGAM`."
            )
        if any(term in text for term in ["vendas por mes", "vendas por mÃƒÂªs", "mensal", "serie mensal", "sÃƒÂ©rie mensal"]):
            return (
                "Fonte: `vendas_por_mes`. "
                "A consulta consolida caixas e receita ao longo do tempo para mostrar tendencia mensal."
            )
        if any(term in text for term in ["vendas por estado", "estado", "uf"]):
            return (
                "Fonte: `vendas_caixas_estado`. "
                "A consulta cruza as vendas Aquafast com a UF para mostrar distribuicao geografica."
            )
        if any(term in text for term in ["top produtos", "ranking produtos", "mais vendidos", "receita por produto", "volume de vendas"]):
            return (
                "Fonte: `ranking_produtos`. "
                "A consulta lista os produtos Aquafast com maior volume em caixas e receita, "
                "consolidando pelo mapeamento oficial de `SUBGRUPO_CIGAM`."
            )
        if any(term in text for term in ["subgrupo cigam", "padronizacao", "padronizaÃ§Ã£o", "nao casam com o portfolio", "nao casam com o portifolio"]):
            return (
                "Fonte: `auditoria_produtos_sem_subgrupo_cigam`. "
                "A consulta lista os produtos Aquafast sem correspondencia no portfolio e sugere `SUBGRUPO_CIGAM` apenas quando a similaridade e transparente."
            )
        if any(term in text for term in ["historico de consultas", "historico consultas", "ultimas consultas", "quais relatorios eu consultei"]):
            return (
                "Fonte: `aquafast_query_history`. "
                "A consulta mostra as 20 consultas deterministicas mais recentes registradas pelo Scanntech Analyst."
            )
        if any(term in text for term in ["clientes", "lojas", "churn", "compra"]):
            return (
                "Fonte: `ranking_clientes`. "
                "A consulta resume as lojas Aquafast por caixas vendidas, receita e recorrencia."
            )
        return "Fonte: consulta local no DuckDB usando as views semanticas da Aquafast."

    def _history_block_from_result(self, question: str, result: dict[str, Any]) -> str:
        report_name = str(result.get("history_report_name", "") or "").strip()
        timestamp = str(result.get("history_timestamp", "") or "").strip()
        if not report_name and not timestamp:
            return ""
        lines = ["Historico desta consulta:", f"- relatorio: {report_name or 'desconhecido'}", f"- pergunta: {question or ''}"]
        if timestamp:
            lines.append(f"- executado em: {timestamp}")
        return "\n".join(lines)

    def _ensure_select_only(self, sql: str) -> str:
        normalized = self._normalize_text(sql)
        if not re.match(r"^(select|with|show|describe)\b", normalized):
            raise ValueError("SQL gerado nao parece ser uma consulta somente leitura.")
        return sql.strip().rstrip(";")

    def _wrap_sql_for_safe_rows(self, sql: str, *, for_export: bool) -> str:
        """
        Evita SELECT sem LIMIT puxando milhoes de linhas (lento no DuckDB e no chat).
        Exportacao Excel usa so o teto da API (EXPORT); nao aplica este wrap.
        """
        if for_export:
            return sql.strip().rstrip(";")
        s = sql.strip().rstrip(";")
        low = s.lower()
        if not (low.startswith("select") or low.startswith("with")):
            return s
        collapsed = re.sub(r"\s+", " ", low).strip()
        if re.search(r"\blimit\s+\d+(\s+offset\s+\d+)?\s*$", collapsed):
            return s
        cap = max(1, int(self.valves.SQL_SAFETY_ROW_CAP))
        return f"SELECT * FROM ({s}) AS _aquafast_safe LIMIT {cap}"

    async def _generate_sql(self, body: dict, question: str, schema_text: str, previous_sql: str | None = None) -> str:
        messages = body.get("messages", [])[-int(self.valves.SQL_CONTEXT_MESSAGES) :]
        user_context = []
        for message in messages:
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = self._content_to_text(message.get("content", ""))
            if not content:
                continue
        # evita mandar tabelas gigantes pro modelo
            if "| --- |" in content or content.count("\n|") > 5:
                continue
            user_context.append(f"{role.upper()}: {content[:600]}")
        context_text = "\n".join(user_context) if user_context else "sem contexto adicional"
        previous_sql_text = f"\n\nSQL anterior (para modificar/continuar se fizer sentido):\n```sql\n{previous_sql}\n```" if previous_sql else ""

        prompt = [
            {
                "role": "system",
                "content": (
                    "Voce e um analista de dados especializado no portfolio Aquafast sobre DuckDB. "
                    "A regra padrao e analisar apenas o mercado Aquafast, usando caixas como base de negocio e evitando a leitura do universo bruto da Scanntech. "
                    "Para perguntas operacionais de resultado, ranking e evolucao, considere apenas os itens Aquafast (is_aquafast = 1). "
                    "Use o universo completo da categoria apenas quando a pergunta for explicitamente de concorrencia, market share ou comparacao de mercado. "
                    "Gere apenas SQL valido e somente leitura. "
                    "Use apenas tabelas, views e colunas existentes no schema fornecido. "
                    "Responda com um unico bloco de codigo Markdown ```sql ... ``` e nada mais. "
                    "Se a pergunta pedir top 20, use LIMIT 20. "
                    "Sempre termine consultas exploratorias com LIMIT (ex.: 200 ou 500) quando nao houver agregacao que ja reduza o resultado. "
                    "Prefira as views ranking_clientes, ranking_produtos, vendas_por_mes, ms_mercado_aquafast, vendas_caixas_estado e top_produtos_categoria quando elas atenderem a pergunta. "
                    "Nao invente colunas. Nao use INSERT, UPDATE, DELETE, DROP ou ALTER."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Schema DuckDB/Aquafast:\n{schema_text}\n\n"
                    f"Pergunta do usuario: {question}\n\n"
                    f"Contexto recente:\n{context_text}{previous_sql_text}"
                ),
            },
        ]

        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": int(self.valves.SQL_MAX_TOKENS)},
        }

        sql_timeout = min(
            float(self.valves.OLLAMA_TIMEOUT_SECONDS),
            float(self.valves.OLLAMA_SQL_TIMEOUT_SECONDS),
        )
        async with httpx.AsyncClient(timeout=sql_timeout) as client:
            response = await client.post(f"{self.valves.OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = str(message.get("content", "")).strip()
        sql = self._extract_sql_block(content)
        if not sql:
            raise ValueError("O modelo nao retornou SQL em formato valido.")
        return self._ensure_select_only(sql)

    async def _repair_sql(self, body: dict, question: str, schema_text: str, bad_sql: str, error_text: str) -> str:
        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Voce corrige SQL para DuckDB. Retorne apenas um bloco de codigo Markdown com a consulta corrigida. "
                        "Use somente leitura."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Schema:\n{schema_text}\n\n"
                        f"Pergunta: {question}\n\n"
                        f"SQL com erro:\n```sql\n{bad_sql}\n```\n\n"
                        f"Erro retornado pelo DuckDB:\n{error_text}"
                    ),
                },
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": int(self.valves.SQL_MAX_TOKENS)},
        }

        sql_timeout = min(
            float(self.valves.OLLAMA_TIMEOUT_SECONDS),
            float(self.valves.OLLAMA_SQL_TIMEOUT_SECONDS),
        )
        async with httpx.AsyncClient(timeout=sql_timeout) as client:
            response = await client.post(f"{self.valves.OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = str(message.get("content", "")).strip()
        sql = self._extract_sql_block(content)
        if not sql:
            raise ValueError("Nao foi possivel corrigir o SQL.")
        return self._ensure_select_only(sql)

    async def _summarize_result(self, question: str, sql: str, markdown_table: str) -> str:
        # Para performance, nao envie tabela completa. Use apenas as primeiras linhas.
        snippet_lines = markdown_table.splitlines()[:14]
        snippet = "\n".join(snippet_lines)
        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": [
                {
                    "role": "system",
                "content": (
                "Voce e o Aquafast IA. Explique o resultado de forma objetiva, executiva e honesta. "
                "Nao invente numeros. Use exatamente os valores fornecidos na tabela."
            ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Pergunta: {question}\n\n"
                        f"SQL executado:\n```sql\n{sql}\n```\n\n"
                        f"Resultado (amostra):\n{snippet}\n\n"
                        "Resuma o que o resultado mostra em portugues, em 3 a 6 linhas, "
                        "e destaque a principal leitura de negocio."
                    ),
                },
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": int(self.valves.MAX_MODEL_TOKENS)},
        }

        async with httpx.AsyncClient(timeout=self.valves.OLLAMA_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{self.valves.OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = str(message.get("content", "")).strip()
        return content or "Analise concluida."

    def _http_status_error_message(self, exc: httpx.HTTPStatusError) -> str:
        detail = ""
        request_url = ""
        if exc.response is not None:
            try:
                detail = exc.response.text.strip()
            except Exception:
                detail = ""
            try:
                request_url = str(exc.request.url)
            except Exception:
                request_url = ""
        if len(detail) > 800:
            detail = detail[:797] + "..."
        code = exc.response.status_code if exc.response is not None else "?"
        lower_detail = detail.lower()
        lower_url = request_url.lower()
        if code == 404 and ("model" in lower_detail and "not found" in lower_detail):
            model_name = safe_output_text(getattr(self.valves, "CHAT_MODEL", "")).strip() or "llama3.2:3b"
            backend_hint = "Ollama" if "11434" in lower_url or "/api/chat" in lower_url else "modelo de fallback"
            return safe_output_text(
                f"Nao consegui concluir esta consulta porque o {backend_hint} nao esta disponivel.\n\n"
                f"Modelo configurado: `{model_name}`.\n"
                "Perguntas predefinidas continuam funcionando pela API deterministica. "
                "Para fallback por chat, carregue o modelo no Ollama."
            )
        return safe_output_text(
            f"Erro HTTP {code} na API Aquafast.\n\n"
            f"{detail or '(sem detalhe no corpo da resposta)'}\n\n"
            "Confirme se o servico da API esta no ar, a URL em Valves (ex.: `http://scanntech-api:8000`) "
            "bate com o `docker compose` e se o arquivo `aquafast_scanntech.duckdb` existe no container."
        )
    def _build_analysis_response(self, question: str, result: dict[str, Any], sql_hint: str) -> str:
        summary = safe_output_text(self._deterministic_summary(question, result.get("columns", []), result.get("rows", [])))
        source_note = safe_output_text(self._source_note_from_result(question, result))
        markdown = safe_output_text(result.get("markdown", ""))
        history_block = safe_output_text(self._history_block_from_result(question, result))
        cap_note = ""
        if result.get("truncated"):
            cap = result.get("row_cap")
            cap_note = safe_output_text(
                f"\n\n_Amostra limitada pela API ({cap} linhas no maximo). "
                "Refine a pergunta com filtros (mes, cliente, produto) ou use LIMIT menor no SQL para ver tudo no Excel._"
            )
        return self._finalize_output("\n".join(
            [
                safe_output_text("## Análise Aquafast"),
                "",
                summary,
                "",
                source_note,
                "",
                markdown,
                "",
                safe_output_text(f"_Linhas retornadas: {result.get('row_count', 0)}_"),
                "",
                history_block,
                cap_note,
            ]
        ).strip())

    async def _try_legacy_ask(self, question: str) -> str | None:
        """Respostas instantâneas via POST /ask quando a pergunta casa com legacy_question_to_sql na API."""
        base = self.valves.API_BASE_URL.rstrip("/")
        url = f"{base}/ask"
        timeout = min(float(self.valves.LEGACY_ASK_TIMEOUT_SECONDS), float(self.valves.TIMEOUT_SECONDS))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json={"question": question.strip()})
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except Exception:
            return None
        if not data.get("ok"):
            return None
        sql_hint = str(data.get("sql", "") or "")
        return self._build_analysis_response(question, data, sql_hint)

    async def _run_data_pipeline(
        self,
        body: dict,
        question: str,
        export: bool = False,
        chart: bool = False,
        sql_override: str | None = None,
        intent_group: str | None = None,
    ) -> str:
        started = time.time()
        group = intent_group or self._intent_group_label(question)
        if not export and sql_override is None:
            legacy_reply = await self._try_legacy_ask(question)
            if legacy_reply is not None:
                self._log_agent_query(group=group, route="/ask", mode="deterministic", started_at=started, status="ok")
                return legacy_reply

        schema = await self._fetch_schema()
        schema_text = schema.get("summary_text", "")
        previous_sql = self._find_last_sql(body)
        sql = sql_override or await self._generate_sql(body, question, schema_text, previous_sql=previous_sql)
        validation_error = self._validate_sql_against_question(question, sql)
        if validation_error:
            # tenta uma vez regenerar com instrucao extra, sem depender do usuario.
            sql = await self._generate_sql(
                body,
                f"{question}\n\nIMPORTANTE: {validation_error}",
                schema_text,
                previous_sql=previous_sql,
            )

        try:
            if export:
                result = await self._export_sql(sql, "Exportacao Excel")
                download_url = result.get("download_url", "")
                self._log_agent_query(
                    group=group,
                    route="/export",
                    mode="deterministic",
                    started_at=started,
                    status="ok",
                    rows=result.get("row_count"),
                )
                return "\n".join(
                    [
                        "## Exportacao Excel",
                        "",
                        "Arquivo Excel gerado com sucesso.",
                        f"[Baixar o arquivo]({download_url})",
                        "",
                        f"_Consulta executada: `{result.get('sql', sql)}`_",
                        f"_Linhas exportadas: {result.get('row_count', 0)}_",
                    ]
                )

            sql_for_api = self._wrap_sql_for_safe_rows(sql, for_export=False)
            result = await self._query_sql(sql_for_api, "Analise Aquafast")
        except httpx.HTTPStatusError as exc:
            detail = str(exc.response.text) if exc.response is not None else ""
            if exc.response is not None and exc.response.status_code == 400:
                try:
                    repaired_sql = await self._repair_sql(body, question, schema_text, sql, detail)
                    if export:
                        result = await self._export_sql(repaired_sql, "Exportacao Excel")
                        download_url = result.get("download_url", "")
                        return "\n".join(
                            [
                                "## Exportacao Excel",
                                "",
                                "Arquivo Excel gerado com sucesso.",
                                f"[Baixar o arquivo]({download_url})",
                                "",
                                f"_Consulta executada: `{result.get('sql', repaired_sql)}`_",
                                f"_Linhas exportadas: {result.get('row_count', 0)}_",
                            ]
                        )
                    sql = repaired_sql
                    sql_for_api = self._wrap_sql_for_safe_rows(sql, for_export=False)
                    result = await self._query_sql(sql_for_api, "Analise Aquafast")
                except httpx.TimeoutException:
                    return (
                        "Timeout ao corrigir ou reexecutar o SQL (Ollama ou API demorou demais). "
                        "Tente de novo em instantes; perguntas comuns respondem direto pela API sem LLM."
                    )
                except httpx.HTTPStatusError as exc2:
                    return self._http_status_error_message(exc2)
                except Exception as fix_exc:
                    fix_msg = str(fix_exc).strip()
                    if len(fix_msg) > 400:
                        fix_msg = fix_msg[:397] + "..."
                    orig = detail.strip()
                    if len(orig) > 500:
                        orig = orig[:497] + "..."
                    return (
                        "Nao consegui executar a consulta apos tentar corrigir o SQL automaticamente.\n\n"
                        f"Resposta da API na primeira tentativa: {orig or '(vazio)'}\n\n"
                        f"Erro na segunda tentativa: {fix_msg}"
                    )
            else:
                self._log_agent_query(
                    group=group,
                    route="/query",
                    mode="deterministic",
                    started_at=started,
                    status="error",
                    error=f"http_status_{exc.response.status_code if exc.response is not None else '?'}",
                )
                return self._finalize_output(self._http_status_error_message(exc))

        if export:
            # defensive fallback; normally handled earlier
            download_url = result.get("download_url", "")
            self._log_agent_query(
                group=group,
                route="/export",
                mode="deterministic",
                started_at=started,
                status="ok",
                rows=result.get("row_count"),
            )
            return "\n".join(
                [
                    "## Exportacao Excel",
                    "",
                    "Arquivo Excel gerado com sucesso.",
                    f"[Baixar o arquivo]({download_url})",
                    "",
                    f"_Consulta executada: `{result.get('sql', sql)}`_",
                    f"_Linhas exportadas: {result.get('row_count', 0)}_",
                ]
            )

        self._log_agent_query(
            group=group,
            route="/query",
            mode="deterministic",
            started_at=started,
            status="ok",
            rows=result.get("row_count"),
        )
        return self._build_analysis_response(question, result, sql)

    def _render_chart(self, title: str, columns: list[str], rows: list[list[Any]]) -> str:
        if not rows:
            return "_Nenhum dado encontrado para montar o grafico._"

        labels = ["cliente", "produto", "mes", "periodo", "categoria", "name"]
        values = ["valor_total", "receita_total", "receita", "total_vendas", "total_pedidos", "qtd", "quantity"]

        lower_map = {column.lower(): column for column in columns}
        label_col = next((original for key in labels for lower, original in lower_map.items() if key == lower or key in lower), None)
        value_col = next((original for key in values for lower, original in lower_map.items() if key == lower or key in lower), None)

        if not label_col and columns:
            label_col = columns[0]
        if not value_col and len(columns) > 1:
            value_col = columns[1]

        if not label_col or not value_col:
            return "_Nao foi possivel identificar colunas para o grafico._"

        label_idx = columns.index(label_col)
        value_idx = columns.index(value_col)
        points = []
        for row in rows[:12]:
            label = str(row[label_idx])
            value = row[value_idx]
            try:
                numeric = float(value)
            except Exception:
                continue
            points.append((label, numeric))

        if not points:
            return "_Nao encontrei valores numericos suficientes para montar o grafico._"

        max_value = max(v for _, v in points)
        if max_value <= 0:
            max_value = 1.0

        chart_lines = [
            "```mermaid",
            "xychart-beta",
            f'    title "{title}"',
            f'    x-axis {json.dumps([label for label, _ in points], ensure_ascii=False)}',
            f'    y-axis "{value_col}" 0 --> {int(max_value * 1.1) if max_value > 0 else 1}',
            f"    bar {json.dumps([round(value, 2) for _, value in points], ensure_ascii=False)}",
            "```",
        ]
        return self._finalize_output("\n".join(chart_lines))

    def _answer_available_questions(self) -> str:
        lines = ["# Perguntas disponíveis", ""]
        for group in AGENT_GROUPS:
            label = safe_text(group.get("label") or group.get("title") or "Categoria")
            lines.append(f"## {label}")
            for item in group.get("questions", ()):
                item_text = safe_text(item)
                if item_text:
                    lines.append(f"- {item_text}")
            lines.append("")
        return self._finalize_output("\n".join(lines).strip())

    def _find_agent_group(self, question: str) -> dict[str, Any] | None:
        q = self._normalize_text(question)
        if not q:
            return None
        best_group = None
        best_score = 0
        for group in AGENT_GROUPS:
            aliases = {
                self._normalize_text(str(group.get("title", ""))),
                self._normalize_text(str(group.get("label", ""))),
            }
            aliases.update(self._normalize_text(alias) for alias in group.get("aliases", ()))
            if q in aliases:
                return group
            score = 0
            for kw in GROUP_INTENT_KEYWORDS.get(str(group.get("label", "")), ()):
                token = self._normalize_text(kw)
                if token and token in q:
                    score += 1
            if score > best_score:
                best_score = score
                best_group = group
        return best_group if best_score > 0 else None

    def _is_agent_request(self, question: str) -> bool:
        q = self._normalize_text(question)
        if not q:
            return False
        titles = {self._normalize_text(str(g.get("title", ""))) for g in AGENT_GROUPS}
        labels = {self._normalize_text(str(g.get("label", ""))) for g in AGENT_GROUPS}
        if q in titles or q in labels:
            return True
        return any(token in q for token in ("agente", "categoria"))

    def _answer_agent_group(self, question: str) -> str:
        group = self._find_agent_group(question)
        if group is None:
            return ""
        heading = safe_text(group.get("label") or group.get("title") or "Agente") or "Agente"
        lines = [f"## {heading}", ""]
        
        # Add description if available
        if group.get("description"):
            lines.append(safe_text(group.get("description")))
            lines.append("")
        
        questions = [
            safe_text(item)
            for item in group.get("questions", ())
        ]
        for idx, item in enumerate(questions, start=1):
            if item:
                lines.append(f"{idx}. {self._inline_prompt(item)}")
        lines.append("")
        lines.append(safe_text("Clique em uma pergunta para copiar, cole no campo de mensagem e envie."))
        lines.append("Ou use `Mostrar perguntas disponíveis`.")
        return self._finalize_output("\n".join(lines).strip())

    def _intent_group_label(self, question: str) -> str:
        group = self._find_agent_group(question)
        if group is None:
            return "Não reconhecido"
        return safe_text(group.get("label") or group.get("title") or "Não reconhecido")

    def _out_of_scope_guidance(self) -> str:
        return (
            "Posso ajudar com vendas, produtos, concorrência, oportunidades ou auditoria da base. "
            "Tente uma pergunta como: `Quais foram os produtos mais vendidos no último mês?`"
        )

    def _canonicalize_deterministic_question(self, question: str) -> str:
        q = self._normalize_text(question)
        mappings = [
            (("ranking de produtos", "produtos mais vendidos", "top produtos"), "Quais foram os produtos mais vendidos no último mês?"),
            (("ranking de clientes", "clientes que mais compraram", "top clientes"), "Quais clientes mais compraram Aquafast?"),
            (("evolucao de vendas", "vendas por mes"), "Mostre a evolução de vendas da Aquafast por mês."),
            (("vendas por estado", "vendas por uf", "melhor desempenho de vendas"), "Quais estados têm melhor desempenho de vendas?"),
            (("compare a aquafast", "principais concorrentes", "concorrentes"), "Compare a Aquafast com os principais concorrentes."),
            (("market share", "participacao de mercado", "share"), "Compare a Aquafast com os principais concorrentes."),
            (("sem subgrupo", "dados inconsistentes", "inconsistencia"), "Existem produtos sem subgrupo ou com dados inconsistentes?"),
            (("oportunidade de crescimento", "potencial de crescimento", "lacuna"), "Quais produtos têm maior oportunidade de crescimento?"),
            (("resumo executivo", "performance comercial"), "Mostre um resumo executivo da performance comercial."),
        ]
        for aliases, canonical in mappings:
            if any(a in q for a in aliases):
                return canonical
        return question

    def _log_agent_query(
        self,
        *,
        group: str,
        route: str,
        mode: str,
        started_at: float,
        status: str,
        rows: Any = None,
        error: str | None = None,
    ) -> None:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "agent": safe_text(group) or "Nao reconhecido",
            "route": route,
            "mode": mode,
            "duration_ms": int((time.time() - started_at) * 1000),
            "status": status,
            "rows": int(rows) if isinstance(rows, int) else (int(rows) if isinstance(rows, float) else None),
        }
        if error:
            payload["error"] = safe_text(error)[:160]
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        for path in (
            Path("/workspace/logs/agent_queries.log"),
            Path("/app/backend/data/logs/agent_queries.log"),
            Path("/app/backend/logs/agent_queries.log"),
            Path("/tmp/agent_queries.log"),
            Path(r"C:\xampp\htdocs\scantech\logs\agent_queries.log"),
        ):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                break
            except Exception:
                continue

    def _format_metric(self, value: float, metric_col: str | None) -> str:
        metric = self._normalize_text(metric_col or "")
        if any(k in metric for k in ["receita", "faturamento", "valor total", "valor_total"]):
            return f"R$ {self._format_ptbr_number(value)}"
        if metric in {"caixa", "caixas", "caixas_vendidas", "qtd_caixa", "qtd_caixas", "total_caixas", "quantidade_caixas"} or metric.endswith("_caixas"):
            rounded = int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            return self._format_ptbr_number(rounded)
        if value.is_integer():
            return self._format_ptbr_number(int(value))
        return self._format_ptbr_number(value)

    def _deterministic_summary(self, question: str, columns: list[str], rows: list[list[Any]]) -> str:
        if not rows:
            return "Nenhum resultado encontrado para essa consulta."

        metric_col = self._pick_metric_column(question, columns, rows)
        label_col = self._pick_label_column(columns, rows, metric_col)
        if not metric_col or metric_col not in columns:
            return "Resultado retornado. Veja a tabela abaixo."

        metric_idx = columns.index(metric_col)
        label_idx = columns.index(label_col) if label_col in columns else 0

        if len(rows) == 1:
            row = rows[0]
            metric_value = self._as_float(row[metric_idx])
            if metric_value is not None:
                formatted = self._format_metric(metric_value, metric_col)
                if label_col in columns and label_col != metric_col:
                    label_value = self._safe_text(row[label_idx], "Resultado")
                    return f"{label_value}: {formatted}"
                return f"{metric_col}: {formatted}"

        points = []
        for row in rows:
            m = self._as_float(row[metric_idx])
            if m is None:
                continue
            points.append((self._safe_text(row[label_idx], f"Item {len(points) + 1}"), m))

        if not points:
            return "Resultado retornado. Veja a tabela abaixo."

        points.sort(key=lambda x: x[1], reverse=True)
        total = sum(v for _, v in points)
        top = points[:3]
        lines = []
        lines.append(f"Metricas: `{metric_col}` (ordenado desc).")
        lines.append("Top 3:")
        for i, (name, v) in enumerate(top, start=1):
            lines.append(f"{i}. {name} - {self._format_metric(v, metric_col)}")
        if total > 0 and len(points) >= 3:
            share = sum(v for _, v in top) / total * 100.0
            lines.append(f"Participacao do top 3 no total listado: {share:.1f}%")
        return "\n".join(lines)

    def _build_analysis_response(
        self,
        question: str,
        result: dict[str, Any],
        sql_hint: str,
        summary_override: str | None = None,
    ) -> str:
        route = self._safe_text(
            result.get("route")
            or result.get("intent")
            or result.get("report_name")
            or "",
            "",
        )
        result_title = self._safe_text(result.get("title", ""), "")
        group_label = self._safe_text(result.get("group", ""), "")
        if self._normalize_text(group_label) == "nao reconhecido":
            group_label = ""
        if not group_label:
            group_label = ROUTE_TO_LABEL.get(route, "")
        if not group_label:
            group_label = result_title
        if not group_label:
            group_label = self._intent_group_label(question)
        if self._normalize_text(group_label) == "nao reconhecido":
            group_label = ROUTE_TO_LABEL.get(route, "") or result_title or "Resultado"
        if not group_label:
            group_label = "Resultado"
        summary = self._safe_text(summary_override, "")
        if not summary:
            summary = self._safe_text(
                self._deterministic_summary(question, result.get("columns", []), result.get("rows", [])),
                "Resultado retornado. Veja a tabela abaixo.",
            )
        source_note = self._safe_text(
            self._source_note_from_result(question, result),
            "Fonte: consulta local no DuckDB usando as views semanticas da Aquafast.",
        )
        markdown = self._safe_text(result.get("markdown", ""), "_Nenhum resultado encontrado._")
        cap_note = ""
        if result.get("truncated"):
            cap = result.get("row_cap")
            cap_note = safe_output_text(
                f"\n\n_Amostra limitada pela API ({cap} linhas no maximo). "
                "Refine a pergunta com filtros (mes, cliente, produto) ou use LIMIT menor no SQL para ver tudo no Excel._"
            )
        questions_block = self._format_questions_block(limit=6)
        next_step = (
            "Próximo passo sugerido: refine com período, UF, cliente ou categoria para uma leitura mais acionável."
        )
        return self._finalize_output("\n".join(
            [
                safe_output_text(f"## {group_label}"),
                "",
                safe_output_text("### Interpretação"),
                summary,
                "",
                safe_output_text("### Fonte/escopo consultado"),
                source_note,
                "",
                safe_output_text("### Resultado em tabela"),
                markdown,
                "",
                safe_output_text(f"_Linhas retornadas: {result.get('row_count', 0)}_"),
                cap_note,
                "",
                safe_output_text(next_step),
                "",
                questions_block,
            ]
        ).strip())

    def _render_chart(self, title: str, columns: list[str], rows: list[list[Any]]) -> str:
        if not rows:
            return "_Nenhum dado encontrado para montar o grafico._"

        labels = ["cliente", "produto", "mes", "periodo", "categoria", "name"]
        values = ["valor_total", "receita_total", "receita", "total_vendas", "total_pedidos", "qtd", "quantity"]

        lower_map = {column.lower(): column for column in columns}
        label_col = next((original for key in labels for lower, original in lower_map.items() if key == lower or key in lower), None)
        value_col = next((original for key in values for lower, original in lower_map.items() if key == lower or key in lower), None)

        if not label_col and columns:
            label_col = columns[0]
        if not value_col and len(columns) > 1:
            value_col = columns[1]

        if not label_col or not value_col:
            return "_Nao foi possivel identificar colunas para o grafico._"

        label_idx = columns.index(label_col)
        value_idx = columns.index(value_col)
        points = []
        for row in rows[:12]:
            label = self._safe_text(row[label_idx], "Item")
            value = row[value_idx]
            try:
                numeric = float(value)
            except Exception:
                continue
            points.append((label, numeric))

        if not points:
            return "_Nao encontrei valores numericos suficientes para montar o grafico._"

        max_value = max(v for _, v in points)
        if max_value <= 0:
            max_value = 1.0

        chart_lines = [
            "```mermaid",
            "xychart-beta",
            f'    title "{self._safe_text(title, "Grafico")}"',
            f'    x-axis {json.dumps([label for label, _ in points], ensure_ascii=False)}',
            f'    y-axis "{value_col}" 0 --> {int(max_value * 1.1) if max_value > 0 else 1}',
            f"    bar {json.dumps([round(value, 2) for _, value in points], ensure_ascii=False)}",
            "```",
        ]
        return self._finalize_output("\n".join(chart_lines))

    async def pipe(self, body: dict):
        started = time.time()
        try:
            # Proteção contra fallback silencioso para modelo base (llama3.2)
            # Se o usuário selecionar llama3.2:3b em vez do pipe Scanntech Analyst,
            # isso bloqueará a resposta e instruirá o redirecionamento.
            model_name = body.get("model", "").lower()
            if "qwen" in model_name and "scanntech_analyst" not in model_name and "analyst" not in model_name:
                return self._finalize_output(
                    "⚠️ **ERRO: Modelo incorreto selecionado**\n\n"
                    "Você selecionou `llama3.2:3b` em vez de usar o pipe **Scanntech Analyst**.\n\n"
                    "**O que fazer:**\n"
                    "1. Clique no seletor de modelo no topo do chat\n"
                    "2. Procure por **\"Scanntech Analyst\"** (não por \"llama3.2:3b\")\n"
                    "3. Selecione **\"Scanntech Analyst\"**\n"
                    "4. Envie sua pergunta novamente\n\n"
                    "O Scanntech Analyst é o assistente especializado em análise dos dados Aquafast. "
                    "Usando o modelo base diretamente, você perde acesso aos dados e às análises contextualizadas."
                )

            question = self._extract_question(body)
            routing_text = question
            intent_group = self._intent_group_label(routing_text) if routing_text else "Não reconhecido"
            if not question:
                self._log_agent_query(
                    group="Não reconhecido",
                    route="pipe",
                    mode="guidance",
                    started_at=started,
                    status="ok",
                )
                return self._finalize_output("Envie uma pergunta sobre os dados da Aquafast.")

            if self._is_access_question(routing_text):
                return self._finalize_output(self._answer_access_question())

            if self._is_agent_request(routing_text):
                self._log_agent_query(
                    group=intent_group,
                    route="agent_group",
                    mode="guidance",
                    started_at=started,
                    status="ok",
                )
                return self._finalize_output(self._answer_agent_group(routing_text))

            if self._is_available_questions_request(routing_text):
                self._log_agent_query(
                    group="Navegação",
                    route="available_questions",
                    mode="guidance",
                    started_at=started,
                    status="ok",
                )
                return self._finalize_output(self._answer_available_questions())

            route_hint = self._looks_like_data_question(routing_text)
            if route_hint is False:
                guidance = self._out_of_scope_guidance()
                self._log_agent_query(
                    group="Não reconhecido",
                    route="out_of_scope",
                    mode="guidance",
                    started_at=started,
                    status="ok",
                )
                return self._finalize_output(guidance)

            route = self._route_for_question(routing_text)
            if route is None:
                category = await self._classify_intent_with_llm(routing_text)
                if category == "fora_de_contexto":
                    guidance = self._out_of_scope_guidance()
                    self._log_agent_query(
                        group="NÃ£o reconhecido",
                        route="out_of_scope",
                        mode="guidance",
                        started_at=started,
                        status="ok",
                    )
                    return self._finalize_output(guidance)
                route = self._route_for_question(routing_text, category)

            if route is None:
                guidance = self._out_of_scope_guidance()
                self._log_agent_query(
                    group="NÃ£o reconhecido",
                    route="out_of_scope",
                    mode="guidance",
                    started_at=started,
                    status="ok",
                )
                return self._finalize_output(guidance)

            normalized_question = self._normalize_text(routing_text)
            if any(term in normalized_question for term in ("sem subgrupo", "subgrupo", "inconsistencia", "divergencia")):
                self._log_agent_query(
                    group="Auditoria de Dados",
                    route="guidance_auditoria",
                    mode="guidance",
                    started_at=started,
                    status="ok",
                )
                return self._finalize_output(
                    "Posso auditar produtos sem subgrupo e inconsistencias da base.\n\n"
                    "Para retornar o relatatorio deterministico sem depender de LLM, use uma pergunta como:\n"
                    "- `Mostre os produtos sem SUBGRUPO_CIGAM`\n"
                    "- `Auditoria produtos sem padronizacao`"
                )
            if any(term in normalized_question for term in ("oportunidade", "potencial", "lacuna", "gap")):
                self._log_agent_query(
                    group="Mapa de Oportunidades",
                    route="guidance_oportunidades",
                    mode="guidance",
                    started_at=started,
                    status="ok",
                )
                return self._finalize_output(
                    "Posso apoiar o mapeamento de oportunidades com base em volume, receita e cobertura.\n\n"
                    "Sem modelo LLM ativo, use uma pergunta deterministica como:\n"
                    "- `Quais foram os produtos mais vendidos no ultimo mes?`\n"
                    "- `Quais estados tem melhor desempenho de vendas?`\n"
                    "- `Quais clientes mais compraram Aquafast?`"
                )

            if self._is_excel_request(routing_text):
                export_result = await self._export_sql(route.sql, route.title)
                download_url = export_result.get("download_url", "")
                return self._finalize_output(
                    "\n".join(
                        [
                            f"## {route.title}",
                            "",
                            "Arquivo Excel gerado com sucesso.",
                            f"[Baixar o arquivo]({download_url})",
                            "",
                            f"_Consulta executada: `{export_result.get('sql', route.sql)}`_",
                            f"_Linhas exportadas: {export_result.get('row_count', 0)}_",
                        ]
                    ).strip()
                )

            if self._is_chart_request(routing_text):
                result = await self._query_sql(route.sql, route.title)
                chart = self._render_chart(result.get("title", route.title), result.get("columns", []), result.get("rows", []))
                return self._finalize_output(
                    "\n".join(
                        [
                            f"## {result.get('title', route.title)}",
                            "",
                            chart,
                            "",
                            result.get("markdown", ""),
                            "",
                            f"_Consulta executada: `{result.get('sql', route.sql)}`_",
                            f"_Linhas retornadas: {result.get('row_count', 0)}_",
                        ]
                    ).strip()
                )

            result = await self._query_sql(route.sql, route.title)
            return self._finalize_output(
                self._build_analysis_response(routing_text, result, route.sql)
            )

            normalized_question = self._normalize_text(routing_text)
            if any(term in normalized_question for term in ("sem subgrupo", "subgrupo", "inconsistencia", "divergencia")):
                self._log_agent_query(
                    group="Auditoria de Dados",
                    route="guidance_auditoria",
                    mode="guidance",
                    started_at=started,
                    status="ok",
                )
                return self._finalize_output(
                    "Posso auditar produtos sem subgrupo e inconsistências da base.\n\n"
                    "Para retornar o relatório determinístico sem depender de LLM, use uma pergunta como:\n"
                    "- `Mostre os produtos sem SUBGRUPO_CIGAM`\n"
                    "- `Auditoria produtos sem padronização`"
                )
            if any(term in normalized_question for term in ("oportunidade", "potencial", "lacuna", "gap")):
                self._log_agent_query(
                    group="Mapa de Oportunidades",
                    route="guidance_oportunidades",
                    mode="guidance",
                    started_at=started,
                    status="ok",
                )
                return self._finalize_output(
                    "Posso apoiar o mapeamento de oportunidades com base em volume, receita e cobertura.\n\n"
                    "Sem modelo LLM ativo, use uma pergunta determinística como:\n"
                    "- `Quais foram os produtos mais vendidos no último mês?`\n"
                    "- `Quais estados têm melhor desempenho de vendas?`\n"
                    "- `Quais clientes mais compraram Aquafast?`"
                )

            if self._is_excel_request(routing_text):
                last_sql = self._find_last_sql(body)
                if not last_sql and route_hint is not True:
                    return self._finalize_output(
                        "Para gerar Excel, eu preciso de uma consulta de dados antes "
                        "ou de uma pergunta com contexto de vendas, clientes, produtos ou receitas."
                    )
                return self._finalize_output(
                    await self._run_data_pipeline(body, question, export=True, sql_override=last_sql, intent_group=intent_group)
                )

            if self._is_chart_request(routing_text):
                last_sql = self._find_last_sql(body)
                if not last_sql and route_hint is not True:
                    return self._finalize_output(
                        "Para gerar um gráfico, eu preciso de uma pergunta analítica antes "
                        "ou de uma consulta anterior com dados."
                    )
                return self._finalize_output(await self._handle_chart(body, question))

            # Periodo/datas: tenta resolver de forma deterministica usando o ultimo resultado (sem chamar o modelo).
            if self._looks_like_period_question(routing_text):
                last_table = self._find_last_table(body)
                if last_table:
                    cols, rows = last_table
                    lower = [c.lower() for c in cols]
                    pick = None
                    for key in ["codigo", "cod_produto", "produto", "sku"]:
                        for i, c in enumerate(lower):
                            if key == c or key in c:
                                pick = i
                                break
                        if pick is not None:
                            break
                    if pick is not None:
                        products = [r[pick] for r in rows if r and len(r) > pick]
                        sql = self._build_period_sql_for_products(products)
                        return self._finalize_output(
                            await self._run_data_pipeline(body, question, export=False, sql_override=sql, intent_group=intent_group)
                        )
                    # pick month column
                    pick_mes = None
                    for key in ["mes", "mês"]:
                        for i, c in enumerate(lower):
                            if key == c or key in c:
                                pick_mes = i
                                break
                        if pick_mes is not None:
                            break
                    if pick_mes is not None:
                        months = [r[pick_mes] for r in rows if r and len(r) > pick_mes]
                        sql = self._build_clients_sql_for_months(months)
                        return self._finalize_output(
                            await self._run_data_pipeline(body, question, export=False, sql_override=sql, intent_group=intent_group)
                        )

            # Follow-up de clientes (ex.: "essas vendas correspondem a quais clientes?") usando o ultimo resultado com meses.
            if self._looks_like_client_question(routing_text):
                last_table = self._find_last_table(body)
                if last_table:
                    cols, rows = last_table
                    lower = [c.lower() for c in cols]
                    pick_mes = None
                    for key in ["mes", "mês"]:
                        for i, c in enumerate(lower):
                            if key == c or key in c:
                                pick_mes = i
                                break
                        if pick_mes is not None:
                            break
                    if pick_mes is not None:
                        months = [r[pick_mes] for r in rows if r and len(r) > pick_mes]
                        sql = self._build_clients_sql_for_months(months)
                        return self._finalize_output(
                            await self._run_data_pipeline(body, question, export=False, sql_override=sql, intent_group=intent_group)
                        )

            # Follow-up de cidades dos clientes retornados na ultima tabela.
            if self._looks_like_city_question(routing_text):
                last_table = self._find_last_table(body)
                if last_table:
                    cols, rows = last_table
                    lower = [c.lower() for c in cols]
                    pick_cliente = None
                    for key in ["cliente", "razao_social", "razao social"]:
                        for i, c in enumerate(lower):
                            if key == c or key in c:
                                pick_cliente = i
                                break
                        if pick_cliente is not None:
                            break
                    if pick_cliente is not None:
                        clients = [r[pick_cliente] for r in rows if r and len(r) > pick_cliente]
                        sql = self._build_cities_sql_for_clients(clients)
                        return self._finalize_output(
                            await self._run_data_pipeline(body, question, export=False, sql_override=sql, intent_group=intent_group)
                        )

            # Follow-up de produto: nome / ticket medio / ultimo valor praticado.
            # Fazemos de forma deterministica usando o ultimo resultado (para nao "inventar" produto).
            if self._looks_like_product_name_question(routing_text):
                products = self._extract_product_codes(body, routing_text)
                if products:
                    sql = self._build_product_names_sql(products)
                    return self._finalize_output(
                        await self._run_data_pipeline(body, question, export=False, sql_override=sql, intent_group=intent_group)
                    )

            if self._looks_like_ticket_question(routing_text):
                products = self._extract_product_codes(body, routing_text)
                if products:
                    sql = self._build_ticket_sql_for_products(products)
                    return self._finalize_output(
                        await self._run_data_pipeline(body, question, export=False, sql_override=sql, intent_group=intent_group)
                    )

            if self._looks_like_last_sale_question(routing_text):
                products = self._extract_product_codes(body, routing_text)
                if products:
                    sql = self._build_last_sale_sql_for_products(products)
                    return self._finalize_output(
                        await self._run_data_pipeline(body, question, export=False, sql_override=sql, intent_group=intent_group)
                    )

            route = self._looks_like_data_question(routing_text)
            if route is False:
                guidance = self._out_of_scope_guidance()
                self._log_agent_query(
                    group="Não reconhecido",
                    route="out_of_scope",
                    mode="guidance",
                    started_at=started,
                    status="ok",
                )
                return self._finalize_output(guidance)

            canonical_question = self._canonicalize_deterministic_question(question)
            return self._finalize_output(
                await self._run_data_pipeline(body, canonical_question, export=False, intent_group=intent_group)
            )
        except httpx.TimeoutException:
            self._log_agent_query(
                group="Erro",
                route="pipe",
                mode="error",
                started_at=started,
                status="error",
                error="timeout",
            )
            return self._finalize_output(
                "Timeout: Ollama ou a API Aquafast demorou demais. "
                "Se a pergunta for comum (ranking, vendas por mes, volume), ela deve cair na resposta rapida via API; "
                "confira se o container da API e o Ollama estao de pe e os Valves de URL/timeout."
            )
        except httpx.HTTPStatusError as exc:
            self._log_agent_query(
                group="Erro",
                route="pipe",
                mode="error",
                started_at=started,
                status="error",
                error=f"http_status_{exc.response.status_code if exc.response is not None else '?'}",
            )
            return self._http_status_error_message(exc)
        except httpx.HTTPError as exc:
            self._log_agent_query(
                group="Erro",
                route="pipe",
                mode="error",
                started_at=started,
                status="error",
                error=type(exc).__name__,
            )
            return self._finalize_output(
                f"Erro de rede ao falar com a stack: {type(exc).__name__}: {exc}\n\n"
                "Verifique URL da API nos Valves do pipe e conectividade entre containers."
            )
        except Exception as exc:
            self._log_agent_query(
                group="Erro",
                route="pipe",
                mode="error",
                started_at=started,
                status="error",
                error=type(exc).__name__,
            )
            detail = str(exc).strip()
            if len(detail) > 280:
                detail = detail[:277] + "..."
            return self._finalize_output(
                "Opa! Houve um problema ao processar sua pergunta. "
                f"Detalhe: {detail}\n\n"
                "Se for SQL invalido ou coluna inexistente, reformule a pergunta ou tente uma das views: "
                "ranking_clientes, ranking_produtos, vendas_por_mes, ms_mercado_aquafast, vendas_caixas_estado, top_produtos_categoria."
            )

    async def _handle_chart(self, body: dict, question: str) -> str:
        schema = await self._fetch_schema()
        schema_text = schema.get("summary_text", "")
        sql = self._find_last_sql(body)
        if not sql:
            sql = await self._generate_sql(body, question, schema_text)

        sql_for_api = self._wrap_sql_for_safe_rows(sql, for_export=False)
        result = await self._query_sql(sql_for_api, "Grafico dos dados anteriores")
        chart = self._render_chart(result.get("title", "Grafico dos dados anteriores"), result.get("columns", []), result.get("rows", []))
        return self._finalize_output("\n".join(
            [
                f"## {result.get('title', 'Grafico dos dados anteriores')}",
                "",
                chart,
                "",
                result.get("markdown", ""),
                "",
                f"_Consulta executada: `{result.get('sql', sql)}`_",
                f"_Linhas retornadas: {result.get('row_count', 0)}_",
            ]
        ).strip())
