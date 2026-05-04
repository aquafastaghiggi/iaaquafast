"""
title: Scanntech Analyst
author: Codex
version: 2.1.0
requirements: httpx
"""

from __future__ import annotations

import json
import re
import unicodedata

import httpx
from pydantic import BaseModel, Field


class Pipe:
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
            description="Modelo usado para conversa livre e classificacao",
        )
        TIMEOUT_SECONDS: float = Field(
            default=60.0,
            description="Tempo maximo de espera da consulta",
        )

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [
            {
                "id": "scanntech_analyst",
                "name": "Scanntech Analyst",
            }
        ]

    def _normalize_text(self, text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        return ascii_text.lower()

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
        return any(term in q for term in ["grafico", "chart", "plot", "visual"])

    def _is_excel_request(self, question: str) -> bool:
        q = self._normalize_text(question)
        return any(
            term in q
            for term in [
                "excel",
                "xlsx",
                "planilha",
                "arquivo excel",
                "exportar",
                "exporta",
                "gerar arquivo",
                "baixar",
                "download",
            ]
        )

    def _is_sql_request(self, question: str) -> bool:
        q = self._normalize_text(question).strip()
        return bool(re.match(r"^(select|with|show|describe)\b", q)) or " select " in f" {q} "

    def _contains_any(self, text: str, terms: list[str]) -> bool:
        return any(term in text for term in terms)

    def _looks_like_data_question(self, question: str) -> bool | None:
        q = self._normalize_text(question)
        q_compact = " ".join(q.split())

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
            "razao_social",
            "razao social",
            "cnpj",
            "uf",
            "cidade",
            "canal",
            "mes",
            "mês",
            "periodo",
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
            r"\b(razao social|razao_social|cnpj|uf|cidade|canal|mes|m[eê]s|periodo)\b",
            r"\b(mais vendidos|mais comprados|valor total|ticket medio)\b",
        ]
        chat_patterns = [
            r"\b(como funciona|como voce funciona|explique|resuma|escreva|revise|melhore|ajude|traduza)\b",
            r"\b(tem acesso|acesso a base|acessar a base|consegue acessar|voce tem acesso)\b",
            r"\b(quem e voce|qual sua funcao|o que e|por que|porque)\b",
        ]

        if self._is_sql_request(question):
            return True

        if self._is_excel_request(question):
            return True

        if self._is_chart_request(question):
            return True

        if self._contains_any(q_compact, data_terms):
            return True

        if any(re.search(pattern, q_compact) for pattern in data_patterns):
            return True

        if any(re.search(pattern, q_compact) for pattern in chat_patterns) and not self._contains_any(q_compact, data_terms):
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

    def _pick_chart_columns(self, columns: list[str]) -> tuple[str | None, str | None]:
        labels = ["cliente", "produto", "mes", "periodo", "categoria", "name"]
        values = ["valor_total", "receita_total", "receita", "total_vendas", "total_pedidos", "qtd", "quantity"]

        label_col = None
        value_col = None

        lower_map = {c.lower(): c for c in columns}
        for key in labels:
            for lower, original in lower_map.items():
                if key == lower or key in lower:
                    label_col = original
                    break
            if label_col:
                break

        for key in values:
            for lower, original in lower_map.items():
                if key == lower or key in lower:
                    value_col = original
                    break
            if value_col:
                break

        if not label_col and columns:
            label_col = columns[0]
        if not value_col and len(columns) > 1:
            value_col = columns[1]

        return label_col, value_col

    def _render_chart(self, title: str, columns: list[str], rows: list[list]) -> str:
        if not rows:
            return "_Nenhum dado encontrado para montar o grafico._"

        label_col, value_col = self._pick_chart_columns(columns)
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

    async def _ollama_chat(self, body: dict, question: str) -> str:
        messages = body.get("messages", [])[-10:]
        chat_messages = [
            {
                "role": "system",
                "content": (
                    "Voce e o Aquafast IA. Responda de forma util, curta e honesta. "
                    "Se a pergunta for sobre os dados da Scanntech, seja claro sobre o que foi consultado. "
                    "Nunca invente numeros."
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

    async def pipe(self, body: dict):
        question = self._extract_question(body)
        routing_text = self._combined_user_text(body) or question
        if not question:
            return "Envie uma pergunta sobre os dados da Scanntech."

        normalized_routing = self._normalize_text(routing_text)
        if self._contains_any(
            normalized_routing,
            [
                "tem acesso",
                "acesso a base",
                "acessar a base",
                "consegue acessar",
                "voce tem acesso",
                "voce consegue acessar",
            ],
        ):
            return await self._ollama_chat(body, question)

        if self._is_excel_request(routing_text):
            last_sql = self._find_last_sql(body)
            payload = None
            if last_sql:
                payload = {"sql": last_sql, "title": "Exportacao Excel"}
            else:
                route_hint = self._looks_like_data_question(routing_text)
                if route_hint is False:
                    return (
                        "Para gerar Excel, eu preciso de uma consulta de dados antes "
                        "ou de uma pergunta com contexto de vendas, clientes, produtos ou receitas."
                    )
                try:
                    async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                        response = await client.post(
                            f"{self.valves.API_BASE_URL}/ask",
                            json={"question": question},
                        )
                        response.raise_for_status()
                        data = response.json()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 400:
                        return (
                            "Nao encontrei uma consulta anterior para exportar em Excel. "
                            "Primeiro me peça uma analise de dados, ou diga algo como "
                            "'top 20 produtos mais vendidos em Excel'."
                        )
                    raise

                if not data.get("ok"):
                    return f"Nao consegui gerar o Excel: {data.get('error', 'erro desconhecido')}"
                payload = {"sql": data.get("sql", ""), "title": data.get("title", "Exportacao Excel")}
            if not payload.get("sql"):
                return "Nao encontrei uma consulta anterior para exportar em Excel."

            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                response = await client.post(f"{self.valves.API_BASE_URL}/export", json=payload)
                response.raise_for_status()
                data = response.json()

            if not data.get("ok"):
                return f"Nao consegui gerar o Excel: {data.get('error', 'erro desconhecido')}"

            download_url = data.get("download_url", "")
            title = data.get("title", "Exportacao Excel")
            sql = data.get("sql", "")
            return "\n".join(
                [
                    f"## {title}",
                    "",
                    f"Arquivo Excel gerado com sucesso.",
                    f"[Baixar o arquivo]({download_url})",
                    "",
                    f"_Consulta executada: `{sql}`_",
                    f"_Linhas exportadas: {data.get('row_count', 0)}_",
                ]
            )

        if self._contains_any(
            normalized_routing,
            [
                "top",
                "ranking",
                "mais vendidos",
                "mais comprados",
                "maior valor",
                "menor valor",
                "clientes",
                "produto",
                "produtos",
                "vendas",
                "receita",
                "faturamento",
                "ticket",
                "churn",
                "sku",
                "canal",
                "cidade",
                "uf",
                "razao social",
            ],
        ):
            route = "data"
        else:
            route = self._looks_like_data_question(routing_text)
            if route is None:
                route = await self._classify_intent(routing_text)

        if self._is_chart_request(routing_text):
            last_sql = self._find_last_sql(body)
            if last_sql:
                async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        f"{self.valves.API_BASE_URL}/query",
                        json={"sql": last_sql, "title": "Grafico dos dados anteriores"},
                    )
                    response.raise_for_status()
                    data = response.json()
            else:
                async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        f"{self.valves.API_BASE_URL}/ask",
                        json={"question": question},
                    )
                    response.raise_for_status()
                    data = response.json()

            if not data.get("ok"):
                return f"Nao consegui gerar o grafico: {data.get('error', 'erro desconhecido')}"

            title = data.get("title", "Grafico dos dados anteriores")
            chart = self._render_chart(title, data.get("columns", []), data.get("rows", []))
            table = data.get("markdown", "")
            sql = data.get("sql", "")
            return "\n".join(
                [
                    f"## {title}",
                    "",
                    chart,
                    "",
                    table,
                    "",
                    f"_Consulta executada: `{sql}`_",
                    f"_Linhas retornadas: {data.get('row_count', 0)}_",
                ]
            )

        if route == "data":
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_SECONDS) as client:
                try:
                    response = await client.post(
                        f"{self.valves.API_BASE_URL}/ask",
                        json={"question": question},
                    )
                    response.raise_for_status()
                    data = response.json()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 400:
                        return await self._ollama_chat(
                            body,
                            question
                            + " Responda apenas dizendo que a pergunta nao corresponde a uma analise suportada e que posso consultar vendas, clientes, produtos, receitas ou graficos.",
                        )
                    raise

            if not data.get("ok"):
                return await self._ollama_chat(
                    body,
                    question
                    + " Responda apenas dizendo que a pergunta nao corresponde a uma analise suportada e que posso consultar vendas, clientes, produtos, receitas ou graficos.",
                )

            title = data.get("title", "Analise Scanntech")
            sql = data.get("sql", "")
            markdown = data.get("markdown", "")
            row_count = data.get("row_count", 0)

            parts = [
                f"## {title}",
                "",
                markdown,
                "",
                f"_Consulta executada: `{sql}`_",
                f"_Linhas retornadas: {row_count}_",
            ]
            return "\n".join(parts)

        return await self._ollama_chat(body, question)
