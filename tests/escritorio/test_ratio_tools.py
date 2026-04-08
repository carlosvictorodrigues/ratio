import pytest

from backend.escritorio.tools.ratio_tools import (
    merge_ranked_results,
    ratio_search,
    run_with_retry,
    search_tese_bundle,
)


def test_merge_ranked_results_prefers_more_recent_document_when_scores_tie():
    merged = merge_ranked_results(
        [
            {"doc_id": "old", "_final_score": 0.9, "data_julgamento": "2014-05-01"},
            {"doc_id": "new", "_final_score": 0.9, "data_julgamento": "2024-05-01"},
        ]
    )

    assert merged[0]["doc_id"] == "new"


@pytest.mark.anyio
async def test_run_with_retry_retries_transient_failures_before_success():
    attempts: list[int] = []

    async def flaky_operation() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("temporary failure")
        return "ok"

    result = await run_with_retry(
        flaky_operation,
        attempts=3,
        base_delay=0.0,
        jitter=0.0,
    )

    assert result == "ok"
    assert len(attempts) == 3


@pytest.mark.anyio
async def test_ratio_search_returns_empty_payload_for_blank_query():
    called = {"value": False}

    def fake_run_query(**kwargs):  # noqa: ANN003
        called["value"] = True
        return ("answer", [], {})

    result = await ratio_search("", run_query_fn=fake_run_query)

    assert result == {"answer": "", "docs": [], "meta": {"skipped_empty_query": True}}
    assert called["value"] is False


@pytest.mark.anyio
async def test_search_tese_bundle_skips_contrary_search_when_query_is_none():
    calls = []

    async def fake_ratio_search(query: str, **kwargs):  # noqa: ANN003
        calls.append((query, kwargs.get("reranker_backend")))
        return {"answer": f"ans:{query}", "docs": [], "meta": {}}

    async def fake_legislacao():
        return []

    result = await search_tese_bundle(
        favoravel_query="cdc",
        contraria_query=None,
        legislacao_operation=fake_legislacao,
        ratio_search_fn=fake_ratio_search,
    )

    assert calls == [("cdc", "local")]
    assert result["jurisprudencia_favoravel"]["answer"] == "ans:cdc"
    assert result["jurisprudencia_contraria"]["docs"] == []


@pytest.mark.anyio
async def test_search_tese_bundle_forces_local_reranker_for_theo_queries():
    calls = []

    async def fake_ratio_search(query: str, **kwargs):  # noqa: ANN003
        calls.append((query, kwargs.get("reranker_backend")))
        return {"answer": f"ans:{query}", "docs": [], "meta": {}}

    async def fake_legislacao():
        return []

    await search_tese_bundle(
        favoravel_query="cdc",
        contraria_query="dano moral",
        legislacao_operation=fake_legislacao,
        ratio_search_fn=fake_ratio_search,
    )

    assert calls == [("cdc", "local"), ("dano moral", "local")]
