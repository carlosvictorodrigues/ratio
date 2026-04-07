import pytest

from backend.escritorio.tools.ratio_tools import merge_ranked_results, run_with_retry


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
