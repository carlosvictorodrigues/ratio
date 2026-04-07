from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from backend.escritorio.models import RatioEscritorioState, TeseJuridica
from backend.escritorio.planning import decompose_case_with_gemini
from backend.escritorio.redaction import (
    build_section_evidence_pack,
    generate_sections_with_gemini,
    infer_section_provenance,
)
from backend.escritorio.tools.ratio_tools import merge_ranked_results, ratio_search, search_tese_bundle


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = merge_ranked_results(list(rows or []))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in ranked:
        key = str(row.get("doc_id") or row.get("processo") or "").strip()
        if not key:
            key = f"fallback:{len(deduped)}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _fallback_teses(state: RatioEscritorioState) -> list[TeseJuridica]:
    if state.teses:
        return list(state.teses)
    descricao = (state.fatos_brutos or "Tese principal do caso").strip()
    return [TeseJuridica(id="t1", descricao=descricao[:160], tipo="principal")]


async def decompose_case_into_teses(
    state: RatioEscritorioState,
    *,
    decompose_case_fn: Callable[[RatioEscritorioState], Any] | None = None,
) -> list[TeseJuridica]:
    if state.teses:
        return list(state.teses)

    active_decompose = decompose_case_fn or decompose_case_with_gemini
    try:
        decomposed = await active_decompose(state)
        if decomposed:
            return [
                item if isinstance(item, TeseJuridica) else TeseJuridica.model_validate(item)
                for item in decomposed
            ]
    except Exception:
        pass

    return _fallback_teses(state)


async def pesquisar_teses(
    state: RatioEscritorioState,
    *,
    decompose_case_fn: Callable[[RatioEscritorioState], Any] | None = None,
    search_bundle_fn: Callable[..., Any] | None = None,
    legislation_search_fn: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    teses = await decompose_case_into_teses(
        state,
        decompose_case_fn=decompose_case_fn,
    )
    active_search_bundle = search_bundle_fn or search_tese_bundle
    active_legislation_search = legislation_search_fn or _search_legislation
    enriched_teses: list[dict[str, Any]] = []
    jurisprudencia: list[dict[str, Any]] = []
    legislacao: list[dict[str, Any]] = []

    for tese in teses:
        async def _search_legislacao_tese():
            result = active_legislation_search(tese.descricao)
            if callable(getattr(result, "__await__", None)):
                return await result
            return result

        bundle = await active_search_bundle(
            favoravel_query=tese.descricao,
            contraria_query=tese.descricao,
            legislacao_operation=_search_legislacao_tese,
        )
        docs_favor = list((bundle.get("jurisprudencia_favoravel") or {}).get("docs", []))
        docs_contra = list((bundle.get("jurisprudencia_contraria") or {}).get("docs", []))
        docs_lei = list(bundle.get("legislacao") or [])

        tese_data = tese.model_dump(mode="json")
        tese_data["jurisprudencia_favoravel"] = docs_favor
        tese_data["jurisprudencia_contraria"] = docs_contra
        tese_data["legislacao"] = docs_lei
        enriched_teses.append(tese_data)
        jurisprudencia.extend(docs_favor)
        jurisprudencia.extend(docs_contra)
        legislacao.extend(docs_lei)

    return {
        "teses": enriched_teses,
        "pesquisa_jurisprudencia": jurisprudencia,
        "pesquisa_legislacao": legislacao,
        "status": "pesquisa",
        "workflow_stage": "pesquisa",
    }


async def pesquisador_node(state: RatioEscritorioState) -> dict[str, Any]:
    return await pesquisar_teses(state)


def make_pesquisador_node(search_bundle_fn: Callable[..., Any]) -> Callable[[RatioEscritorioState], dict[str, Any]]:
    async def _node(state: RatioEscritorioState) -> dict[str, Any]:
        return await pesquisar_teses(state, search_bundle_fn=search_bundle_fn)

    return _node


async def _search_legislation(query: str) -> list[dict[str, Any]]:
    result = await ratio_search(query, prefer_recent=True, persona="parecer")
    return list(result.get("docs", []))[:10]


def curadoria_node(state: RatioEscritorioState) -> dict[str, Any]:
    return {
        "pesquisa_jurisprudencia": _dedupe_rows(state.pesquisa_jurisprudencia),
        "pesquisa_legislacao": _dedupe_rows(state.pesquisa_legislacao),
        "status": "gate2",
        "workflow_stage": "gate2",
    }


def gate2_node(state: RatioEscritorioState) -> dict[str, Any]:
    return {
        "status": "gate2",
        "workflow_stage": "gate2",
    }


def gate2_router(state: RatioEscritorioState) -> str:
    return "redigir" if state.gate2_aprovado else "buscar_mais"


async def redator_node(state: RatioEscritorioState) -> dict[str, Any]:
    sections = await generate_sections_with_gemini(state)
    provenance = infer_section_provenance(sections)
    evidence_pack = build_section_evidence_pack(state, sections)
    return {
        "peca_sections": sections,
        "proveniencia": provenance,
        "evidence_pack": evidence_pack,
        "status": "redacao",
        "workflow_stage": "redacao",
    }


def build_drafting_graph(
    *,
    pesquisador_fn: Callable[[RatioEscritorioState], dict[str, Any]] | None = None,
    redator_fn: Callable[[RatioEscritorioState], dict[str, Any]] | None = None,
    gate2_router_fn: Callable[[RatioEscritorioState], str] | None = None,
    enable_interrupts: bool = True,
):
    graph = StateGraph(RatioEscritorioState)
    graph.add_node("pesquisador", pesquisador_fn or pesquisador_node)
    graph.add_node("curadoria", curadoria_node)
    graph.add_node("gate2", gate2_node)
    graph.add_node("redator", redator_fn or redator_node)
    graph.add_edge(START, "pesquisador")
    graph.add_edge("pesquisador", "curadoria")
    graph.add_edge("curadoria", "gate2")
    graph.add_conditional_edges(
        "gate2",
        gate2_router_fn or gate2_router,
        {"buscar_mais": "pesquisador", "redigir": "redator"},
    )
    graph.add_edge("redator", END)
    interrupt_before = ["gate2"] if enable_interrupts else []
    return graph.compile(interrupt_before=interrupt_before)
