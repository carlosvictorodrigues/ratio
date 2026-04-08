from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_escritorio_frontend_no_longer_contains_mock_runtime_data():
    html = _read("frontend/Escritorio/escritorio.html")

    assert "const MOCK_SECTIONS" not in html
    assert "const MOCK_TESES" not in html
    assert "const MOCK_CRITICAS" not in html
    assert "const FEED_SCRIPT" not in html
    assert "const AGENT_OUTPUTS" not in html


def test_escritorio_frontend_resolves_lucide_icon_names_from_kebab_case():
    html = _read("frontend/Escritorio/escritorio.html")

    assert "resolveLucideIconNode" in html
    assert "split('-')" in html
    assert "lucide.icons[normalized]" in html


def test_escritorio_frontend_uses_named_confirmations_instead_of_gate_labels():
    html = _read("frontend/Escritorio/escritorio.html")

    assert 'gateLabel="Confirma' in html
    assert 'gateDesc="Base de pesquisa suficiente para redigir?' in html
    assert "Gate {gate}" not in html


def test_escritorio_frontend_renders_theo_textual_output_per_tese():
    html = _read("frontend/Escritorio/escritorio.html")

    assert "resposta_pesquisa" in html
    assert "Theo ainda nao concluiu esta tese." in html
    assert "LEGISLACAO COMPLEMENTAR" in html
    assert "legislationComplementary" in html


def test_escritorio_frontend_uses_single_draft_modal_for_helena_sections():
    html = _read("frontend/Escritorio/escritorio.html")

    assert "draftModalOpen" in html
    assert "draftSections" in html
    assert "Salvar alteracoes" in html
    assert "Object.entries(draftSections || {})" in html
    assert "editSec" not in html
    assert "editContent" not in html


def test_escritorio_frontend_renders_clara_conversational_gate1_panel():
    html = _read("frontend/Escritorio/escritorio.html")

    assert "resposta_conversacional_clara" in html
    assert "perguntas_pendentes" in html
    assert "Prosseguir assim mesmo" in html
    assert "TRIAGEM DA CLARA" in html
    assert "O QUE A CLARA AINDA PRECISA CONFIRMAR" in html
    assert "Responder perguntas da Clara" not in html
    assert "Responda às perguntas da Clara ou acrescente novos fatos" in html


def test_escritorio_frontend_prefers_active_case_on_restore_instead_of_delivery_case():
    html = _read("frontend/Escritorio/escritorio.html")

    assert "isTerminalCaseStatus" in html
    assert "findInitialCaseId" in html
    assert "const activeSaved = saved && !isTerminalCaseStatus" in html
    assert "const firstActive = cases.find" in html


def test_escritorio_frontend_uses_single_helena_card_and_expandable_marco_findings():
    html = _read("frontend/Escritorio/escritorio.html")

    assert "key: 'draft-summary'" in html
    assert "draft: {" in html
    assert "collapsedFindingKeys" in html
    assert "Mostrar detalhe" in html
    assert "Ocultar detalhe" in html
    assert "DESCRICAO COMPLETA" in html
    assert "c.finding.descricao" in html
    assert "c.finding.secao_afetada &&" in html
    assert "c.finding.argumento_contrario &&" in html


def test_escritorio_frontend_shows_delivery_download_button_inside_workspace_column():
    html = _read("frontend/Escritorio/escritorio.html")

    assert "handleDownloadDocx" in html
    assert "Baixar .docx" in html
    assert "i === 4 && state?.output_docx_path" in html


def test_escritorio_frontend_hides_marco_finalize_controls_after_verification_stage():
    html = _read("frontend/Escritorio/escritorio.html")

    assert "state?.status === 'adversarial' || state?.status === 'revisao_humana'" in html


def test_escritorio_frontend_renders_auditor_cards_with_real_verification_details():
    html = _read("frontend/Escritorio/escritorio.html")

    assert "title: v.referencia || v.section || v.item || v.check || 'Verifica" in html
    assert "sub: v.level || v.result || v.status || 'ok'" in html
    assert "c.verification && isExpanded" in html
    assert "DETALHE DA VERIFICACAO" in html


def test_escritorio_frontend_exposes_history_and_restore_controls():
    html = _read("frontend/Escritorio/escritorio.html")

    assert "getHistory: (id) => api._f(`/cases/${id}/history`)" in html
    assert "getSnapshots: (id) => api._f(`/cases/${id}/snapshots`)" in html
    assert "restoreSnapshot: (id, snapshotId) => api._f(`/cases/${id}/restore`" in html
    assert "do fluxo" in html
    assert "Voltar para esta etapa" in html


def test_escritorio_frontend_renders_snapshot_responses_inside_history_modal():
    html = _read("frontend/Escritorio/escritorio.html")

    assert "historyOpen" in html
    assert "historyItems" in html
    assert "snapshotMap" in html
    assert "snapshot.state?.teses" in html
    assert "snapshot.state?.peca_sections" in html
    assert "snapshot.state?.critica_atual" in html
