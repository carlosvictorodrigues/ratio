from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from typing import Any, Awaitable, Callable

import anyio

log = logging.getLogger(__name__)


def _parse_date_key(raw_value: str) -> tuple[int, int, int]:
    value = str(raw_value or "").strip()
    if not value:
        return (0, 0, 0)

    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(value, fmt)
            return (parsed.year, parsed.month, parsed.day)
        except ValueError:
            continue
    return (0, 0, 0)


def merge_ranked_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            float(row.get("_final_score", 0.0)),
            _parse_date_key(str(row.get("data_julgamento", ""))),
        ),
        reverse=True,
    )


async def run_with_retry(
    operation: Callable[[], Awaitable[Any]],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    jitter: float = 0.2,
    sleep_func: Callable[[float], Awaitable[Any]] = anyio.sleep,
) -> Any:
    max_attempts = max(1, int(attempts))
    last_error: Exception | None = None

    op_name = getattr(operation, "__name__", None) or repr(operation)
    for attempt_index in range(max_attempts):
        try:
            return await operation()
        except Exception as exc:
            last_error = exc
            log.warning(
                "run_with_retry: %s falhou tentativa %d/%d: %s",
                op_name, attempt_index + 1, max_attempts, exc,
            )
            if attempt_index >= max_attempts - 1:
                break

            wait_seconds = max(0.0, float(base_delay)) * (2 ** attempt_index)
            if jitter > 0:
                wait_seconds += random.uniform(0.0, float(jitter))
            await sleep_func(wait_seconds)

    if last_error is None:
        raise RuntimeError("run_with_retry falhou sem erro capturado")
    raise last_error


def _get_run_query() -> Callable[..., Any]:
    from rag.query import run_query

    return run_query


async def ratio_search(
    query: str,
    *,
    run_query_fn: Callable[..., Any] | None = None,
    prefer_recent: bool = True,
    persona: str = "parecer",
    reranker_backend: str | None = None,
    sources: list[str] | None = None,
    tribunais: list[str] | None = None,
    tipos: list[str] | None = None,
    ramos: list[str] | None = None,
    orgaos: list[str] | None = None,
    relator_contains: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return {"answer": "", "docs": [], "meta": {"skipped_empty_query": True}}

    runner = run_query_fn or _get_run_query()

    def _invoke() -> dict[str, Any]:
        kwargs = dict(
            query=normalized_query,
            sources=sources,
            tribunais=tribunais,
            tipos=tipos,
            ramos=ramos,
            orgaos=orgaos,
            relator_contains=relator_contains,
            date_from=date_from,
            date_to=date_to,
            prefer_recent=prefer_recent,
            persona=persona,
            return_meta=True,
        )
        if reranker_backend:
            kwargs["reranker_backend"] = reranker_backend
        try:
            answer, docs, meta = runner(**kwargs)
        except RuntimeError as exc:
            message = str(exc).lower()
            if "reranker" not in message or reranker_backend == "gemini":
                raise
            kwargs["reranker_backend"] = "gemini"
            answer, docs, meta = runner(**kwargs)
        return {
            "answer": answer,
            "docs": merge_ranked_results(list(docs or [])),
            "meta": meta or {},
        }

    return await anyio.to_thread.run_sync(_invoke)


async def search_tese_bundle(
    *,
    favoravel_query: str,
    contraria_query: str | None,
    legislacao_operation: Callable[[], Awaitable[Any]],
    ratio_search_fn: Callable[..., Awaitable[dict[str, Any]]] = ratio_search,
) -> dict[str, Any]:
    favoravel_coro = ratio_search_fn(
        favoravel_query,
        prefer_recent=True,
        persona="parecer",
        reranker_backend="local",
    )
    if contraria_query:
        contraria_coro = ratio_search_fn(
            contraria_query,
            prefer_recent=True,
            persona="parecer",
            reranker_backend="local",
        )
    else:
        async def _empty_contraria():
            return {"answer": "", "docs": [], "meta": {}}
        contraria_coro = _empty_contraria()

    favoravel, contraria, legislacao = await asyncio.gather(
        favoravel_coro,
        contraria_coro,
        run_with_retry(legislacao_operation),
    )

    return {
        "jurisprudencia_favoravel": favoravel,
        "jurisprudencia_contraria": contraria,
        "legislacao": legislacao,
    }
