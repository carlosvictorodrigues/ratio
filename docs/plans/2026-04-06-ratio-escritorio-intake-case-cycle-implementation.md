# Ratio Escritorio Intake And Case Cycle Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the backend-first intake cycle of Ratio Escritorio with case metadata, intake history, gate decisions, resumable case state, and FastAPI endpoints for creating, progressing, and reviewing a case before research starts.

**Architecture:** Extend the new `backend/escritorio/` bounded context instead of adding logic to the monolithic backend. Keep the intake orchestration modular: domain models hold state, the store persists case and event history, an intake service computes progress and next questions, and the API exposes resumable contracts for case creation, intake turns, and gate decisions.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, SQLite, pytest, existing `backend/escritorio`

---

### Task 1: Extend Domain Models For Intake And Gates

**Files:**
- Modify: `backend/escritorio/models.py`
- Test: `tests/escritorio/test_intake_models.py`

**Step 1: Write the failing test**

```python
from backend.escritorio.models import RatioEscritorioState


def test_state_tracks_intake_history_and_gate_flags():
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")
    assert state.intake_history == []
    assert state.gate1_aprovado is False
    assert state.gate2_aprovado is False
    assert state.status == "intake"
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest -q tests/escritorio/test_intake_models.py::test_state_tracks_intake_history_and_gate_flags`
Expected: FAIL because intake fields do not exist

**Step 3: Write minimal implementation**

```python
class IntakeMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class IntakeChecklist(BaseModel):
    partes_identificadas: bool = False
    fatos_principais_cobertos: bool = False
    documentos_listados: bool = False


class RatioEscritorioState(BaseModel):
    ...
    intake_history: list[IntakeMessage] = Field(default_factory=list)
    intake_checklist: IntakeChecklist = Field(default_factory=IntakeChecklist)
    gate1_aprovado: bool = False
    gate2_aprovado: bool = False
    status: Literal["intake", "gate1", "pesquisa", "gate2", "redacao", "finalizado"] = "intake"
```

**Step 4: Run test to verify it passes**

Run: `py -m pytest -q tests/escritorio/test_intake_models.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/escritorio/models.py tests/escritorio/test_intake_models.py
git commit -m "feat: extend escritorio state for intake and gates"
```

### Task 2: Persist Case Metadata And Event History

**Files:**
- Modify: `backend/escritorio/store.py`
- Test: `tests/escritorio/test_case_store.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

from backend.escritorio.store import EscritorioStore


def test_store_creates_case_and_lists_latest_summary(tmp_path: Path):
    store = EscritorioStore(tmp_path / "casos.db")
    store.create_case(caso_id="caso-1", tipo_peca="peticao_inicial", area_direito="Civil")

    cases = store.list_cases()

    assert len(cases) == 1
    assert cases[0]["caso_id"] == "caso-1"
    assert cases[0]["status"] == "intake"
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest -q tests/escritorio/test_case_store.py::test_store_creates_case_and_lists_latest_summary`
Expected: FAIL because `create_case` and `list_cases` do not exist

**Step 3: Write minimal implementation**

```python
class EscritorioStore:
    def _initialize(self) -> None:
        ...
        conn.execute(
            "CREATE TABLE IF NOT EXISTS cases (caso_id TEXT PRIMARY KEY, tipo_peca TEXT, area_direito TEXT, status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS case_events (id INTEGER PRIMARY KEY AUTOINCREMENT, caso_id TEXT NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )

    def create_case(self, *, caso_id: str, tipo_peca: str, area_direito: str = "") -> None:
        ...

    def list_cases(self) -> list[dict[str, Any]]:
        ...

    def append_event(self, caso_id: str, event_type: str, payload: dict[str, Any]) -> None:
        ...
```

**Step 4: Run test to verify it passes**

Run: `py -m pytest -q tests/escritorio/test_case_store.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/escritorio/store.py tests/escritorio/test_case_store.py
git commit -m "feat: persist escritorio case metadata and events"
```

### Task 3: Intake Service And Checklist Progress

**Files:**
- Create: `backend/escritorio/intake.py`
- Test: `tests/escritorio/test_intake_service.py`

**Step 1: Write the failing test**

```python
from backend.escritorio.intake import process_intake_message
from backend.escritorio.models import RatioEscritorioState


def test_process_intake_message_updates_history_and_promotes_gate_when_checklist_complete():
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial")

    updated = process_intake_message(
        state,
        user_message="Cliente Joao relata cobranca indevida. Tenho contrato e boletos.",
    )

    assert updated.intake_history[-1].role == "user"
    assert updated.intake_checklist.documentos_listados is True
    assert updated.status in {"intake", "gate1"}
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest -q tests/escritorio/test_intake_service.py::test_process_intake_message_updates_history_and_promotes_gate_when_checklist_complete`
Expected: FAIL because intake service does not exist

**Step 3: Write minimal implementation**

```python
def process_intake_message(state: RatioEscritorioState, *, user_message: str) -> RatioEscritorioState:
    updated = state.model_copy(deep=True)
    updated.intake_history.append(IntakeMessage(role="user", content=user_message))
    updated.fatos_brutos = "\n".join(filter(None, [updated.fatos_brutos, user_message])).strip()
    updated.intake_checklist = compute_checklist(updated)
    updated.status = "gate1" if checklist_ready(updated.intake_checklist) else "intake"
    return updated
```

Add:
- `compute_checklist()`
- `checklist_ready()`
- `build_next_question()` based on missing checklist items

**Step 4: Run test to verify it passes**

Run: `py -m pytest -q tests/escritorio/test_intake_service.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/escritorio/intake.py tests/escritorio/test_intake_service.py
git commit -m "feat: add escritorio intake service and checklist"
```

### Task 4: Case API Contracts

**Files:**
- Modify: `backend/escritorio/api.py`
- Modify: `backend/main.py`
- Test: `tests/escritorio/test_case_api.py`

**Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from backend.main import app


def test_case_api_creates_case_and_returns_summary():
    client = TestClient(app)
    response = client.post(
        "/api/escritorio/cases",
        json={"caso_id": "caso-1", "tipo_peca": "peticao_inicial", "area_direito": "Civil"},
    )
    assert response.status_code == 201
    assert response.json()["caso_id"] == "caso-1"
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest -q tests/escritorio/test_case_api.py::test_case_api_creates_case_and_returns_summary`
Expected: FAIL with 404

**Step 3: Write minimal implementation**

```python
@router.post("/cases", status_code=201)
def create_case(payload: CreateCaseRequest) -> dict[str, Any]:
    ...

@router.get("/cases")
def list_cases() -> list[dict[str, Any]]:
    ...

@router.get("/cases/{caso_id}")
def get_case(caso_id: str) -> dict[str, Any]:
    ...

@router.post("/cases/{caso_id}/intake")
def post_intake_turn(caso_id: str, payload: IntakeTurnRequest) -> dict[str, Any]:
    ...

@router.post("/cases/{caso_id}/gates/{gate_name}")
def decide_gate(caso_id: str, gate_name: str, payload: GateDecisionRequest) -> dict[str, Any]:
    ...
```

Use a lazily created `EscritorioStore` rooted under a dedicated local data path, and keep the router import-safe for tests.

**Step 4: Run test to verify it passes**

Run: `py -m pytest -q tests/escritorio/test_case_api.py`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/escritorio/api.py backend/main.py tests/escritorio/test_case_api.py
git commit -m "feat: expose escritorio case cycle api"
```

### Task 5: End-To-End Intake Cycle Verification

**Files:**
- Test: `tests/escritorio/test_case_cycle.py`
- Test: `tests/escritorio/test_api.py`
- Test: `tests/test_api_contract.py`

**Step 1: Write the failing integration test**

```python
from fastapi.testclient import TestClient

from backend.main import app


def test_case_cycle_can_create_case_progress_intake_and_approve_gate():
    client = TestClient(app)
    created = client.post("/api/escritorio/cases", json={"caso_id": "caso-1", "tipo_peca": "peticao_inicial"})
    assert created.status_code == 201

    intake = client.post("/api/escritorio/cases/caso-1/intake", json={"message": "Sou autora e tenho contrato."})
    assert intake.status_code == 200

    gate = client.post("/api/escritorio/cases/caso-1/gates/gate1", json={"approved": True})
    assert gate.status_code == 200
    assert gate.json()["state"]["gate1_aprovado"] is True
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest -q tests/escritorio/test_case_cycle.py::test_case_cycle_can_create_case_progress_intake_and_approve_gate`
Expected: FAIL on missing endpoint or missing persistence behavior

**Step 3: Write minimal implementation**

```python
# Ensure:
# - store updates latest snapshot after case creation and intake turns
# - gate decisions mutate state and append an event
# - GET /cases/{caso_id} returns the latest snapshot and summary
```

**Step 4: Run tests to verify they pass**

Run: `py -m pytest -q tests/escritorio tests/test_api_contract.py`
Expected: PASS

Run: `py -m pytest`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/escritorio tests/test_api_contract.py backend/escritorio backend/main.py
git commit -m "test: verify escritorio intake case cycle end to end"
```
