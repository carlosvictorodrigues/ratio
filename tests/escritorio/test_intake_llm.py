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
        fatos_brutos="Cliente relata cobranca indevida.",
    )

    prompt = build_intake_prompt(state)

    assert "fatos_estruturados" in prompt
    assert "provas_disponiveis" in prompt
    assert "resposta_conversacional_clara" in prompt
    assert "perguntas_pendentes" in prompt
    assert "triagem_suficiente" in prompt
    assert "Cliente relata cobranca indevida." in prompt


def test_parse_intake_payload_returns_expected_fields():
    payload = """
    {
      "fatos_estruturados": ["fato 1"],
      "provas_disponiveis": ["contrato"],
      "pontos_atencao": ["prazo prescricional"],
      "resposta_conversacional_clara": "Entendi o caso e preciso de dois pontos.",
      "perguntas_pendentes": ["Quem e o reu?", "Ha pedido de tutela?"],
      "triagem_suficiente": false
    }
    """

    parsed = parse_intake_payload(payload)

    assert parsed["fatos_estruturados"] == ["fato 1"]
    assert parsed["provas_disponiveis"] == ["contrato"]
    assert parsed["resposta_conversacional_clara"].startswith("Entendi o caso")
    assert parsed["perguntas_pendentes"] == ["Quem e o reu?", "Ha pedido de tutela?"]
    assert parsed["triagem_suficiente"] is False


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
                    "text": (
                        '{"fatos_estruturados":["fato llm"],'
                        '"provas_disponiveis":["contrato"],'
                        '"pontos_atencao":["prazo"],'
                        '"resposta_conversacional_clara":"Entendi o caso e preciso de mais detalhes.",'
                        '"perguntas_pendentes":["Quem e o reu?"],'
                        '"triagem_suficiente":false}'
                    )
                },
            )()

    class _FakeClient:
        models = _FakeModels()

    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        fatos_brutos="Cliente relata cobranca indevida.",
    )

    parsed = await generate_intake_with_gemini(state, client=_FakeClient())

    assert captured["model"] == "gemini-3-flash-preview"
    assert parsed["fatos_estruturados"] == ["fato llm"]
    assert parsed["perguntas_pendentes"] == ["Quem e o reu?"]
    assert parsed["triagem_suficiente"] is False
    assert captured["config"] is not None
    assert getattr(captured["config"], "response_mime_type", None) == "application/json"
    assert getattr(getattr(captured["config"], "http_options", None), "timeout", None) == 120000


def test_parse_intake_payload_strips_markdown_fences():
    payload = """```json
    {"fatos_estruturados": ["fato 1"], "provas_disponiveis": [], "pontos_atencao": [], "resposta_conversacional_clara": "", "perguntas_pendentes": [], "triagem_suficiente": false}
    ```"""

    parsed = parse_intake_payload(payload)

    assert parsed["fatos_estruturados"] == ["fato 1"]


def test_parse_intake_payload_coerces_pending_questions_and_boolean_fields():
    payload = """
    {
      "fatos_estruturados": ["fato 1"],
      "provas_disponiveis": [],
      "pontos_atencao": [],
      "resposta_conversacional_clara": ["Entendi o nucleo do caso."],
      "perguntas_pendentes": [{"pergunta": "Quem e o reu?"}, "Quais documentos ja estao em maos?"],
      "triagem_suficiente": "true"
    }
    """

    parsed = parse_intake_payload(payload)

    assert parsed["resposta_conversacional_clara"].startswith("Entendi")
    assert parsed["perguntas_pendentes"] == ["Quem e o reu?", "Quais documentos ja estao em maos?"]
    assert parsed["triagem_suficiente"] is True
