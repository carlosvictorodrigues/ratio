import pytest

from backend.escritorio.models import RatioEscritorioState
from backend.escritorio.planning import (
    build_case_decomposition_prompt,
    decompose_case_with_gemini,
    parse_teses_payload,
)


def test_build_case_decomposition_prompt_mentions_3_to_5_objective_theses():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        fatos_brutos="Cliente relata cobrancas indevidas e negativacao.",
    )

    prompt = build_case_decomposition_prompt(state)

    assert "3 a 5 teses juridicas objetivas" in prompt
    assert "Cliente relata cobrancas indevidas e negativacao." in prompt


def test_build_case_decomposition_prompt_includes_new_intake_information():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        fatos_brutos="Relato inicial.\nO reu e o Banco X e houve pedido de justica gratuita.",
    )

    prompt = build_case_decomposition_prompt(state)

    assert "Banco X" in prompt
    assert "justica gratuita" in prompt


def test_parse_teses_payload_validates_json_list():
    payload = """
    [
      {"id": "t1", "descricao": "Cobranca indevida", "tipo": "principal"},
      {"id": "t2", "descricao": "Dano moral por negativacao", "tipo": "subsidiaria"}
    ]
    """

    teses = parse_teses_payload(payload)

    assert [t.id for t in teses] == ["t1", "t2"]
    assert [t.tipo for t in teses] == ["principal", "subsidiaria"]


@pytest.mark.anyio
async def test_decompose_case_with_gemini_defaults_to_gemini_3_flash_preview(monkeypatch):
    captured = {}

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            captured["model"] = model
            captured["contents"] = contents
            captured["config"] = config
            return type("Resp", (), {"text": '[{"id":"t1","descricao":"CDC","tipo":"principal"}]'})()

    class _FakeClient:
        models = _FakeModels()

    monkeypatch.delenv("RATIO_ESCRITORIO_PESQUISADOR_MODEL", raising=False)
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial", fatos_brutos="Cobranca indevida.")

    teses = await decompose_case_with_gemini(state, client=_FakeClient())

    assert captured["model"] == "gemini-3-flash-preview"
    assert teses[0].descricao == "CDC"
    assert getattr(getattr(captured["config"], "http_options", None), "timeout", None) == 120000


def test_parse_teses_payload_unwraps_envelope_object():
    """Gemini sometimes returns ``{"teses": [...]}`` instead of a bare list."""
    payload = """
    {"teses": [
      {"id": "t1", "descricao": "Cobranca indevida", "tipo": "principal"},
      {"id": "t2", "descricao": "Dano moral", "tipo": "subsidiaria"}
    ]}
    """

    teses = parse_teses_payload(payload)

    assert [t.id for t in teses] == ["t1", "t2"]
    assert [t.descricao for t in teses] == ["Cobranca indevida", "Dano moral"]


def test_parse_teses_payload_strips_markdown_fences_and_trailing_text():
    payload = """```json
    [
      {"id": "t1", "descricao": "Lesao grave"}
    ]
    ```
    Observacao: estas teses devem ser revisadas pelo escritorio.
    """

    teses = parse_teses_payload(payload)

    assert teses[0].id == "t1"
    assert teses[0].tipo == "principal"  # default when missing


def test_parse_teses_payload_synthesizes_id_when_missing():
    payload = '[{"descricao": "Tese A"}, {"descricao": "Tese B"}]'

    teses = parse_teses_payload(payload)

    assert [t.id for t in teses] == ["t1", "t2"]
    assert [t.descricao for t in teses] == ["Tese A", "Tese B"]


def test_parse_teses_payload_normalizes_tipo_aliases():
    payload = '[{"id":"t1","descricao":"X","tipo":"PRIMARIA"},{"id":"t2","descricao":"Y","tipo":"alternativa"}]'

    teses = parse_teses_payload(payload)

    assert teses[0].tipo == "principal"
    assert teses[1].tipo == "subsidiaria"


def test_parse_teses_payload_accepts_string_items_without_dropping():
    payload = '["Cobranca indevida", "Negativacao indevida"]'

    teses = parse_teses_payload(payload)

    assert [t.descricao for t in teses] == ["Cobranca indevida", "Negativacao indevida"]
    assert [t.id for t in teses] == ["t1", "t2"]


def test_parse_teses_payload_folds_dict_when_descricao_missing():
    """A dict with rich keys but no ``descricao`` must NOT be discarded."""
    payload = (
        '[{"id":"t1","tese":"Cobranca indevida","fundamento":"art. 42 CDC"}]'
    )

    teses = parse_teses_payload(payload)

    assert teses[0].id == "t1"
    assert "Cobranca indevida" in teses[0].descricao
    # Information about the fundament should be preserved in the description.
    assert "art. 42 CDC" in teses[0].descricao
