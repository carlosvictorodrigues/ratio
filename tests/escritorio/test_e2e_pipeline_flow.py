"""
E2E pipeline flow test — exercises the full contract:
  create → intake → gate1 pause → approve gate1 → run (research) → gate2 pause
  → approve gate2 → run (redaction) → run (adversarial) → output_docx_path exists

Uses mocked graph functions (no real Gemini calls) but exercises the real
orchestrator, store, API contract shapes, and gate logic.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.escritorio.models import (
    CriticaContraparte,
    FalhaCritica,
    RatioEscritorioState,
    RodadaAdversarial,
    TeseJuridica,
)
from backend.escritorio.store import CaseStore
from backend.escritorio.intake import process_intake_message, build_next_question
from backend.escritorio.graph.orchestrator import run_escritorio_pipeline


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_store(tmp_path: Path, caso_id: str = "e2e_test") -> CaseStore:
    store = CaseStore(tmp_path / caso_id)
    return store


def _create_initial_state(store: CaseStore, caso_id: str = "e2e_test") -> dict:
    return store.create_case(caso_id=caso_id, tipo_peca="peticao_inicial", area_direito="consumidor")


# ── Mock graph functions ─────────────────────────────────────────────────────

async def mock_intake_graph(state: RatioEscritorioState, store) -> RatioEscritorioState:
    """Simulates intake analysis: extracts structured facts from raw text."""
    updated = state.model_copy(deep=True)
    updated.fatos_estruturados = [
        "Contrato celebrado em 15/03/2023",
        "360 parcelas mensais",
        "Pagamento integral ate 10/01/2025",
        "Manutencao indevida em cadastro restritivo",
    ]
    updated.provas_disponiveis = ["contrato", "comprovantes de pagamento", "extrato"]
    updated.pontos_atencao = ["Verificar se ha Sumula 385 aplicavel"]
    updated.status = "gate1"
    updated.workflow_stage = "gate1"
    store.save_snapshot(updated, stage=updated.status)
    return updated


async def mock_drafting_research(state: RatioEscritorioState, store) -> RatioEscritorioState:
    """Simulates research: decomposes theses, finds jurisprudence and legislation."""
    updated = state.model_copy(deep=True)
    updated.teses = [
        TeseJuridica(
            id="t1",
            descricao="Responsabilidade Objetiva do Fornecedor",
            tipo="principal",
            jurisprudencia_favoravel=[{"processo": "REsp 1.234.567/SP", "tribunal": "STJ", "ementa": "Dano moral in re ipsa."}],
            jurisprudencia_contraria=[],
            legislacao=[{"artigo": "Art. 14 CDC", "texto": "Responsabilidade objetiva."}],
            confianca="alta",
        ),
        TeseJuridica(
            id="t2",
            descricao="Prazo de Exclusao — Sumula 548/STJ",
            tipo="subsidiaria",
            jurisprudencia_favoravel=[{"processo": "AgInt AREsp 1.799.837/SP", "tribunal": "STJ"}],
            jurisprudencia_contraria=[],
            legislacao=[{"artigo": "Sumula 548/STJ"}],
            confianca="media",
        ),
    ]
    updated.pesquisa_jurisprudencia = [
        {"processo": "REsp 1.234.567/SP", "tribunal": "STJ"},
        {"processo": "AgInt AREsp 1.799.837/SP", "tribunal": "STJ"},
    ]
    updated.pesquisa_legislacao = [
        {"artigo": "Art. 14 CDC"},
        {"artigo": "Sumula 548/STJ"},
    ]
    updated.status = "gate2"
    updated.workflow_stage = "gate2"
    store.save_snapshot(updated, stage=updated.status)
    return updated


async def mock_drafting_redaction(state: RatioEscritorioState, store) -> RatioEscritorioState:
    """Simulates section drafting."""
    updated = state.model_copy(deep=True)
    updated.peca_sections = {
        "Dos Fatos": "O autor celebrou contrato de financiamento...",
        "Do Direito": "A responsabilidade objetiva esta caracterizada conforme art. 14 CDC...",
        "Dos Pedidos": "Requer-se a condenacao em danos morais...",
    }
    updated.proveniencia = {
        "Do Direito": ["REsp 1.234.567/SP", "Art. 14 CDC"],
    }
    updated.status = "redacao"
    updated.workflow_stage = "redacao"
    store.save_snapshot(updated, stage=updated.status)
    return updated


async def mock_adversarial_graph(state: RatioEscritorioState, store) -> RatioEscritorioState:
    """Simulates adversarial review + verification + document generation."""
    updated = state.model_copy(deep=True)
    updated.critica_atual = CriticaContraparte(
        falhas_processuais=[],
        argumentos_materiais_fracos=[
            FalhaCritica(
                finding_id="f1",
                secao_afetada="Dos Pedidos",
                tipo="material",
                gravidade="media",
                descricao="Quantum acima da media",
                argumento_contrario="Juiz pode reduzir",
            )
        ],
        jurisprudencia_faltante=[],
        score_de_risco=12,
        analise_contestacao="Peca solida com risco baixo.",
        recomendacao="aprovar",
    )
    updated.rodada_atual = 1
    updated.rodadas = [
        RodadaAdversarial(
            numero=1,
            resumo_rodada="Revisao adversarial concluida com score 12/100.",
            critica_contraparte=updated.critica_atual,
        )
    ]
    updated.verificacoes = [
        {"item": "Citacoes jurisprudenciais", "result": "7/7 validas"},
        {"item": "Artigos de lei", "result": "2/2 vigentes"},
        {"item": "Sumulas", "result": "1/1 ativa"},
    ]
    updated.output_docx_path = str(store.output_dir / "peticao_final.docx")
    updated.custo_total_usd = 0.0842
    updated.status = "finalizado"
    updated.workflow_stage = "finalizado"
    store.save_snapshot(updated, stage=updated.status)
    return updated


# ── Orchestrator wrapper that switches drafting fn based on gate2 state ──────

def _build_drafting_fn(research_fn, redaction_fn):
    """Returns a drafting fn that routes to research or redaction based on gate2."""
    async def _drafting(state, store):
        if not state.gate2_aprovado:
            return await research_fn(state, store)
        else:
            return await redaction_fn(state, store)
    return _drafting


# ── E2E TEST ─────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_full_e2e_pipeline_flow(tmp_path):
    """
    Full E2E flow:
      1. Create case
      2. Intake messages → status reaches gate1
      3. Approve gate1 → status becomes pesquisa
      4. Run pipeline → research fills teses, status becomes gate2
      5. Approve gate2 → status becomes redacao
      6. Run pipeline → redaction fills peca_sections
      7. Run pipeline → adversarial fills critica_atual, output_docx_path
      8. Final state is 'finalizado' with document generated
    """
    caso_id = "e2e_test_caso"
    store = _make_store(tmp_path, caso_id)

    # ── Step 1: Create case ──
    created = _create_initial_state(store, caso_id)
    assert created["caso_id"] == caso_id
    assert created["status"] == "intake"
    assert created["tipo_peca"] == "peticao_inicial"

    state = store.load_latest_state()
    assert state is not None
    assert state.status == "intake"
    assert state.gate1_aprovado is False
    assert state.gate2_aprovado is False

    # ── Step 2: Intake messages ──
    # Message 1: parties
    state = process_intake_message(state, user_message="O cliente Joao Silva contratou financiamento com o banco reu Banco X em 2023.")
    store.save_snapshot(state, stage=state.status)
    assert state.intake_checklist.partes_identificadas is True

    # Message 2: facts
    state = process_intake_message(state, user_message="Pagou todas as parcelas ate janeiro 2025, mas o banco manteve o nome dele negativado indevidamente. Contrato de 360 parcelas.")
    store.save_snapshot(state, stage=state.status)
    assert state.intake_checklist.fatos_principais_cobertos is True

    # Message 3: documents
    state = process_intake_message(state, user_message="Tenho o contrato original, comprovantes de pagamento e extrato bancario como documentos.")
    store.save_snapshot(state, stage=state.status)
    assert state.intake_checklist.documentos_listados is True

    # After all 3 messages, checklist is complete → status should be gate1
    assert state.status == "gate1", f"Expected gate1, got {state.status}"

    # next_question should indicate everything is ready
    next_q = build_next_question(state)
    assert "partes" not in next_q.lower() or "detectamos" in next_q.lower()

    # ── Step 3: Approve gate1 ──
    state.gate1_aprovado = True
    state.status = "pesquisa"
    state.workflow_stage = "pesquisa"
    store.save_snapshot(state, stage=state.status)

    assert state.gate1_aprovado is True
    assert state.status == "pesquisa"

    # ── Step 4: Run pipeline → research ──
    state = await run_escritorio_pipeline(
        store=store,
        run_intake_graph_fn=mock_intake_graph,
        run_drafting_graph_fn=_build_drafting_fn(mock_drafting_research, mock_drafting_redaction),
        run_adversarial_graph_fn=mock_adversarial_graph,
    )

    # Research should have produced teses and paused at gate2
    assert state.status == "gate2", f"Expected gate2, got {state.status}"
    assert len(state.teses) == 2
    assert len(state.pesquisa_jurisprudencia) == 2
    assert len(state.pesquisa_legislacao) == 2
    assert state.teses[0].descricao == "Responsabilidade Objetiva do Fornecedor"
    assert state.teses[0].confianca == "alta"
    assert state.gate2_aprovado is False  # Not yet approved

    # ── Step 5: Approve gate2 ──
    state.gate2_aprovado = True
    state.status = "redacao"
    state.workflow_stage = "redacao"
    store.save_snapshot(state, stage=state.status)

    assert state.gate2_aprovado is True
    assert state.status == "redacao"

    # ── Step 6: Run pipeline → redaction ──
    # peca_sections is empty, so orchestrator calls drafting_fn again (now with gate2_aprovado=True → redaction)
    state = await run_escritorio_pipeline(
        store=store,
        run_intake_graph_fn=mock_intake_graph,
        run_drafting_graph_fn=_build_drafting_fn(mock_drafting_research, mock_drafting_redaction),
        run_adversarial_graph_fn=mock_adversarial_graph,
    )

    # After redaction + adversarial, should be finalizado
    assert state.output_docx_path != "", f"Expected output_docx_path, got empty"
    assert state.status == "finalizado", f"Expected finalizado, got {state.status}"

    # ── Step 7: Verify final state ──
    assert len(state.peca_sections) == 3
    assert "Dos Fatos" in state.peca_sections
    assert "Do Direito" in state.peca_sections
    assert "Dos Pedidos" in state.peca_sections

    # Adversarial review completed
    assert state.critica_atual is not None
    assert state.critica_atual.score_de_risco == 12
    assert state.critica_atual.recomendacao == "aprovar"
    assert state.rodada_atual == 1
    assert len(state.rodadas) == 1

    # Verification checks
    assert len(state.verificacoes) == 3
    assert state.custo_total_usd > 0

    # Document path points to output dir
    assert "peticao_final.docx" in state.output_docx_path

    # ── Step 8: Verify events were recorded ──
    events = store.list_events()
    stage_events = [e for e in events if e.get("event_type") == "pipeline.stage_completed"]
    assert len(stage_events) >= 2, f"Expected at least 2 stage events, got {len(stage_events)}"


@pytest.mark.anyio
async def test_gate2_pauses_before_redaction(tmp_path):
    """
    Verify that after research, the pipeline stops at gate2
    and does NOT proceed to redaction until gate2 is approved.
    """
    caso_id = "gate2_pause_test"
    store = _make_store(tmp_path, caso_id)
    _create_initial_state(store, caso_id)

    state = store.load_latest_state()
    # Fast-forward to pesquisa
    state.gate1_aprovado = True
    state.status = "pesquisa"
    state.workflow_stage = "pesquisa"
    store.save_snapshot(state, stage=state.status)

    # Run pipeline — should do research and stop at gate2
    state = await run_escritorio_pipeline(
        store=store,
        run_intake_graph_fn=mock_intake_graph,
        run_drafting_graph_fn=_build_drafting_fn(mock_drafting_research, mock_drafting_redaction),
        run_adversarial_graph_fn=mock_adversarial_graph,
    )

    assert state.status == "gate2"
    assert state.gate2_aprovado is False
    assert len(state.peca_sections) == 0, "Redaction should NOT have run yet"
    assert state.output_docx_path == "", "No document should exist yet"


@pytest.mark.anyio
async def test_intake_checklist_controls_gate1(tmp_path):
    """
    Verify that gate1 status is only reached when all 3 checklist items are met.
    """
    caso_id = "checklist_test"
    store = _make_store(tmp_path, caso_id)
    _create_initial_state(store, caso_id)
    state = store.load_latest_state()

    # Only short facts, no parties or docs
    state = process_intake_message(state, user_message="Houve cobranca indevida de taxas mensais desde janeiro de 2024 ate dezembro de 2024.")
    assert state.status == "intake"  # Not ready yet — no parties, no docs

    # Add parties — but still no documents
    state = process_intake_message(state, user_message="O autor e o cliente lesado. A empresa reu e a operadora de telefonia.")
    assert state.intake_checklist.partes_identificadas is True
    # Without document hints, should still be intake
    assert state.intake_checklist.documentos_listados is False, "No document hints should be detected yet"
    assert state.status == "intake"

    # Add documents
    state = process_intake_message(state, user_message="Possuo o contrato e comprovantes como documentos anexos.")
    assert state.intake_checklist.documentos_listados is True
    assert state.status == "gate1"  # NOW ready


@pytest.mark.anyio
async def test_frontend_field_contract(tmp_path):
    """
    Verify that the state shape returned by the backend matches what
    the frontend expects to read (based on the escritorio.html contract).
    """
    caso_id = "field_contract_test"
    store = _make_store(tmp_path, caso_id)
    _create_initial_state(store, caso_id)

    state = store.load_latest_state()
    dumped = state.model_dump(mode="json")

    # All fields the frontend reads must exist in the state
    frontend_fields = [
        "caso_id", "tipo_peca", "area_direito", "status", "workflow_stage",
        "fatos_estruturados", "provas_disponiveis", "pontos_atencao",
        "teses", "pesquisa_jurisprudencia", "pesquisa_legislacao",
        "peca_sections", "proveniencia",
        "critica_atual", "rodada_atual", "rodadas",
        "verificacoes", "output_docx_path",
        "custo_total_usd",
        "gate1_aprovado", "gate2_aprovado",
        "intake_history", "intake_checklist",
    ]
    for field in frontend_fields:
        assert field in dumped, f"Field '{field}' missing from state — frontend will break"

    # Verify types
    assert isinstance(dumped["fatos_estruturados"], list)
    assert isinstance(dumped["teses"], list)
    assert isinstance(dumped["peca_sections"], dict)
    assert isinstance(dumped["rodadas"], list)
    assert isinstance(dumped["verificacoes"], list)
    assert isinstance(dumped["custo_total_usd"], (int, float))
    assert isinstance(dumped["gate1_aprovado"], bool)
    assert isinstance(dumped["gate2_aprovado"], bool)
    assert isinstance(dumped["output_docx_path"], str)
