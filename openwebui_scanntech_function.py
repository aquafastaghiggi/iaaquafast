"""
title: Scanntech Analyst
author: Codex
version: 3.0.8
requirements: httpx
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

import httpx
from pydantic import BaseModel, Field


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
            default=60.0,
            description="Tempo maximo de espera da consulta",
        )
        OLLAMA_TIMEOUT_SECONDS: float = Field(
            default=75.0,
            description="Tempo maximo de espera das chamadas ao Ollama",
        )
        SQL_CONTEXT_MESSAGES: int = Field(
            default=4,
            description="Quantas mensagens recentes entram no prompt de SQL",
        )
        SUMMARY_ENABLED: bool = Field(
            default=True,
            description="Gera resumo via modelo (pode deixar lento)",
        )
        MAX_MODEL_TOKENS: int = Field(
            default=220,
            description="Limite de tokens de resposta do modelo",
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
        normalized = unicodedata.normalize("NFKD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        return " ".join(ascii_text.lower().split())

    def _extract_question(self, body: dict) -> str:
        messages = body.get("messages", [])
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            content = str(message.get("content", "")).strip()
            if content:
                return content
        return str(body.get("prompt", "")).strip()

    def _combined_user_text(self, body: dict) -> str:
        messages = body.get("messages", [])
        parts = []
        for message in messages:
            if message.get("role") != "user":
                continue
            content = str(message.get("content", "")).strip()
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
            "dados da scanntech",
            "base da scanntech",
        ]
        return self._contains_any(q, access_terms)

    def _answer_access_question(self) -> str:
        return (
            "Tenho acesso ao banco local do projeto Scanntech conectado ao DuckDB e à API interna da stack. "
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

    def _is_explicit_chat_question(self, question: str) -> bool:
        q = self._normalize_text(question)

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
            r"^\s*(oi|ol[aá]|bom dia|boa tarde|boa noite|obrigado|valeu)\s*[!?.,]*\s*$",
        ]

        if self._contains_any(q, chat_terms):
            return True

        return any(re.search(pattern, q) for pattern in chat_patterns)

    def _looks_like_data_question(self, question: str) -> bool | None:
        q = self._normalize_text(question)

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
            r"\b(razao social|cnpj|uf|cidade|canal|mes|m[eê]s|periodo)\b",
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
            content = str(message.get("content", ""))
            match = re.search(r"Consulta executada:\s*`([^`]+)`", content)
            if match:
                return match.group(1).strip().rstrip(";")
        return None

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

    async def _query_sql(self, sql: str, title: str = "Analise Scanntech") -> dict[str, Any]:
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
        return any(term in q for term in ["produto", "produtos", "item", "itens", "sku", "codigo", "código"])

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
        if any(term in q for term in ["receita", "faturamento", "valor total"]):
            preferred = prefer_revenue
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
            return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}"

    def _deterministic_summary(self, question: str, columns: list[str], rows: list[list[Any]]) -> str:
        if not rows:
            return "Nenhum resultado encontrado para essa consulta."

        metric_col = self._pick_metric_column(question, columns, rows)
        label_col = self._pick_label_column(columns, rows, metric_col)
        if not metric_col or metric_col not in columns:
            return "Resultado retornado. Veja a tabela abaixo."

        metric_idx = columns.index(metric_col)
        label_idx = columns.index(label_col) if label_col in columns else 0

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

    def _ensure_select_only(self, sql: str) -> str:
        normalized = self._normalize_text(sql)
        if not re.match(r"^(select|with|show|describe)\b", normalized):
            raise ValueError("SQL gerado nao parece ser uma consulta somente leitura.")
        return sql.strip().rstrip(";")

    async def _generate_sql(self, body: dict, question: str, schema_text: str, previous_sql: str | None = None) -> str:
        messages = body.get("messages", [])[-int(self.valves.SQL_CONTEXT_MESSAGES) :]
        user_context = []
        for message in messages:
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = str(message.get("content", "")).strip()
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
                    "Voce e um analista de dados especializado em DuckDB. "
                    "Gere apenas SQL valido e somente leitura. "
                    "Use apenas tabelas, views e colunas existentes no schema fornecido. "
                    "Responda com um unico bloco de codigo Markdown ```sql ... ``` e nada mais. "
                    "Se a pergunta pedir top 20, use LIMIT 20. "
                    "Prefira as views ranking_clientes, ranking_produtos e vendas_por_mes quando elas atenderem a pergunta. "
                    "Nao invente colunas. Nao use INSERT, UPDATE, DELETE, DROP ou ALTER."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Schema DuckDB:\n{schema_text}\n\n"
                    f"Pergunta do usuario: {question}\n\n"
                    f"Contexto recente:\n{context_text}{previous_sql_text}"
                ),
            },
        ]

        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": int(self.valves.MAX_MODEL_TOKENS)},
        }

        async with httpx.AsyncClient(timeout=self.valves.OLLAMA_TIMEOUT_SECONDS) as client:
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
            "options": {"temperature": 0.1},
        }

        async with httpx.AsyncClient(timeout=self.valves.OLLAMA_TIMEOUT_SECONDS) as client:
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
                    "Voce e o Aquafast IA. Responda em portugues, de forma util, curta e honesta. "
                    "Se a pergunta for sobre os dados da Scanntech, deixe claro quando esta consultando dados e quando esta apenas explicando. "
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

    async def _run_data_pipeline(
        self,
        body: dict,
        question: str,
        export: bool = False,
        chart: bool = False,
        sql_override: str | None = None,
    ) -> str:
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

            result = await self._query_sql(sql, "Analise Scanntech")
        except httpx.HTTPStatusError as exc:
            detail = str(exc.response.text)
            if exc.response.status_code == 400:
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
                result = await self._query_sql(repaired_sql, "Analise Scanntech")
                sql = repaired_sql
            else:
                raise

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

        # Resumo deterministico: todos os numeros/percentuais sao calculados a partir de (columns, rows).
        summary = self._deterministic_summary(question, result.get("columns", []), result.get("rows", []))
        return "\n".join(
            [
                "## Analise Scanntech",
                "",
                summary,
                "",
                result.get("markdown", ""),
                "",
                f"_Consulta executada: `{result.get('sql', sql)}`_",
                f"_Linhas retornadas: {result.get('row_count', 0)}_",
            ]
        )

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
            question = self._extract_question(body)
            routing_text = question
            if not question:
                return "Envie uma pergunta sobre os dados da Scanntech."

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

            route = self._looks_like_data_question(routing_text)
            if route is False:
                return await self._ask_chat(body, question)

            return await self._run_data_pipeline(body, question, export=False)
        except httpx.TimeoutException:
            return (
                "O modelo demorou demais para responder agora (timeout). "
                "Tenta novamente em alguns segundos; se persistir, posso reduzir o uso do modelo e retornar so a tabela."
            )
        except httpx.HTTPError as exc:
            return f"Ocorreu um erro de rede ao consultar a stack ({type(exc).__name__})."
        except Exception:
            return "Opa! Houve um problema ao processar sua pergunta. Tenta de novo; se repetir, eu olho os logs e corrijo."

    async def _handle_chart(self, body: dict, question: str) -> str:
        schema = await self._fetch_schema()
        schema_text = schema.get("summary_text", "")
        sql = self._find_last_sql(body)
        if not sql:
            sql = await self._generate_sql(body, question, schema_text)

        result = await self._query_sql(sql, "Grafico dos dados anteriores")
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
