import pytest

from backend.escritorio.intake_llm import (
    build_intake_prompt,
    generate_intake_with_gemini,
    parse_intake_payload,
)
from backend.escritorio.models import RatioEscritorioState


def test_build_intake_prompt_mentions_structured_dossie_fields():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        fatos_brutos="Cliente relata cobrança indevida.",
    )

    prompt = build_intake_prompt(state)

    assert "fatos_estruturados" in prompt
    assert "provas_disponiveis" in prompt
    assert "Cliente relata cobrança indevida." in prompt


def test_parse_intake_payload_returns_expected_fields():
    payload = """
    {
      "fatos_estruturados": ["fato 1"],
      "provas_disponiveis": ["contrato"],
      "pontos_atencao": ["prazo prescricional"]
    }
    """

    parsed = parse_intake_payload(payload)

    assert parsed["fatos_estruturados"] == ["fato 1"]
    assert parsed["provas_disponiveis"] == ["contrato"]


@pytest.mark.anyio
async def test_generate_intake_with_gemini_defaults_to_gemini_3_flash_preview():
    captured = {}

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            captured["model"] = model
            captured["contents"] = contents
            captured["config"] = config
            return type(
                "Resp",
                (),
                {
                    "text": '{"fatos_estruturados":["fato llm"],"provas_disponiveis":["contrato"],"pontos_atencao":["prazo"]}'
                },
            )()

    class _FakeClient:
        models = _FakeModels()

    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        fatos_brutos="Cliente relata cobrança indevida.",
    )

    parsed = await generate_intake_with_gemini(state, client=_FakeClient())

    assert captured["model"] == "gemini-3-flash-preview"
    assert parsed["fatos_estruturados"] == ["fato llm"]
    # response_mime_type=application/json must be requested to force structured output
    assert captured["config"] is not None
    assert getattr(captured["config"], "response_mime_type", None) == "application/json"
    assert getattr(getattr(captured["config"], "http_options", None), "timeout", None) == 45000


def test_parse_intake_payload_strips_markdown_fences():
    payload = """```json
    {"fatos_estruturados": ["fato 1"], "provas_disponiveis": [], "pontos_atencao": []}
    ```"""

    parsed = parse_intake_payload(payload)

    assert parsed["fatos_estruturados"] == ["fato 1"]
