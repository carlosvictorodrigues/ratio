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
async def test_decompose_case_with_gemini_defaults_to_gemini_3_flash(monkeypatch):
    captured = {}

    class _FakeModels:
        def generate_content(self, *, model, contents):
            captured["model"] = model
            captured["contents"] = contents
            return type("Resp", (), {"text": '[{"id":"t1","descricao":"CDC","tipo":"principal"}]'})()

    class _FakeClient:
        models = _FakeModels()

    monkeypatch.delenv("RATIO_ESCRITORIO_PESQUISADOR_MODEL", raising=False)
    state = RatioEscritorioState(caso_id="caso-1", tipo_peca="peticao_inicial", fatos_brutos="Cobranca indevida.")

    teses = await decompose_case_with_gemini(state, client=_FakeClient())

    assert captured["model"] == "gemini-3-flash"
    assert teses[0].descricao == "CDC"
