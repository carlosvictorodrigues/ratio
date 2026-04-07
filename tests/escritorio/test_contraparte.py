import pytest

from backend.escritorio.contraparte import (
    build_contraparte_prompt,
    generate_critique_with_gemini,
    parse_critique_payload,
)
from backend.escritorio.models import RatioEscritorioState


def test_build_contraparte_prompt_uses_only_piece_sections():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        fatos_brutos="isso nao deve ir ao prompt da contraparte",
        peca_sections={
            "dos_fatos": "Texto dos fatos.",
            "do_direito": "Texto do direito.",
        },
    )

    prompt = build_contraparte_prompt(state)

    assert "Texto dos fatos." in prompt
    assert "Texto do direito." in prompt
    assert "isso nao deve ir ao prompt da contraparte" not in prompt


def test_parse_critique_payload_returns_structured_dict():
    payload = """
    {
      "falhas_processuais": [],
      "argumentos_materiais_fracos": [
        {
          "secao_afetada": "dos_fatos",
          "descricao": "falta robustez",
          "argumento_contrario": "ataque",
          "query_jurisprudencia_contraria": "falta robustez"
        }
      ],
      "jurisprudencia_faltante": [],
      "score_de_risco": 30,
      "analise_contestacao": "ha risco",
      "recomendacao": "revisar"
    }
    """

    critique = parse_critique_payload(payload)

    assert critique["score_de_risco"] == 30
    assert critique["recomendacao"] == "revisar"


@pytest.mark.anyio
async def test_generate_critique_with_gemini_defaults_to_reasoning_model():
    captured = {}

    class _FakeModels:
        def generate_content(self, *, model, contents):
            captured["model"] = model
            captured["contents"] = contents
            return type(
                "Resp",
                (),
                {
                    "text": '{"falhas_processuais":[],"argumentos_materiais_fracos":[],"jurisprudencia_faltante":[],"score_de_risco":15,"analise_contestacao":"ok","recomendacao":"revisar"}'
                },
            )()

    class _FakeClient:
        models = _FakeModels()

    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        peca_sections={"dos_fatos": "Texto dos fatos."},
    )

    critique = await generate_critique_with_gemini(state, client=_FakeClient())

    assert captured["model"] == "gemini-3.1-pro-preview"
    assert critique["score_de_risco"] == 15
