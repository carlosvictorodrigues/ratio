from pathlib import Path

from backend.escritorio.store import EscritorioStore


def test_store_creates_case_and_lists_latest_summary(tmp_path: Path):
    store = EscritorioStore(tmp_path / "casos.db")

    store.create_case(caso_id="caso-1", tipo_peca="peticao_inicial", area_direito="Civil")
    cases = store.list_cases()

    assert len(cases) == 1
    assert cases[0]["caso_id"] == "caso-1"
    assert cases[0]["status"] == "intake"
