"""
title: Scanntech Analyst
author: Codex
version: 3.0.1
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
        MAX_MESSAGES: int = Field(
            default=12,
            description="Quantidade de mensagens recentes para contexto",
        )

    def __init__(self):
        self.valves = self.Valves()

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
        async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
            response = await client.get(f"{self.valves.API_BASE_URL}/schema")
            response.raise_for_status()
            return response.json()

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

    def _ensure_select_only(self, sql: str) -> str:
        normalized = self._normalize_text(sql)
        if not re.match(r"^(select|with|show|describe)\b", normalized):
            raise ValueError("SQL gerado nao parece ser uma consulta somente leitura.")
        return sql.strip().rstrip(";")

    async def _generate_sql(self, body: dict, question: str, schema_text: str) -> str:
        messages = body.get("messages", [])[-self.valves.MAX_MESSAGES :]
        user_context = []
        for message in messages:
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = str(message.get("content", "")).strip()
            if content:
                user_context.append(f"{role.upper()}: {content}")
        context_text = "\n".join(user_context) if user_context else "sem contexto adicional"

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
                    f"Contexto recente:\n{context_text}"
                ),
            },
        ]

        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": prompt,
            "stream": False,
            "options": {"temperature": 0.1},
        }

        async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
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

        async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
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
                        f"Resultado:\n{markdown_table}\n\n"
                        "Resuma o que o resultado mostra em portugues, em 3 a 6 linhas, "
                        "e destaque a principal leitura de negocio."
                    ),
                },
            ],
            "stream": False,
            "options": {"temperature": 0.2},
        }

        async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
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
                    "Se a pergunta for sobre os dados da Scanntech, deixe claro quando esta consultando dados e quando esta apenas explicando."
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
            "options": {"temperature": 0.2},
        }

        async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
            response = await client.post(f"{self.valves.OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = str(message.get("content", "")).strip()
        if not content:
            return "Nao consegui gerar uma resposta agora."
        return content

    async def _run_data_pipeline(self, body: dict, question: str, export: bool = False, chart: bool = False) -> str:
        schema = await self._fetch_schema()
        schema_text = schema.get("summary_text", "")
        sql = self._find_last_sql(body)

        if not sql:
            sql = await self._generate_sql(body, question, schema_text)

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

        summary = await self._summarize_result(question, sql, result.get("markdown", ""))
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
        question = self._extract_question(body)
        routing_text = self._combined_user_text(body) or question
        if not question:
            return "Envie uma pergunta sobre os dados da Scanntech."

        normalized = self._normalize_text(routing_text)

        if self._contains_any(normalized, ["tem acesso", "acesso a base", "acessar a base", "consegue acessar", "voce tem acesso", "voce consegue acessar"]):
            return await self._ask_chat(body, question)

        if self._is_excel_request(routing_text):
            last_sql = self._find_last_sql(body)
            route_hint = self._looks_like_data_question(routing_text)
            if not last_sql and route_hint is not True:
                return (
                    "Para gerar Excel, eu preciso de uma consulta de dados antes "
                    "ou de uma pergunta com contexto de vendas, clientes, produtos ou receitas."
                )
            return await self._run_data_pipeline(body, question, export=True)

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
        if route is None:
            route = await self._classify_intent(question)

        if route == "data":
            return await self._run_data_pipeline(body, question, export=False)

        return await self._ask_chat(body, question)

    async def _classify_intent(self, question: str) -> str:
        payload = {
            "model": self.valves.CHAT_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Classifique a intencao do usuario em JSON puro. "
                        "Retorne exatamente: {\"route\":\"data\"} ou {\"route\":\"chat\"}. "
                        "Use \"data\" quando a pergunta pedir analise, numeros, ranking, graficos, clientes, "
                        "produtos, vendas, receita, SQL ou qualquer consulta ao DuckDB. "
                        "Use \"chat\" para conversa livre, explicacoes gerais, texto ou ajuda nao relacionada aos dados."
                    ),
                },
                {"role": "user", "content": question},
            ],
            "stream": False,
            "options": {"temperature": 0},
        }

        async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
            response = await client.post(f"{self.valves.OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}) if isinstance(data, dict) else {}
        content = str(message.get("content", "")).strip()
        match = re.search(r'"route"\s*:\s*"(data|chat)"', content, flags=re.IGNORECASE)
        if match:
            return match.group(1).lower()
        return "chat"

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
