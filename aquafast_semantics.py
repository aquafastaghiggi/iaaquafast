from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.strip().lower().split())


_COMMON_MOJIBAKE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
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
)


def _repair_mojibake_once(text: str) -> str:
    if not text:
        return ""
    repaired = text
    candidate = repaired
    for encoding in ("latin1", "cp1252"):
        try:
            candidate = repaired.encode(encoding).decode("utf-8")
            break
        except Exception:
            candidate = repaired
    for bad, good in _COMMON_MOJIBAKE_REPLACEMENTS:
        candidate = candidate.replace(bad, good)
    return candidate


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
        next_text = _repair_mojibake_once(repaired)
        if next_text == repaired:
            break
        repaired = next_text
    return repaired


def repair_mojibake(text: Any) -> str:
    return safe_output_text(text)


BUSINESS_SYNONYMS: tuple[tuple[str, str], ...] = (
    (r"\bpontos de venda\b", "lojas"),
    (r"\bpdv?s?\b", "lojas"),
    (r"\bpresente hoje\b", "hoje"),
    (r"\bpresenca hoje\b", "hoje"),
    (r"\bpresença hoje\b", "hoje"),
    (r"\bconcorrente principal\b", "maior concorrente"),
    (r"\bprincipal concorrente\b", "maior concorrente"),
    (r"\bteriam mais potencial\b", "potencial de venda"),
    (r"\bproduto[s]? com potencial\b", "potencial de venda"),
    (r"\bo que vender\b", "potencial de venda"),
    (r"\bmix\b", "categoria"),
    (r"\bportifolio\b", "portfolio"),
)


def _selftest_safe_output_text() -> None:
    cases = {
        "Vendas por mÃªs": "Vendas por mês",
        "HistÃ³rico de consultas": "Histórico de consultas",
        "ConcorrÃªncia": "Concorrência",
        "disponÃ­veis": "disponíveis",
        "Vendas por mês": "Vendas por mês",
    }
    for raw, expected in cases.items():
        actual = safe_output_text(raw)
        assert actual == expected, f"{raw!r} -> {actual!r} (esperado {expected!r})"


def normalize_business_question(text: str) -> str:
    q = normalize_text(safe_output_text(text))
    q = q.replace("_", " ")
    for pattern, replacement in BUSINESS_SYNONYMS:
        q = re.sub(pattern, replacement, q)
    return " ".join(q.split())


def normalize_product_name(text: str | None) -> str:
    if not text:
        return ""
    q = repair_mojibake(str(text))
    q = unicodedata.normalize("NFKD", q)
    q = q.encode("ascii", "ignore").decode("ascii")
    q = q.lower().replace("_", " ").replace("+", " ")
    q = q.replace(",", ".")
    q = re.sub(r"\b2x\s*(\d+(?:\.\d+)?\s*(?:ml|l|kg|g))\b", r" pack \1 ", q)
    q = re.sub(r"\b\d+x\s*(\d+(?:\.\d+)?\s*(?:ml|l|kg|g))\b", r" pack \1 ", q)
    q = re.sub(r"\bc\s*/\s*pulv\w*\b", " pulverizador ", q)
    q = re.sub(r"\bgatilho\b", " pulverizador ", q)
    q = re.sub(r"\bc\s*/\s*recarga\b", " recarga ", q)
    q = re.sub(r"\bsquee?z\w*\b", " squeeze ", q)
    q = re.sub(r"\bdesengordurante\b", " deseng ", q)
    q = re.sub(r"\bamaciantes?\b", " amaciante ", q)
    q = re.sub(r"\bsabao liquido\b", " lava roupas liq ", q)
    q = re.sub(r"\bsabao em po\b", " lava roupas po ", q)
    q = re.sub(r"\blimpador de vidro\b", " limpa vidros ", q)
    q = re.sub(r"\blimpador multiuso\b", " multiuso ", q)
    q = re.sub(r"\blimpador perfumado\b", " limpador perfumado ", q)
    q = re.sub(r"\blimpeza pesada\b", " limpeza pesada ", q)
    q = re.sub(r"\bdetergente liquido\b", " detergente ", q)
    q = re.sub(r"\bagua sanitaria\b", " agua sanitaria ", q)
    q = re.sub(r"\balvejante\b", " alvejante ", q)
    q = re.sub(r"\blimpador pet\b", " neutralizador de odores ", q)
    q = re.sub(r"\baquafast\b", " ", q)
    q = re.sub(r"[^a-z0-9\.\s]+", " ", q)
    return " ".join(q.split())


def normalize_volume_signature(text: str | None) -> str:
    normalized = normalize_product_name(text)
    if not normalized:
        return ""
    pack_flag = "pack" if "pack" in normalized else ""
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(ml|l|kg|g)\b", normalized)
    if match:
        sig = f"{match.group(1)}{match.group(2)}"
        return f"{pack_flag}{sig}" if pack_flag else sig
    if pack_flag:
        return pack_flag
    return ""


def _product_markers(text: str | None) -> set[str]:
    normalized = normalize_product_name(text)
    markers = set()
    if "pack" in normalized:
        markers.add("pack")
    if "pulverizador" in normalized:
        markers.add("pulverizador")
    if "recarga" in normalized:
        markers.add("recarga")
    if "squeeze" in normalized:
        markers.add("squeeze")
    if "concentrado" in normalized:
        markers.add("concentrado")
    if "diluido" in normalized:
        markers.add("diluido")
    if "limpeza pesada" in normalized:
        markers.add("limpeza pesada")
    if "limpador perfumado" in normalized:
        markers.add("limpador perfumado")
    if "outros" in normalized:
        markers.add("outros")
    return markers


def _infer_portfolio_category_key(text: str | None) -> str:
    normalized = normalize_product_name(text)
    category_aliases = (
        ("lava roupas po", "sabao em po"),
        ("lava roupas liq", "sabao liquido"),
        ("lava roupas", "sabao liquido"),
        ("deseng", "desengordurantes"),
        ("amaciante", "amaciantes"),
        ("limpa vidros", "limpa vidros"),
        ("multiuso", "multiuso"),
        ("detergente", "detergente liquido"),
        ("agua sanitaria", "agua sanitaria"),
        ("alvejante", "alvejante"),
        ("neutralizador de odores", "eliminador de odores pet"),
        ("limpador perfumado", "grandes superficies"),
        ("limpeza pesada", "grandes superficies"),
    )
    for marker, category in category_aliases:
        if marker in normalized:
            return normalize_product_name(category)
    return normalized


def _portfolio_candidate_signature(row: dict[str, Any]) -> dict[str, Any]:
    category = normalize_product_name(row.get("PROD_CATEGORY"))
    litragem = normalize_volume_signature(row.get("LITRAGEM"))
    candidate_text = " ".join(
        part
        for part in [
            row.get("SUBGRUPO_CIGAM") or "",
            row.get("SUBGRUPO_LITRAGEM") or "",
            row.get("LITRAGEM") or "",
            row.get("PROD_CATEGORY") or "",
        ]
        if str(part).strip()
    )
    return {
        "category": category,
        "litragem": litragem,
        "markers": _product_markers(candidate_text),
        "normalized_text": normalize_product_name(candidate_text),
    }


def resolve_subgrupo_cigam(
    product_name: str | None,
    category: str | None = None,
    clasif_1: str | None = None,
    clasif_2: str | None = None,
    portfolio_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw_text = " ".join(
        part
        for part in [product_name or "", category or "", clasif_1 or "", clasif_2 or ""]
        if str(part).strip()
    )
    raw_normalized = normalize_product_name(raw_text)
    raw_category = _infer_portfolio_category_key(category or clasif_1 or product_name or raw_text)
    raw_size = normalize_volume_signature(" ".join(part for part in [clasif_2 or "", product_name or "", clasif_1 or ""] if str(part).strip()))
    raw_markers = _product_markers(raw_text)
    candidates = [
        row
        for row in (portfolio_rows or [])
        if _infer_portfolio_category_key(row.get("PROD_CATEGORY")) == raw_category
    ]
    if not candidates and raw_category:
        candidates = [
            row
            for row in (portfolio_rows or [])
            if raw_category in _infer_portfolio_category_key(row.get("PROD_CATEGORY"))
        ]
    if raw_size:
        size_candidates = [
            row
            for row in candidates
            if normalize_volume_signature(row.get("LITRAGEM") or row.get("SUBGRUPO_CIGAM")) == raw_size
        ]
        if size_candidates:
            candidates = size_candidates
    if len(candidates) == 1:
        chosen = candidates[0]
        return {
            "produto_padrao": repair_mojibake(str(chosen.get("SUBGRUPO_CIGAM") or product_name or "")),
            "subgrupo_cigam": repair_mojibake(str(chosen.get("SUBGRUPO_CIGAM") or "")),
            "subgrupo_litragem": repair_mojibake(str(chosen.get("SUBGRUPO_LITRAGEM") or "")),
            "qtde_cx": chosen.get("QTDE_CX"),
            "match_mode": "deterministic_exact",
            "match_confidence": "high",
            "raw_normalized": raw_normalized,
        }

    priority_markers = (
        "pack",
        "pulverizador",
        "recarga",
        "squeeze",
        "concentrado",
        "diluido",
        "limpeza pesada",
        "limpador perfumado",
        "outros",
    )
    for marker in priority_markers:
        if marker not in raw_markers:
            continue
        marker_candidates = [
            row
            for row in candidates
            if marker in _portfolio_candidate_signature(row)["markers"]
        ]
        if len(marker_candidates) == 1:
            chosen = marker_candidates[0]
            return {
                "produto_padrao": repair_mojibake(str(chosen.get("SUBGRUPO_CIGAM") or product_name or "")),
                "subgrupo_cigam": repair_mojibake(str(chosen.get("SUBGRUPO_CIGAM") or "")),
                "subgrupo_litragem": repair_mojibake(str(chosen.get("SUBGRUPO_LITRAGEM") or "")),
                "qtde_cx": chosen.get("QTDE_CX"),
                "match_mode": "deterministic_keyword",
                "match_confidence": "high",
                "raw_normalized": raw_normalized,
            }
        if marker_candidates:
            candidates = marker_candidates
            break

    exact_candidates = [
        row
        for row in candidates
        if normalize_product_name(" ".join(
            part for part in [row.get("SUBGRUPO_CIGAM"), row.get("SUBGRUPO_LITRAGEM"), row.get("LITRAGEM")] if str(part).strip()
        )) in raw_normalized
    ]
    if len(exact_candidates) == 1:
        chosen = exact_candidates[0]
        return {
            "produto_padrao": repair_mojibake(str(chosen.get("SUBGRUPO_CIGAM") or product_name or "")),
            "subgrupo_cigam": repair_mojibake(str(chosen.get("SUBGRUPO_CIGAM") or "")),
            "subgrupo_litragem": repair_mojibake(str(chosen.get("SUBGRUPO_LITRAGEM") or "")),
            "qtde_cx": chosen.get("QTDE_CX"),
            "match_mode": "deterministic_exact",
            "match_confidence": "medium",
            "raw_normalized": raw_normalized,
        }

    subset_candidates = []
    raw_tokens = set(raw_normalized.split())
    for row in candidates:
        row_sig = _portfolio_candidate_signature(row)
        row_tokens = set(row_sig["normalized_text"].split())
        if row_tokens and row_tokens.issubset(raw_tokens):
            subset_candidates.append(row)
    if len(subset_candidates) == 1:
        chosen = subset_candidates[0]
        return {
            "produto_padrao": repair_mojibake(str(chosen.get("SUBGRUPO_CIGAM") or product_name or "")),
            "subgrupo_cigam": repair_mojibake(str(chosen.get("SUBGRUPO_CIGAM") or "")),
            "subgrupo_litragem": repair_mojibake(str(chosen.get("SUBGRUPO_LITRAGEM") or "")),
            "qtde_cx": chosen.get("QTDE_CX"),
            "match_mode": "deterministic_subset",
            "match_confidence": "medium",
            "raw_normalized": raw_normalized,
        }

    if candidates:
        chosen = candidates[0]
        return {
            "produto_padrao": repair_mojibake(str(product_name or "")),
            "subgrupo_cigam": "",
            "subgrupo_litragem": "",
            "qtde_cx": None,
            "match_mode": "unresolved",
            "match_confidence": "none",
            "raw_normalized": raw_normalized,
        }

    return {
        "produto_padrao": repair_mojibake(str(product_name or "")),
        "subgrupo_cigam": "",
        "subgrupo_litragem": "",
        "qtde_cx": None,
        "match_mode": "unresolved",
        "match_confidence": "none",
        "raw_normalized": raw_normalized,
    }


@dataclass(frozen=True)
class OfficialQuestionRoute:
    id: str
    title: str
    patterns: tuple[str, ...]
    sql: str
    source_note: str
    description: str
    examples: tuple[str, ...]


OFFICIAL_QUESTION_ROUTES: tuple[OfficialQuestionRoute, ...] = (
    OfficialQuestionRoute(
        id="lojas_hoje",
        title="Lojas com venda Aquafast",
        patterns=(
            r"\bquantas lojas\b",
            r"\bquantos lojas\b",
            r"\bquantas lojas existem\b",
            r"\btotal de lojas\b",
            r"\blojas na base\b",
            r"\bquantas lojas vendem aquafast\b",
            r"\blojas aquafast\b",
            r"\bvende aquafast\b",
            r"\bvendem aquafast\b",
            r"\baquafast presente\b",
            r"\bquantos pdvs\b",
        ),
        sql="SELECT COUNT(*) AS total_lojas FROM ranking_clientes",
        source_note="Fonte: `ranking_clientes`. A consulta conta as lojas/PDVs que vendem Aquafast no periodo carregado.",
        description="Quantidade de lojas/PDVs com venda Aquafast.",
        examples=("quantas lojas vendem aquafast hoje", "em quantas lojas a aquafast esta presente hoje"),
    ),
    OfficialQuestionRoute(
        id="pontos_venda",
        title="PDVs com venda Aquafast",
        patterns=(
            r"\bpontos de venda\b",
            r"\bponto de venda\b",
            r"\bquantos pontos de venda\b",
            r"\bquantos pontos\b",
            r"\btotal de pontos\b",
            r"\bpontos na base\b",
            r"\bpdv\b",
            r"\bpdvs\b",
            r"\bpresenca hoje\b",
            r"\bpresença hoje\b",
            r"\bpresente hoje\b",
        ),
        sql="SELECT COUNT(*) AS total_pontos_de_venda FROM ranking_clientes",
        source_note="Fonte: `ranking_clientes`. A consulta conta os pontos de venda que aparecem com venda Aquafast no periodo carregado.",
        description="Total de PDVs com Aquafast presente.",
        examples=("em quantos pdvs a aquafast esta presente hoje",),
    ),
    OfficialQuestionRoute(
        id="top_clientes",
        title="Top lojas Aquafast",
        patterns=(
            r"\branking clientes\b",
            r"\btop clientes\b",
            r"\btop\s+\d+\s+clientes\b",
            r"\bclientes aquafast\b",
            r"\blojas aquafast\b",
            r"\btotal de clientes\b",
            r"\bquantos clientes\b",
            r"\bclientes na base\b",
            r"\bqual o total de clientes\b",
        ),
        sql="SELECT * FROM ranking_clientes ORDER BY caixas_vendidas DESC, receita_total DESC, cliente LIMIT 20",
        source_note="Fonte: `ranking_clientes`. A consulta resume as lojas que vendem Aquafast por caixas vendidas, receita e recorrencia.",
        description="Ranking das lojas com maior volume de Aquafast.",
        examples=("top 20 clientes por valor", "top clientes aquafast por caixa"),
    ),
    OfficialQuestionRoute(
        id="top_produtos",
        title="Top produtos Aquafast",
        patterns=(
            r"\branking produtos\b",
            r"\bprodutos mais vendidos\b",
            r"\btop produtos\b",
            r"\btop\s+\d+\s+produtos\b",
        ),
        sql="SELECT * FROM ranking_produtos ORDER BY total_vendas DESC, receita_total DESC, produto LIMIT 20",
        source_note="Fonte: `ranking_produtos`. A consulta lista os produtos Aquafast com maior volume em caixas e receita, consolidados pelo mapeamento oficial de `SUBGRUPO_CIGAM`.",
        description="Ranking dos produtos Aquafast mais fortes.",
        examples=("top 20 produtos mais vendidos",),
    ),
    OfficialQuestionRoute(
        id="auditoria_produtos_sem_subgrupo_cigam",
        title="Auditoria produtos sem SUBGRUPO_CIGAM",
        patterns=(
            r"\bprodutos sem subgrupo cigam\b",
            r"\bprodutos sem padronizacao\b",
            r"\bauditoria produtos sem padronizacao\b",
            r"\bauditoria produtos sem padronização\b",
            r"\bquais produtos nao casam com o portfolio\b",
            r"\bquais produtos nao casam com o portifolio\b",
        ),
        sql="""
            SELECT *
            FROM auditoria_produtos_sem_subgrupo_cigam
            ORDER BY faturamento DESC, caixas_vendidas DESC, ocorrencias DESC, produto_original_scanntech
        """.strip(),
        source_note="Fonte: `auditoria_produtos_sem_subgrupo_cigam`. A consulta lista os produtos Aquafast sem correspondencia no portfolio e sugere SUBGRUPO_CIGAM apenas quando a similaridade e transparente.",
        description="Produtos Aquafast sem correspondencia no portfolio.",
        examples=("produtos sem subgrupo cigam", "auditoria produtos sem padronizacao"),
    ),
    OfficialQuestionRoute(
        id="receita_total",
        title="Receita total Aquafast",
        patterns=(r"\breceita total\b", r"\bfaturamento total\b", r"\bvalor total de vendas\b"),
        sql="""
            SELECT
                ROUND(SUM(receita_total), 2) AS receita_total,
                CAST(SUM(caixas_vendidas) AS BIGINT) AS caixas_vendidas,
                ROUND(SUM(receita_total) / NULLIF(SUM(caixas_vendidas), 0), 2) AS ticket_medio_caixa
            FROM ranking_clientes
        """.strip(),
        source_note="Fonte: `ranking_clientes`. A consulta agrega vendas Aquafast por lojas e mostra receita e ticket medio em caixas.",
        description="Receita total do universo Aquafast carregado.",
        examples=("qual a receita total",),
    ),
    OfficialQuestionRoute(
        id="ticket_medio",
        title="Ticket médio Aquafast",
        patterns=(r"\bticket medio\b", r"\bticket medio ponderado\b", r"\bticket medio geral\b"),
        sql="""
            SELECT
                ROUND(SUM(receita_total) / NULLIF(SUM(caixas_vendidas), 0), 2) AS ticket_medio_caixa_ponderado,
                ROUND(AVG(ticket_medio_caixa), 2) AS ticket_medio_simples_entre_lojas
            FROM ranking_clientes
        """.strip(),
        source_note="Fonte: `ranking_clientes`. A consulta calcula o ticket medio ponderado por caixas e a media simples entre lojas.",
        description="Ticket medio Aquafast por caixa.",
        examples=("qual e o ticket medio da aquafast",),
    ),
    OfficialQuestionRoute(
        id="vendas_mes",
        title="Vendas por mês",
        patterns=(
            r"\bvendas por mes\b",
            r"\bvendas mensais\b",
            r"\bvenda do ultimo mes\b",
            r"\bvenda no ultimo mes\b",
            r"\bqual foi a venda do ultimo mes\b",
            r"\bevolucao mensal\b",
            r"\bevolução de vendas\b",
            r"\bevolucao de vendas\b",
            r"\bhistorico de vendas\b",
            r"\bcomo estao as vendas\b",
            r"\bcomo est\u00e3o as vendas\b",
            r"\bperformance por mes\b",
            r"\bperformance por m\u00eas\b",
            r"\bserie mensal\b",
            r"\bqual foi o melhor mes\b",
            r"\bmelhor mes em faturamento\b",
            r"\bmes com maior faturamento\b",
            r"\bmes mais vendido\b",
            r"\bqual mes vendeu mais\b",
            r"\bqual foi o pior mes\b",
            r"\bpior mes em faturamento\b",
            r"\bmes com menor faturamento\b",
        ),
        sql="SELECT * FROM vendas_por_mes ORDER BY mes",
        source_note="Fonte: `vendas_por_mes`. A consulta consolida caixas e receita ao longo do tempo para mostrar tendencia mensal.",
        description="Evolucao mensal do mercado Aquafast.",
        examples=("vendas aquafast por mes",),
    ),
    OfficialQuestionRoute(
        id="vendas_estado",
        title="Vendas por estado",
        patterns=(r"\bvendas por estado\b", r"\bestado\b", r"\buf\b"),
        sql="SELECT * FROM vendas_caixas_estado ORDER BY receita_total DESC",
        source_note="Fonte: `vendas_caixas_estado`. A consulta cruza as vendas Aquafast com a UF para mostrar distribuicao geografica.",
        description="Distribuicao de vendas Aquafast por estado.",
        examples=("vendas aquafast por estado",),
    ),
    OfficialQuestionRoute(
        id="vendas_por_cidade",
        title="Presença por cidade",
        patterns=(
            r"\bcidades que a aquafast esta\b",
            r"\bcidades aquafast\b",
            r"\bem quais cidades\b",
            r"\bprincipais cidades\b",
            r"\bcidades presentes\b",
            r"\bonde a aquafast vende\b",
            r"\btop cidades\b",
            r"\btop\s+\d+\s+cidades\b",
        ),
        sql="SELECT * FROM vendas_por_cidade ORDER BY receita_total DESC LIMIT 10",
        source_note="Fonte: `vendas_por_cidade`. A consulta resume as cidades com venda Aquafast e ordena por faturamento.",
        description="Cidades com venda Aquafast ordenadas por receita.",
        examples=("em quais cidades a aquafast esta presente", "top 10 cidades por faturamento"),
    ),
    OfficialQuestionRoute(
        id="share_aquafast_por_categoria",
        title="Share Aquafast por categoria",
        patterns=(
            r"\bshare aquafast por categoria\b",
            r"\bparticipacao aquafast por categoria\b",
            r"\bparticipacao da aquafast por categoria\b",
            r"\bqual a participacao da aquafast por categoria\b",
        ),
        sql="""
            SELECT *
            FROM share_aquafast_por_categoria
            ORDER BY share_aquafast_pct DESC, faturamento_total_categoria DESC, categoria
        """.strip(),
        source_note="Fonte: `share_aquafast_por_categoria`. A consulta calcula o faturamento total da categoria, separa Aquafast e concorrentes e mostra a participacao da Aquafast.",
        description="Participacao da Aquafast por categoria.",
        examples=("share aquafast por categoria",),
    ),
    OfficialQuestionRoute(
        id="market_share",
        title="Market share por fabricante",
        patterns=(r"\bmarket share\b", r"\bparticipacao\b", r"\bshare\b", r"\bfabricantes\b"),
        sql="SELECT * FROM ms_mercado_aquafast ORDER BY total_receita DESC LIMIT 20",
        source_note="Fonte: `ms_mercado_aquafast`. A consulta mede a participacao de cada fabricante dentro do mercado da categoria.",
        description="Participacao por fabricante no mercado da categoria.",
        examples=("market share por fabricante",),
    ),
    OfficialQuestionRoute(
        id="concorrentes_por_categoria",
        title="Concorrentes por categoria",
        patterns=(
            r"\bconcorrentes por categoria\b",
            r"\bconcorrente por categoria\b",
            r"\bqual concorrente domina cada categoria\b",
            r"\bqual concorrente domina categoria\b",
        ),
        sql="""
            SELECT *
            FROM concorrentes_por_categoria
            ORDER BY categoria, ranking_categoria
        """.strip(),
        source_note="Fonte: `concorrentes_por_categoria`. A consulta separa Aquafast dos concorrentes e mostra faturamento, unidades e participacao dentro de cada categoria.",
        description="Concorrentes que dominam cada categoria.",
        examples=("concorrentes por categoria",),
    ),
    OfficialQuestionRoute(
        id="lojas_com_concorrente_sem_aquafast",
        title="Lojas com concorrente sem Aquafast",
        patterns=(
            r"\blojas com concorrente sem aquafast\b",
            r"\bonde concorrente vende e aquafast nao\b",
            r"\bquais lojas vendem concorrente mas nao vendem aquafast\b",
        ),
        sql="""
            SELECT *
            FROM lojas_com_concorrente_sem_aquafast
            ORDER BY faturamento_concorrente DESC, unidades_scanntech DESC, loja, categoria, concorrente
        """.strip(),
        source_note="Fonte: `lojas_com_concorrente_sem_aquafast`. A consulta usa PDV_ID como chave principal para amarrar a venda Ã  loja e expõe `status_loja` quando a ligaÃ§Ã£o nao existir.",
        description="Lojas que vendem concorrente mas nao vendem Aquafast.",
        examples=("lojas com concorrente sem aquafast",),
    ),
    OfficialQuestionRoute(
        id="top_concorrentes_por_cidade",
        title="Top concorrentes por cidade",
        patterns=(
            r"\btop concorrentes por cidade\b",
            r"\bconcorrentes por cidade\b",
        ),
        sql="""
            SELECT *
            FROM top_concorrentes_por_cidade
            ORDER BY cidade, ranking_cidade
        """.strip(),
        source_note="Fonte: `top_concorrentes_por_cidade`. A consulta mostra quais concorrentes mais faturam em cada cidade e UF.",
        description="Concorrentes mais fortes por cidade.",
        examples=("top concorrentes por cidade",),
    ),
    OfficialQuestionRoute(
        id="historico_consultas",
        title="Historico de consultas",
        patterns=(
            r"\bhistorico de consultas\b",
            r"\bhistorico consultas\b",
            r"\bultimas consultas\b",
            r"\bquais relatorios eu consultei\b",
            r"\bhistorico das consultas\b",
        ),
        sql="""
            SELECT
              timestamp AS data_hora,
              pergunta,
              report_name AS relatorio,
              metric,
              rows_returned AS linhas_retornadas,
              status
            FROM aquafast_query_history
            ORDER BY timestamp DESC, id DESC
            LIMIT 20
        """.strip(),
        source_note="Fonte: `aquafast_query_history`. A consulta mostra apenas as 20 consultas deterministicas mais recentes.",
        description="Historico das consultas deterministicas registradas pelo Scanntech Analyst.",
        examples=("historico de consultas",),
    ),
    OfficialQuestionRoute(
        id="concorrentes_crescimento_90_dias",
        title="Concorrentes em crescimento 90 dias",
        patterns=(
            r"\bconcorrentes crescimento 90 dias\b",
            r"\bconcorrentes em crescimento 90 dias\b",
            r"\bqual concorrente mais cresce nos ultimos 90 dias\b",
        ),
        sql="""
            SELECT *
            FROM concorrentes_crescimento_90_dias
            ORDER BY variacao_abs DESC, faturamento_90d DESC, concorrente, categoria
        """.strip(),
        source_note="Fonte: `concorrentes_crescimento_90_dias`. A consulta compara os 3 meses mais recentes com os 3 meses anteriores como proxy transparente de 90 dias.",
        description="Concorrentes em crescimento nos ultimos 90 dias.",
        examples=("concorrentes em crescimento 90 dias",),
    ),
    OfficialQuestionRoute(
        id="maior_concorrente",
        title="Maior concorrente Aquafast",
        patterns=(r"\bmaior concorrente\b", r"\bconcorrentes\b", r"\bconcorrencia\b", r"\bcompetidor\b"),
        sql="""
            SELECT
              fabricante,
              skus,
              pdvs,
              total_unidades,
              total_receita,
              market_share_pct
            FROM ms_mercado_aquafast
            WHERE LOWER(fabricante) <> 'aquafast'
            ORDER BY total_receita DESC, market_share_pct DESC, fabricante
            LIMIT 10
        """.strip(),
        source_note="Fonte: `ms_mercado_aquafast`. A consulta compara os fabricantes do mercado da categoria e exclui a Aquafast para apontar concorrentes.",
        description="Principal concorrente da Aquafast no mercado da categoria.",
        examples=("qual o maior concorrente de aquafast",),
    ),
    OfficialQuestionRoute(
        id="ranking_redes",
        title="Redes com Aquafast",
        patterns=(
            r"\branking de redes\b",
            r"\brede\b",
            r"\bbandeira\b",
            r"\bquantas redes\b",
            r"\bquantas redes existem\b",
            r"\btotal de redes\b",
            r"\bredes na base\b",
        ),
        sql="SELECT * FROM ranking_redes ORDER BY total_receita DESC LIMIT 20",
        source_note="Fonte: `ranking_redes`. A consulta resume redes e tipos de loja com venda Aquafast.",
        description="Performance de redes e tipos de loja.",
        examples=("ranking de redes aquafast",),
    ),
    OfficialQuestionRoute(
        id="mix_categoria",
        title="Produtos por categoria",
        patterns=(r"\bcategoria\b", r"\bmix\b", r"\blitragem\b", r"\bproduto por categoria\b"),
        sql="SELECT * FROM top_produtos_categoria ORDER BY caixas_vendidas DESC, produto_padrao LIMIT 50",
        source_note="Fonte: `top_produtos_categoria`. A consulta cruza o portfolio Aquafast com caixas e consolida os produtos pelo mapeamento oficial de `SUBGRUPO_CIGAM`.",
        description="Mix de produtos e categorias da Aquafast.",
        examples=("produto por categoria aquafast",),
    ),
    OfficialQuestionRoute(
        id="potencial_venda",
        title="Potencial de venda",
        patterns=(
            r"\bpotencial de venda\b",
            r"\bpotencial de crescimento\b",
            r"\boportunidade de crescimento\b",
            r"\boportunidades de crescimento\b",
            r"\bprodutos com oportunidade\b",
            r"\bprodutos com oportunidades\b",
            r"\bonde crescer\b",
            r"\bpotencial\b",
            r"\bo que vender\b",
            r"\bonde a aquafast pode crescer\b",
        ),
        sql="""
            SELECT
                produto_padrao,
                produto_original_exemplo,
                subgrupo_cigam,
                variacoes_produto_original,
                categoria,
                fabricante,
                marca,
                pdvs_com_venda,
                caixas_vendidas,
                total_receita,
                preco_medio_caixa
            FROM top_produtos_categoria
            ORDER BY pdvs_com_venda DESC, caixas_vendidas DESC, total_receita DESC, produto_padrao
            LIMIT 20
        """.strip(),
        source_note="Fonte: `top_produtos_categoria`. A consulta usa a presença em PDVs e o volume em caixas como proxy de potencial de venda, consolidado pelo mapeamento oficial de `SUBGRUPO_CIGAM`.",
        description="Produtos com maior potencial de expansão na rede.",
        examples=("quais produtos teriam mais potencial de venda",),
    ),
    OfficialQuestionRoute(
        id="total_produtos",
        title="Total de produtos",
        patterns=(r"\bquantos produtos\b", r"\btotal de produtos\b", r"\bquantos skus\b"),
        sql="SELECT COUNT(DISTINCT produto_padrao) AS total_produtos FROM ranking_produtos",
        source_note="Fonte: `ranking_produtos`. A consulta conta os produtos distintos do portfolio Aquafast carregado, priorizando o mapeamento oficial de `SUBGRUPO_CIGAM`.",
        description="Quantidade de produtos distintos do portfolio.",
        examples=("quantos produtos aquafast temos",),
    ),
    OfficialQuestionRoute(
        id="lojas_90d",
        title="Lojas sem compra 90d",
        patterns=(r"\b90 dias\b", r"\bsem compra\b", r"\bchurn\b"),
        sql="""
            SELECT cliente, ultima_compra, caixas_vendidas, receita_total
            FROM ranking_clientes
            WHERE ultima_compra < CURRENT_DATE - INTERVAL '90 days'
            ORDER BY receita_total DESC
            LIMIT 50
        """.strip(),
        source_note="Fonte: `ranking_clientes`. A consulta identifica lojas sem compra recente para apoiar a leitura de churn.",
        description="Lista de lojas com risco de churn por inatividade.",
        examples=("clientes sem compra ha 90 dias",),
    ),
    OfficialQuestionRoute(
        id="uma_compra",
        title="Lojas com 1 compra",
        patterns=(r"\b1 compra\b", r"\buma compra\b", r"\bapenas uma compra\b"),
        sql="""
            SELECT cliente, caixas_vendidas, receita_total, primeira_compra, ultima_compra
            FROM ranking_clientes
            WHERE caixas_vendidas = 1
            ORDER BY receita_total DESC
            LIMIT 50
        """.strip(),
        source_note="Fonte: `ranking_clientes`. A consulta mostra lojas com apenas uma compra registrada no periodo.",
        description="Lojas com baixa recorrencia.",
        examples=("lojas com apenas 1 compra",),
    ),
    OfficialQuestionRoute(
        id="maior_categoria",
        title="Categorias líderes",
        patterns=(r"\bmaior categoria\b", r"\bcategoria com maior receita\b", r"\btop categorias\b"),
        sql="""
            SELECT
                categoria,
                ROUND(SUM(caixas_vendidas), 1) AS caixas_vendidas,
                ROUND(SUM(receita_total), 2) AS receita_total
            FROM top_produtos_categoria
            GROUP BY categoria
            ORDER BY receita_total DESC, caixas_vendidas DESC, categoria
            LIMIT 10
        """.strip(),
        source_note="Fonte: `top_produtos_categoria`. A consulta consolida por categoria para ver onde a Aquafast é mais forte.",
        description="Categorias com maior peso de receita.",
        examples=("qual categoria vende mais",),
    ),
    OfficialQuestionRoute(
        id="maior_estado",
        title="Estados líderes",
        patterns=(r"\bmaior estado\b", r"\bestado com maior receita\b", r"\btop estados\b"),
        sql="""
            SELECT
                estado,
                ROUND(SUM(caixas_vendidas), 1) AS caixas_vendidas,
                ROUND(SUM(receita_total), 2) AS receita_total
            FROM vendas_caixas_estado
            GROUP BY estado
            ORDER BY receita_total DESC, caixas_vendidas DESC, estado
            LIMIT 10
        """.strip(),
        source_note="Fonte: `vendas_caixas_estado`. A consulta consolida por UF para mostrar a força regional da Aquafast.",
        description="Estados com maior receita Aquafast.",
        examples=("qual estado vende mais aquafast",),
    ),
    OfficialQuestionRoute(
        id="maior_rede",
        title="Redes líderes",
        patterns=(r"\bmaior rede\b", r"\brede com maior receita\b", r"\btop redes\b"),
        sql="""
            SELECT
                rede,
                tipo_loja,
                total_lojas,
                caixas_vendidas,
                total_receita
            FROM ranking_redes
            ORDER BY total_receita DESC, caixas_vendidas DESC, rede
            LIMIT 10
        """.strip(),
        source_note="Fonte: `ranking_redes`. A consulta resume o desempenho por rede e tipo de loja.",
        description="Redes e tipos de loja mais relevantes.",
        examples=("qual rede vende mais aquafast",),
    ),
    OfficialQuestionRoute(
        id="resumo_geral",
        title="Resumo geral",
        patterns=(r"\bresumo geral\b", r"\bvisao geral\b", r"\bvisão geral\b"),
        sql="""
            SELECT
                COUNT(*) AS total_registros,
                COUNT(DISTINCT cliente) AS total_clientes,
                ROUND(SUM(receita_total), 2) AS receita_total,
                ROUND(AVG(ticket_medio_caixa), 2) AS ticket_medio_geral,
                MIN(primeira_compra) AS periodo_inicio,
                MAX(ultima_compra) AS periodo_fim
            FROM ranking_clientes
        """.strip(),
        source_note="Fonte: `ranking_clientes`. A consulta resume o periodo carregado com clientes, receita e ticket medio.",
        description="Resumo executivo da base Aquafast.",
        examples=("resumo geral da aquafast",),
    ),
)

OFFICIAL_QUESTION_DISPLAY_TITLES: dict[str, tuple[str, ...]] = {
    "lojas_hoje": ("Lojas com Aquafast hoje",),
    "pontos_venda": ("PDVs com Aquafast hoje",),
    "top_clientes": ("Top lojas Aquafast",),
    "top_produtos": ("Top produtos Aquafast",),
    "receita_total": ("Receita total Aquafast",),
    "ticket_medio": ("Ticket médio Aquafast",),
    "vendas_mes": ("Vendas por mês",),
    "vendas_estado": ("Vendas por estado",),
    "vendas_por_cidade": ("Presença por cidade",),
    "market_share": ("Market share por fabricante",),
    "concorrentes_por_categoria": ("Concorrentes por categoria",),
    "share_aquafast_por_categoria": ("Share Aquafast por categoria",),
    "lojas_com_concorrente_sem_aquafast": ("Lojas com concorrente sem Aquafast",),
    "top_concorrentes_por_cidade": ("Top concorrentes por cidade",),
    "historico_consultas": ("Historico de consultas",),
    "concorrentes_crescimento_90_dias": ("Concorrentes em crescimento 90 dias",),
    "maior_concorrente": ("Maior concorrente Aquafast",),
    "ranking_redes": ("Redes com Aquafast",),
    "mix_categoria": ("Produtos por categoria",),
    "potencial_venda": ("Potencial de venda",),
    "total_produtos": ("Total de produtos",),
    "lojas_90d": ("Lojas sem compra há 90 dias",),
    "uma_compra": ("Lojas com 1 compra",),
    "maior_categoria": ("Categorias líderes",),
    "maior_estado": ("Estados líderes",),
    "maior_rede": ("Redes líderes",),
    "resumo_geral": ("Resumo geral Aquafast",),
}



def _extract_limit(question: str, default: int = 10) -> int:
    q = normalize_business_question(question)
    m = re.search(
        r"\b(?:top|liste(?:\s+(?:os|as))?|mostre(?:\s+(?:os|as))?|quais?\s+(?:os|as))?\s*(\d+)\s*"
        r"(?:principais?|maiores?|menores?|primeiros?|primeiras?|produtos?|"
        r"cidades?|clientes?|concorrentes?|lojas?|redes?)?",
        q,
    )
    if m:
        n = int(m.group(1))
        return min(max(n, 1), 200)
    return default


def resolve_official_route(question: str) -> OfficialQuestionRoute | None:
    q = normalize_business_question(question)
    for route in OFFICIAL_QUESTION_ROUTES:
        if any(re.search(pattern, q) for pattern in route.patterns):
            if route.id == "vendas_mes":
                best_terms = (
                    "melhor mes",
                    "mes com maior faturamento",
                    "mes mais vendido",
                    "qual mes vendeu mais",
                )
                worst_terms = (
                    "pior mes",
                    "mes com menor faturamento",
                )
                if any(term in q for term in best_terms):
                    sql = "SELECT * FROM vendas_por_mes ORDER BY receita DESC LIMIT 1"
                    return OfficialQuestionRoute(
                        id=route.id,
                        title=route.title,
                        patterns=route.patterns,
                        sql=sql,
                        source_note=route.source_note,
                        description=route.description,
                        examples=route.examples,
                    )
                if any(term in q for term in worst_terms):
                    sql = "SELECT * FROM vendas_por_mes ORDER BY receita ASC LIMIT 1"
                    return OfficialQuestionRoute(
                        id=route.id,
                        title=route.title,
                        patterns=route.patterns,
                        sql=sql,
                        source_note=route.source_note,
                        description=route.description,
                        examples=route.examples,
                    )
            if route.id in {"top_clientes", "top_produtos", "vendas_por_cidade", "maior_concorrente", "ranking_redes"}:
                base_limit = 10 if route.id in {"vendas_por_cidade", "maior_concorrente"} else 20
                n = _extract_limit(question, base_limit)
                if route.id == "ranking_redes" or n != base_limit:
                    sql = route.sql.replace(f"LIMIT {base_limit}", f"LIMIT {n}")
                    return OfficialQuestionRoute(
                        id=route.id,
                        title=route.title,
                        patterns=route.patterns,
                        sql=sql,
                        source_note=route.source_note,
                        description=route.description,
                        examples=route.examples,
                    )
            return route
    return None


def match_route(question: str) -> str | None:
    route = resolve_official_route(question)
    return route.id if route is not None else None


def list_official_questions() -> list[dict[str, str | list[str]]]:
    return [
        {
            "id": repair_mojibake(route.id),
            "title": repair_mojibake(route.title),
            "title_lines": [
                repair_mojibake(part)
                for part in OFFICIAL_QUESTION_DISPLAY_TITLES.get(route.id, (route.title,))
            ],
            "description": repair_mojibake(route.description),
            "examples": " | ".join(repair_mojibake(example) for example in route.examples),
            "source_note": repair_mojibake(route.source_note),
        }
        for route in OFFICIAL_QUESTION_ROUTES
    ]
