from pathlib import Path

from backend.escritorio.models import RatioEscritorioState
from backend.escritorio.store import EscritorioStore


def test_store_persists_and_loads_case_snapshot(tmp_path: Path):
    store = EscritorioStore(tmp_path / "casos.db")
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")

    store.save_snapshot(state, stage="pesquisa")
    loaded = store.load_latest_snapshot("caso-1")

    assert loaded is not None
    assert loaded["stage"] == "pesquisa"
    assert loaded["state"]["caso_id"] == "caso-1"
