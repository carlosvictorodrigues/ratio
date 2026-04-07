# Ratio Escritorio Adversarial Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the backend adversarial cycle of Ratio Escritorio with critique validation, anti-sycophancy checks, human dismiss flow, section-level revision inputs, and resumable state transitions for multiple rounds.

**Architecture:** Keep the loop inside `backend/escritorio/` as deterministic orchestration around the future Contraparte/Redator LLM calls. Extend the domain models to represent rounds, dismissed findings, and human edits, add a service that validates and normalizes critiques before they enter state, and expose API endpoints that let the UI bootstrap a draft, register a critique, dismiss findings, and submit section revisions without coupling this behavior to `backend/main.py`.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, SQLite, pytest, existing `backend/escritorio`

---

### Task 1: Extend Adversarial Domain Models

**Files:**
- Modify: `backend/escritorio/models.py`
- Test: `tests/escritorio/test_adversarial_models.py`

**Step 1: Write the failing test**

```python
from backend.escritorio.models import RatioEscritorioState


def test_state_tracks_round_counter_and_dismissed_findings():
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")
    assert state.rodada_atual == 0
    assert state.usuario_finaliza is False
    assert state.rodadas == []
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest -q tests/escritorio/test_adversarial_models.py::test_state_tracks_round_counter_and_dismissed_findings`
Expected: FAIL because fields do not exist

**Step 3: Write minimal implementation**

```python
class DismissedFinding(BaseModel):
    finding_id: str
    reason: str = ""


class RodadaAdversarial(BaseModel):
    ...
    dismissed_findings: list[DismissedFinding] = Field(default_factory=list)


class RatioEscritorioState(BaseModel):
    ...
    rodada_atual: int = 0
    usuario_finaliza: bool = False
```

Also add `finding_id` and `origem` to `FalhaCritica`.

**Step 4: Run test to verify it passes**

Run: `py -m pytest -q tests/escritorio/test_adversarial_models.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/escritorio/models.py tests/escritorio/test_adversarial_models.py
git commit -m "feat: extend escritorio models for adversarial loop"
```

### Task 2: Adversarial Service With Anti-Sycophancy And Round Creation

**Files:**
- Create: `backend/escritorio/adversarial.py`
- Test: `tests/escritorio/test_adversarial_service.py`

**Step 1: Write the failing test**

```python
import pytest

from backend.escritorio.adversarial import register_critique_round
from backend.escritorio.models import RatioEscritorioState


def test_register_critique_round_rejects_empty_sycophantic_result():
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")

    with pytest.raises(ValueError):
        register_critique_round(
            state,
            critique_payload={
                "falhas_processuais": [],
                "argumentos_materiais_fracos": [],
                "jurisprudencia_faltante": [],
                "score_de_risco": 0,
                "analise_contestacao": "nenhum problema",
                "recomendacao": "aprovar",
            },
        )
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest -q tests/escritorio/test_adversarial_service.py::test_register_critique_round_rejects_empty_sycophantic_result`
Expected: FAIL because service does not exist

**Step 3: Write minimal implementation**

```python
def register_critique_round(state: RatioEscritorioState, *, critique_payload: dict[str, Any]) -> RatioEscritorioState:
    critique = CriticaContraparte.model_validate(critique_payload)
    if critique.score_de_risco == 0 and not critique.falhas_processuais and not critique.argumentos_materiais_fracos and not critique.jurisprudencia_faltante:
        raise ValueError("Critica vazia rejeitada por anti-sycophancy.")
    ...
```

Expand to:
- assign stable `finding_id`s
- append `RodadaAdversarial`
- update `critica_atual`, `rodada_atual`, `status="adversarial"`

**Step 4: Run test to verify it passes**

Run: `py -m pytest -q tests/escritorio/test_adversarial_service.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/escritorio/adversarial.py tests/escritorio/test_adversarial_service.py
git commit -m "feat: add adversarial service and anti-sycophancy checks"
```

### Task 3: Human Dismiss And Revision Payload

**Files:**
- Modify: `backend/escritorio/state.py`
- Modify: `backend/escritorio/adversarial.py`
- Test: `tests/escritorio/test_adversarial_revision.py`

**Step 1: Write the failing test**

```python
from backend.escritorio.adversarial import dismiss_findings, register_critique_round, submit_human_revision
from backend.escritorio.models import RatioEscritorioState


def test_revision_payload_excludes_dismissed_findings_and_keeps_human_edits():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        peca_sections={"fatos": "texto humano"},
    )
    state = register_critique_round(
        state,
        critique_payload={
            "falhas_processuais": [
                {
                    "secao_afetada": "fatos",
                    "descricao": "falta data",
                    "argumento_contrario": "ataque",
                    "query_jurisprudencia_contraria": "falta data peticao",
                }
            ],
            "argumentos_materiais_fracos": [],
            "jurisprudencia_faltante": [],
            "score_de_risco": 40,
            "analise_contestacao": "ha problema",
            "recomendacao": "revisar",
        },
    )
    finding_id = state.critica_atual.falhas_processuais[0].finding_id
    state = dismiss_findings(state, finding_ids=[finding_id], reason="juiz local nao exige isso")

    payload = submit_human_revision(
        state,
        section_updates={"fatos": "texto humano revisado"},
        notes="preservar meu estilo",
    )

    assert payload["current_sections"]["fatos"] == "texto humano revisado"
    assert payload["current_critique"]["falhas_processuais"] == []
    assert payload["preserve_human_anchors"] is True
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest -q tests/escritorio/test_adversarial_revision.py::test_revision_payload_excludes_dismissed_findings_and_keeps_human_edits`
Expected: FAIL because dismiss/revision helpers do not exist

**Step 3: Write minimal implementation**

```python
def dismiss_findings(...): ...
def submit_human_revision(...): ...
```

Make `submit_human_revision()`:
- merge section updates into `peca_sections`
- persist edits in the current round
- filter dismissed findings from the critique
- return `build_redator_revision_payload(...)` plus `preserve_human_anchors=True`

**Step 4: Run test to verify it passes**

Run: `py -m pytest -q tests/escritorio/test_adversarial_revision.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/escritorio/state.py backend/escritorio/adversarial.py tests/escritorio/test_adversarial_revision.py
git commit -m "feat: add dismissal flow and revision payload helpers"
```

### Task 4: Draft And Adversarial API Endpoints

**Files:**
- Modify: `backend/escritorio/api.py`
- Modify: `backend/escritorio/store.py`
- Test: `tests/escritorio/test_adversarial_api.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app


def test_adversarial_api_can_register_critique_and_dismiss_finding(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RATIO_ESCRITORIO_DB_PATH", str(tmp_path / "escritorio_cases.db"))
    client = TestClient(app)
    client.post("/api/escritorio/cases", json={"caso_id": "caso-1", "tipo_peca": "peticao_inicial"})
    client.post("/api/escritorio/cases/caso-1/draft", json={"sections": {"fatos": "rascunho"}})

    critique = client.post(
        "/api/escritorio/cases/caso-1/adversarial/critique",
        json={
            "falhas_processuais": [
                {
                    "secao_afetada": "fatos",
                    "descricao": "falta data",
                    "argumento_contrario": "ataque",
                    "query_jurisprudencia_contraria": "falta data peticao",
                }
            ],
            "argumentos_materiais_fracos": [],
            "jurisprudencia_faltante": [],
            "score_de_risco": 40,
            "analise_contestacao": "ha problema",
            "recomendacao": "revisar",
        },
    )
    assert critique.status_code == 200
    finding_id = critique.json()["state"]["critica_atual"]["falhas_processuais"][0]["finding_id"]

    dismissed = client.post(
        "/api/escritorio/cases/caso-1/adversarial/dismiss",
        json={"finding_ids": [finding_id], "reason": "descartado pelo advogado"},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["state"]["rodadas"][-1]["dismissed_findings"][0]["finding_id"] == finding_id
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest -q tests/escritorio/test_adversarial_api.py::test_adversarial_api_can_register_critique_and_dismiss_finding`
Expected: FAIL with missing endpoints

**Step 3: Write minimal implementation**

```python
@router.post("/cases/{caso_id}/draft")
def upsert_draft(...): ...

@router.post("/cases/{caso_id}/adversarial/critique")
def register_adversarial_critique(...): ...

@router.post("/cases/{caso_id}/adversarial/dismiss")
def dismiss_adversarial_findings(...): ...

@router.post("/cases/{caso_id}/adversarial/revise")
def submit_adversarial_revision(...): ...
```

Snapshots and events must be saved after each transition.

**Step 4: Run test to verify it passes**

Run: `py -m pytest -q tests/escritorio/test_adversarial_api.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/escritorio/api.py backend/escritorio/store.py tests/escritorio/test_adversarial_api.py
git commit -m "feat: expose adversarial loop api endpoints"
```

### Task 5: End-To-End Adversarial Loop Verification

**Files:**
- Test: `tests/escritorio/test_adversarial_cycle.py`
- Test: `tests/test_api_contract.py`

**Step 1: Write the failing integration test**

```python
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app


def test_adversarial_cycle_can_revise_sections_after_human_dismiss(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RATIO_ESCRITORIO_DB_PATH", str(tmp_path / "escritorio_cases.db"))
    client = TestClient(app)
    client.post("/api/escritorio/cases", json={"caso_id": "caso-1", "tipo_peca": "peticao_inicial"})
    client.post("/api/escritorio/cases/caso-1/draft", json={"sections": {"fatos": "texto inicial"}})

    critique = client.post("/api/escritorio/cases/caso-1/adversarial/critique", json={...})
    finding_id = critique.json()["state"]["critica_atual"]["falhas_processuais"][0]["finding_id"]
    client.post("/api/escritorio/cases/caso-1/adversarial/dismiss", json={"finding_ids": [finding_id], "reason": "nao usar"})

    revise = client.post(
        "/api/escritorio/cases/caso-1/adversarial/revise",
        json={"section_updates": {"fatos": "texto revisado"}, "notes": "preservar meu estilo", "finalize": False},
    )

    assert revise.status_code == 200
    assert revise.json()["revision_payload"]["preserve_human_anchors"] is True
    assert revise.json()["state"]["peca_sections"]["fatos"] == "texto revisado"
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest -q tests/escritorio/test_adversarial_cycle.py::test_adversarial_cycle_can_revise_sections_after_human_dismiss`
Expected: FAIL on missing behavior

**Step 3: Write minimal implementation**

```python
# Ensure:
# - draft bootstrap exists
# - critique enters state as current round
# - dismissal survives snapshot reload
# - revise endpoint returns filtered payload for the future Redator call
# - finalize flag sets usuario_finaliza/status accordingly
```

**Step 4: Run tests to verify they pass**

Run: `py -m pytest -q tests/escritorio tests/test_api_contract.py`
Expected: PASS

Run: `py -m pytest`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/escritorio tests/test_api_contract.py backend/escritorio
git commit -m "test: verify adversarial loop end to end"
```
