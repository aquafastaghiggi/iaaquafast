"""
title: Scanntech Analyst
author: Codex
version: 3.0.15
requirements: httpx
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

import httpx
from pydantic import BaseModel, Field

try:
    from aquafast_semantics import normalize_business_question, repair_mojibake
except Exception:
    def repair_mojibake(text: str) -> str:
        if not isinstance(text, str):
            return text
        if not any(marker in text for marker in ("Ã", "Â", "ï¿½")):
            return text
        try:
            repaired = text.encode("latin1").decode("utf-8")
        except Exception:
            return text
        return repaired or text


    def normalize_business_question(text: str) -> str:
        q = repair_mojibake(text)
        q = unicodedata.normalize("NFKD", q)
        q = q.encode("ascii", "ignore").decode("ascii")
        q = " ".join(q.strip().lower().split())
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


class Pipe:
    # Invariante do projeto:
    # - O nome visivel e a porta de entrada principal precisam permanecer como "Scanntech Analyst".
    # - O modelo interno continua sendo qwen2.5:latest, mas so para raciocinio e resposta.
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
            default="qwen2.5:latest",
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
        text = repair_mojibake(text)
        normalized = unicodedata.normalize("NFKD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        return " ".join(ascii_text.lower().split())

    def _content_to_text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return repair_mojibake(content)
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
        return repair_mojibake(
            "Tenho acesso ao banco local do projeto Aquafast conectado ao DuckDB e à API interna da stack. "
            "Consigo consultar os dados ingeridos no ambiente local, gerar análises, gráficos e exportações. "
            "Não tenho acesso a bases externas ou confidenciais fora deste ambiente."
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
            "parÃ¡grafo",
            "frase",
            "prompt",
            "documento",
            "relatorio",
            "relatÃ³rio",
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
            r"^\s*(oi|ol[aÃ¡]|bom dia|boa tarde|boa noite|obrigado|valeu)\s*[!?.,]*\s*$",
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
            r"\b(razao social|cnpj|uf|cidade|canal|mes|m[eÃª]s|periodo)\b",
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
        return any(term in q for term in ["periodo", "periodos", "quando", "mes", "mÃªs", "data", "primeira", "ultima"])

    def _looks_like_client_question(self, question: str) -> bool:
        q = self._normalize_text(question)
        return any(term in q for term in ["cliente", "clientes", "razao social", "razÃ£o social", "cnpj"])

    def _looks_like_city_question(self, question: str) -> bool:
        q = self._normalize_text(question)
        return any(term in q for term in ["cidade", "cidades", "municipio", "municÃ­pio", "uf", "estado"])

    def _looks_like_product_name_question(self, question: str) -> bool:
        q = self._normalize_text(question)
        # _normalize_text remove acentos, entao "descriÃ§Ã£o" vira "descricao"
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
        return any(term in q for term in ["produto", "produtos", "item", "itens", "sku", "codigo", "cÃ³digo"])

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
                "A consulta cruza o portfolio Aquafast com caixas para enxergar o mix por categoria."
            )
        if any(term in text for term in ["vendas por mes", "vendas por mÃªs", "mensal", "serie mensal", "sÃ©rie mensal"]):
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
                "A consulta lista os produtos Aquafast com maior volume em caixas e receita."
            )
        if any(term in text for term in ["clientes", "lojas", "churn", "compra"]):
            return (
                "Fonte: `ranking_clientes`. "
                "A consulta resume as lojas Aquafast por caixas vendidas, receita e recorrencia."
            )
        return "Fonte: consulta local no DuckDB usando as views semanticas da Aquafast."

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

    async def _ask_chat(self, body: dict, question: str) -> str:
        messages = body.get("messages", [])[-self.valves.MAX_MESSAGES :]
        chat_messages = [
            {
                "role": "system",
                "content": (
                    "Voce e o Aquafast IA (modo conversa, sem consulta SQL nesta rodada). "
                    "Responda em portugues, de forma util e curta. "
                    "NUNCA invente numeros, totais, rankings, nomes de clientes ou produtos, nem datas de vendas. "
                    "A regra padrao e falar do portfolio Aquafast e do mercado Aquafast, sempre pensando em caixas e nao em unidade avulsa. "
                    "Se o usuario pedir qualquer dado concreto da base, diga explicitamente que ele deve reformular como pergunta analitica no mesmo chat "
                    "(ex.: 'top 10 lojas Aquafast por caixa') para o sistema executar SQL no DuckDB. "
                    "Nao afirme que nao ha acesso aos dados locais da stack quando a pergunta for sobre a base do projeto."
                ),
            }
        ]

        for message in messages:
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = str(message.get("content", "")).strip()
            if not content:
                continue
            chat_messages.append({"role": role, "content": content})

        if not chat_messages or chat_messages[-1].get("role") != "user":
            chat_messages.append({"role": "user", "content": question})

        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": chat_messages,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": int(self.valves.MAX_MODEL_TOKENS)},
        }

        async with httpx.AsyncClient(timeout=self.valves.OLLAMA_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{self.valves.OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = str(message.get("content", "")).strip()
        if not content:
            return "Nao consegui gerar uma resposta agora."
        return content

    def _http_status_error_message(self, exc: httpx.HTTPStatusError) -> str:
        detail = ""
        if exc.response is not None:
            try:
                detail = exc.response.text.strip()
            except Exception:
                detail = ""
        if len(detail) > 800:
            detail = detail[:797] + "..."
        code = exc.response.status_code if exc.response is not None else "?"
        return repair_mojibake(
            f"Erro HTTP {code} na API Aquafast.\n\n"
            f"{detail or '(sem detalhe no corpo da resposta)'}\n\n"
            "Confirme se o servico da API esta no ar, a URL em Valves (ex.: `http://scanntech-api:8000`) "
            "bate com o `docker compose` e se o arquivo `aquafast_scanntech.duckdb` existe no container."
        )
    def _build_analysis_response(self, question: str, result: dict[str, Any], sql_hint: str) -> str:
        summary = repair_mojibake(self._deterministic_summary(question, result.get("columns", []), result.get("rows", [])))
        source_note = repair_mojibake(self._source_note_from_result(question, result))
        markdown = repair_mojibake(result.get("markdown", ""))
        cap_note = ""
        if result.get("truncated"):
            cap = result.get("row_cap")
            cap_note = repair_mojibake(
                f"\n\n_Amostra limitada pela API ({cap} linhas no maximo). "
                "Refine a pergunta com filtros (mes, cliente, produto) ou use LIMIT menor no SQL para ver tudo no Excel._"
            )
        return "\n".join(
            [
                repair_mojibake("## Analise Aquafast"),
                "",
                summary,
                "",
                source_note,
                "",
                markdown,
                "",
                repair_mojibake(f"_Linhas retornadas: {result.get('row_count', 0)}_"),
                cap_note,
            ]
        ).strip()
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
    ) -> str:
        if not export and sql_override is None:
            legacy_reply = await self._try_legacy_ask(question)
            if legacy_reply is not None:
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
                return self._http_status_error_message(exc)

        if export:
            # defensive fallback; normally handled earlier
            download_url = result.get("download_url", "")
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
        return "\n".join(chart_lines)

    async def pipe(self, body: dict):
        try:
            # Proteção contra fallback silencioso para modelo base (qwen2.5)
            # Se o usuário selecionar qwen2.5:latest em vez do pipe Scanntech Analyst,
            # isso bloqueará a resposta e instruirá o redirecionamento.
            model_name = body.get("model", "").lower()
            if "qwen" in model_name and "scanntech_analyst" not in model_name and "analyst" not in model_name:
                return (
                    "⚠️ **ERRO: Modelo incorreto selecionado**\n\n"
                    "Você selecionou `qwen2.5:latest` em vez de usar o pipe **Scanntech Analyst**.\n\n"
                    "**O que fazer:**\n"
                    "1. Clique no seletor de modelo no topo do chat\n"
                    "2. Procure por **\"Scanntech Analyst\"** (não por \"qwen2.5\")\n"
                    "3. Selecione **\"Scanntech Analyst\"**\n"
                    "4. Envie sua pergunta novamente\n\n"
                    "O Scanntech Analyst é o assistente especializado em análise dos dados Aquafast. "
                    "Usando o modelo base diretamente, você perde acesso aos dados e às análises contextualizadas."
                )

            question = self._extract_question(body)
            routing_text = question
            if not question:
                return "Envie uma pergunta sobre os dados da Aquafast."

            if self._is_access_question(routing_text):
                return self._answer_access_question()

            if self._is_explicit_chat_question(routing_text):
                return await self._ask_chat(body, question)

            if self._is_excel_request(routing_text):
                last_sql = self._find_last_sql(body)
                route_hint = self._looks_like_data_question(routing_text)
                if not last_sql and route_hint is not True:
                    return (
                        "Para gerar Excel, eu preciso de uma consulta de dados antes "
                        "ou de uma pergunta com contexto de vendas, clientes, produtos ou receitas."
                    )
                return await self._run_data_pipeline(body, question, export=True, sql_override=last_sql)

            if self._is_chart_request(routing_text):
                last_sql = self._find_last_sql(body)
                route_hint = self._looks_like_data_question(routing_text)
                if not last_sql and route_hint is not True:
                    return (
                        "Para gerar um grafico, eu preciso de uma pergunta analitica antes "
                        "ou de uma consulta anterior com dados."
                    )
                return await self._handle_chart(body, question)

            # Periodo/datas: tenta resolver de forma deterministica usando o ultimo resultado (sem chamar o modelo).
            if self._looks_like_period_question(routing_text):
                last_table = self._find_last_table(body)
                if last_table:
                    cols, rows = last_table
                    lower = [c.lower() for c in cols]
                    # pick product/code column
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
                        return await self._run_data_pipeline(body, question, export=False, sql_override=sql)
                    # pick month column
                    pick_mes = None
                    for key in ["mes", "mÃªs"]:
                        for i, c in enumerate(lower):
                            if key == c or key in c:
                                pick_mes = i
                                break
                        if pick_mes is not None:
                            break
                    if pick_mes is not None:
                        months = [r[pick_mes] for r in rows if r and len(r) > pick_mes]
                        sql = self._build_clients_sql_for_months(months)
                        return await self._run_data_pipeline(body, question, export=False, sql_override=sql)

            # Follow-up de clientes (ex.: "essas vendas correspondem a quais clientes?") usando o ultimo resultado com meses.
            if self._looks_like_client_question(routing_text):
                last_table = self._find_last_table(body)
                if last_table:
                    cols, rows = last_table
                    lower = [c.lower() for c in cols]
                    pick_mes = None
                    for key in ["mes", "mÃªs"]:
                        for i, c in enumerate(lower):
                            if key == c or key in c:
                                pick_mes = i
                                break
                        if pick_mes is not None:
                            break
                    if pick_mes is not None:
                        months = [r[pick_mes] for r in rows if r and len(r) > pick_mes]
                        sql = self._build_clients_sql_for_months(months)
                        return await self._run_data_pipeline(body, question, export=False, sql_override=sql)

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
                        return await self._run_data_pipeline(body, question, export=False, sql_override=sql)

            # Follow-up de produto: nome / ticket medio / ultimo valor praticado.
            # Fazemos de forma deterministica usando o ultimo resultado (para nao "inventar" produto).
            if self._looks_like_product_name_question(routing_text):
                products = self._extract_product_codes(body, routing_text)
                if products:
                    sql = self._build_product_names_sql(products)
                    return await self._run_data_pipeline(body, question, export=False, sql_override=sql)

            if self._looks_like_ticket_question(routing_text):
                products = self._extract_product_codes(body, routing_text)
                if products:
                    sql = self._build_ticket_sql_for_products(products)
                    return await self._run_data_pipeline(body, question, export=False, sql_override=sql)

            if self._looks_like_last_sale_question(routing_text):
                products = self._extract_product_codes(body, routing_text)
                if products:
                    sql = self._build_last_sale_sql_for_products(products)
                    return await self._run_data_pipeline(body, question, export=False, sql_override=sql)

            route = self._looks_like_data_question(routing_text)
            if route is False:
                return await self._ask_chat(body, question)

            return await self._run_data_pipeline(body, question, export=False)
        except httpx.TimeoutException:
            return (
                "Timeout: Ollama ou a API Aquafast demorou demais. "
                "Se a pergunta for comum (ranking, vendas por mes, volume), ela deve cair na resposta rapida via API; "
                "confira se o container da API e o Ollama estao de pe e os Valves de URL/timeout."
            )
        except httpx.HTTPStatusError as exc:
            return self._http_status_error_message(exc)
        except httpx.HTTPError as exc:
            return (
                f"Erro de rede ao falar com a stack: {type(exc).__name__}: {exc}\n\n"
                "Verifique URL da API nos Valves do pipe e conectividade entre containers."
            )
        except Exception as exc:
            detail = str(exc).strip()
            if len(detail) > 280:
                detail = detail[:277] + "..."
            return (
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
        return "\n".join(
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
        )
