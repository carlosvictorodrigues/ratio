from __future__ import annotations

import anyio
import inspect
import logging
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

log = logging.getLogger(__name__)

from backend.escritorio.models import RatioEscritorioState, TeseJuridica
from backend.escritorio.planning import (
    decompose_case_with_gemini,
    plan_legislation_queries_with_gemini,
)
from backend.escritorio.redaction import (
    build_section_evidence_pack,
    generate_sections_with_gemini,
    infer_section_provenance,
)
from backend.escritorio.tools.google_search import search_google_legislation
from backend.escritorio.tools.ratio_tools import merge_ranked_results, search_tese_bundle


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


def _dedupe_teses(teses: list[TeseJuridica]) -> list[TeseJuridica]:
    """Remove teses with identical descriptions (case/whitespace-insensitive)."""
    import re as _re
    seen: set[str] = set()
    unique: list[TeseJuridica] = []
    for t in teses:
        key = _re.sub(r"\s+", " ", (t.descricao or "").strip().lower())
        if key and key not in seen:
            seen.add(key)
            unique.append(t)
    if unique:
        return unique
    return teses  # never return empty


async def decompose_case_into_teses(
    state: RatioEscritorioState,
    *,
    decompose_case_fn: Callable[[RatioEscritorioState], Any] | None = None,
) -> list[TeseJuridica]:
    if state.teses:
        return _dedupe_teses(list(state.teses))

    active_decompose = decompose_case_fn or decompose_case_with_gemini
    try:
        decomposed = await active_decompose(state)
        if decomposed:
            return _dedupe_teses([
                item if isinstance(item, TeseJuridica) else TeseJuridica.model_validate(item)
                for item in decomposed
            ])
    except Exception:
        pass

    return _fallback_teses(state)


async def pesquisar_teses(
    state: RatioEscritorioState,
    *,
    decompose_case_fn: Callable[[RatioEscritorioState], Any] | None = None,
    search_bundle_fn: Callable[..., Any] | None = None,
    legislation_search_fn: Callable[[str], Any] | None = None,
    legislation_query_plan_fn: Callable[[RatioEscritorioState, list[TeseJuridica]], Any] | None = None,
    on_tese_result: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    teses = await decompose_case_into_teses(
        state,
        decompose_case_fn=decompose_case_fn,
    )
    log.info("pesquisar_teses: %d teses decompostas", len(teses))
    for _i, _t in enumerate(teses, start=1):
        log.info("  tese %d [%s/%s]: %s", _i, _t.id, _t.tipo, (_t.descricao or "")[:120])
    active_search_bundle = search_bundle_fn or search_tese_bundle
    active_legislation_search = legislation_search_fn or _search_legislation
    active_legislation_query_plan = legislation_query_plan_fn or plan_legislation_queries_with_gemini
    enriched_teses: list[dict[str, Any]] = []
    jurisprudencia: list[dict[str, Any]] = []
    legislacao: list[dict[str, Any]] = []
    legislacao_complementar: list[dict[str, Any]] = []

    for tese in teses:
        log.info("pesquisar_teses: iniciando busca para tese %s", tese.id)

        async def _search_legislacao_tese(_descricao=tese.descricao):
            result = active_legislation_search(_descricao)
            if callable(getattr(result, "__await__", None)):
                return await result
            return result

        bundle = await active_search_bundle(
            favoravel_query=tese.descricao,
            contraria_query=None,
            legislacao_operation=_search_legislacao_tese,
        )
        resposta_pesquisa = str((bundle.get("jurisprudencia_favoravel") or {}).get("answer") or "").strip()
        docs_favor = list((bundle.get("jurisprudencia_favoravel") or {}).get("docs", []))
        docs_contra = list((bundle.get("jurisprudencia_contraria") or {}).get("docs", []))
        docs_lei = list(bundle.get("legislacao") or [])

        tese_data = tese.model_dump(mode="json")
        tese_data["resposta_pesquisa"] = resposta_pesquisa
        tese_data["jurisprudencia_favoravel"] = docs_favor
        tese_data["jurisprudencia_contraria"] = docs_contra
        tese_data["legislacao"] = docs_lei
        enriched_teses.append(tese_data)
        jurisprudencia.extend(docs_favor)
        jurisprudencia.extend(docs_contra)
        legislacao.extend(docs_lei)

        if on_tese_result is not None:
            partial_delta = {
                "teses": list(enriched_teses),
                "pesquisa_jurisprudencia": list(jurisprudencia),
                "pesquisa_legislacao": list(legislacao),
                "pesquisa_legislacao_complementar": list(legislacao_complementar),
                "status": "pesquisa",
                "workflow_stage": "pesquisa",
            }
            callback_result = on_tese_result(partial_delta)
            if inspect.isawaitable(callback_result):
                await callback_result

    planned_queries = active_legislation_query_plan(state, teses)
    if inspect.isawaitable(planned_queries):
        planned_queries = await planned_queries

    for query_item in list(planned_queries or []):
        consulta = " ".join(str(query_item.get("consulta") or "").split()).strip()
        categoria = str(query_item.get("categoria") or "material").strip().lower() or "material"
        if not consulta:
            continue
        rows = active_legislation_search(consulta)
        if callable(getattr(rows, "__await__", None)):
            rows = await rows
        normalized_rows = []
        for row in list(rows or []):
            normalized = dict(row)
            normalized.setdefault("categoria", categoria)
            normalized.setdefault("query_origem", consulta)
            normalized.setdefault("estrategia", "complementar")
            normalized_rows.append(normalized)
        legislacao_complementar.extend(normalized_rows)
        legislacao.extend(normalized_rows)

    return {
        "teses": enriched_teses,
        "pesquisa_jurisprudencia": jurisprudencia,
        "pesquisa_legislacao": legislacao,
        "pesquisa_legislacao_complementar": legislacao_complementar,
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
    return await anyio.to_thread.run_sync(lambda: search_google_legislation(query, limit=10))


def curadoria_node(state: RatioEscritorioState) -> dict[str, Any]:
    return {
        "pesquisa_jurisprudencia": _dedupe_rows(state.pesquisa_jurisprudencia),
        "pesquisa_legislacao": _dedupe_rows(state.pesquisa_legislacao),
        "pesquisa_legislacao_complementar": _dedupe_rows(state.pesquisa_legislacao_complementar),
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
