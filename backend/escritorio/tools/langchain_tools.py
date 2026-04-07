from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from backend.escritorio.tools import ratio_tools
from backend.escritorio.tools.lancedb_access import LanceDBReadonlyRegistry
from backend.escritorio.verifier import verify_citation_reference


@tool
async def buscar_jurisprudencia_favoravel(
    query: str,
    tese: str,
    tribunais: list[str] | None = None,
    limite: int = 10,
) -> list[dict[str, Any]]:
    """Busca jurisprudencia favoravel a uma tese juridica especifica."""

    result = await ratio_tools.ratio_search(
        f"{tese}: {query}",
        tribunais=tribunais,
        prefer_recent=True,
        persona="parecer",
    )
    return list(result.get("docs", []))[:limite]


@tool
async def buscar_jurisprudencia_contraria(
    query: str,
    tese: str,
    tribunais: list[str] | None = None,
    limite: int = 5,
) -> list[dict[str, Any]]:
    """Busca jurisprudencia contraria a uma tese juridica."""

    result = await ratio_tools.ratio_search(
        f"jurisprudencia contraria a: {tese}. Situacao: {query}",
        tribunais=tribunais,
        prefer_recent=True,
        persona="parecer",
    )
    return list(result.get("docs", []))[:limite]


@tool
async def buscar_legislacao(termos: str, codigo: str | None = None) -> list[dict[str, Any]]:
    """Busca legislacao pertinente na tool layer atual do Escritorio."""

    prefix = f"{codigo}: " if codigo else ""
    result = await ratio_tools.ratio_search(
        f"{prefix}{termos}",
        prefer_recent=True,
        persona="parecer",
    )
    return list(result.get("docs", []))[:10]


@tool
def verificar_citacao(referencia: str) -> dict[str, Any]:
    """Extrai e prepara candidatos para verificacao deterministica."""
    try:
        from rag.query import LANCE_DIR
    except Exception:
        return {"exists": False, "level": "unverified", "referencia": referencia, "candidates": []}

    registry = LanceDBReadonlyRegistry()
    return verify_citation_reference(
        referencia,
        registry=registry,
        lance_dir=LANCE_DIR,
        table_name="jurisprudencia",
    )


@tool
async def buscar_acervo(query: str, limite: int = 5) -> list[dict[str, Any]]:
    """Busca no acervo do usuario via source user."""

    result = await ratio_tools.ratio_search(
        query,
        sources=["user"],
        prefer_recent=False,
        persona="parecer",
    )
    return list(result.get("docs", []))[:limite]


TOOLS_PESQUISADOR = [
    buscar_jurisprudencia_favoravel,
    buscar_jurisprudencia_contraria,
    buscar_legislacao,
    buscar_acervo,
]

TOOLS_CONTRAPARTE = [
    buscar_jurisprudencia_contraria,
    buscar_legislacao,
]
