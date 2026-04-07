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
        def generate_content(self, *, model, contents, config=None):
            captured["model"] = model
            captured["contents"] = contents
            captured["config"] = config
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
    assert getattr(getattr(captured["config"], "http_options", None), "timeout", None) == 45000


def test_parse_critique_payload_strips_fences_and_trailing():
    payload = """```json
    {
      "falhas_processuais": [],
      "argumentos_materiais_fracos": [],
      "jurisprudencia_faltante": [],
      "score_de_risco": 45,
      "analise_contestacao": "ok",
      "recomendacao": "revisar"
    }
    ```
    Nota: recomendo revisar os argumentos.
    """

    critique = parse_critique_payload(payload)

    assert critique["score_de_risco"] == 45
    assert critique["recomendacao"] == "revisar"


def test_parse_critique_payload_coerces_score_from_string():
    payload = (
        '{"falhas_processuais":[],"argumentos_materiais_fracos":[],'
        '"jurisprudencia_faltante":[],"score_de_risco":"75/100",'
        '"analise_contestacao":"risco medio","recomendacao":"revisar"}'
    )

    critique = parse_critique_payload(payload)

    assert critique["score_de_risco"] == 75


def test_parse_critique_payload_clamps_score_to_0_100():
    payload = (
        '{"falhas_processuais":[],"argumentos_materiais_fracos":[],'
        '"jurisprudencia_faltante":[],"score_de_risco":150,'
        '"analise_contestacao":"x","recomendacao":"revisar"}'
    )

    critique = parse_critique_payload(payload)

    assert critique["score_de_risco"] == 100


def test_parse_critique_payload_normalizes_recomendacao_casing():
    payload = (
        '{"falhas_processuais":[],"argumentos_materiais_fracos":[],'
        '"jurisprudencia_faltante":[],"score_de_risco":10,'
        '"analise_contestacao":"x","recomendacao":"APROVAR"}'
    )

    critique = parse_critique_payload(payload)

    assert critique["recomendacao"] == "aprovar"


def test_parse_critique_payload_maps_recomendacao_aliases():
    payload = (
        '{"falhas_processuais":[],"argumentos_materiais_fracos":[],'
        '"jurisprudencia_faltante":[],"score_de_risco":80,'
        '"analise_contestacao":"x","recomendacao":"reescrever"}'
    )

    critique = parse_critique_payload(payload)

    assert critique["recomendacao"] == "reestruturar"


def test_parse_critique_payload_wraps_string_falhas_in_dict():
    """If Gemini returns a falha as a plain string, wrap it preserving info."""
    payload = (
        '{"falhas_processuais":["Falta juntada de procuracao"],'
        '"argumentos_materiais_fracos":[],'
        '"jurisprudencia_faltante":[],"score_de_risco":20,'
        '"analise_contestacao":"x","recomendacao":"revisar"}'
    )

    critique = parse_critique_payload(payload)

    assert len(critique["falhas_processuais"]) == 1
    assert critique["falhas_processuais"][0]["descricao"] == "Falta juntada de procuracao"


def test_parse_critique_payload_preserves_rich_falha_dict():
    """A dict with extra keys beyond the schema must not lose descricao."""
    payload = (
        '{"falhas_processuais":[{"secao_afetada":"dos_fatos","descricao":"lacuna probatoria",'
        '"argumento_contrario":"contestar","extra_key":"valor_extra"}],'
        '"argumentos_materiais_fracos":[],'
        '"jurisprudencia_faltante":[],"score_de_risco":30,'
        '"analise_contestacao":"x","recomendacao":"revisar"}'
    )

    critique = parse_critique_payload(payload)

    falha = critique["falhas_processuais"][0]
    assert falha["descricao"] == "lacuna probatoria"
    assert falha["secao_afetada"] == "dos_fatos"


def test_parse_critique_payload_coerces_jurisprudencia_faltante_dicts():
    """jurisprudencia_faltante should be list[str], even if Gemini sends dicts."""
    payload = (
        '{"falhas_processuais":[],"argumentos_materiais_fracos":[],'
        '"jurisprudencia_faltante":[{"descricao":"STJ Sumula 479"}],'
        '"score_de_risco":10,"analise_contestacao":"x","recomendacao":"aprovar"}'
    )

    critique = parse_critique_payload(payload)

    assert critique["jurisprudencia_faltante"] == ["STJ Sumula 479"]


def test_parse_critique_payload_defaults_missing_analise():
    payload = (
        '{"falhas_processuais":[],"argumentos_materiais_fracos":[],'
        '"jurisprudencia_faltante":[],"score_de_risco":0,"recomendacao":"aprovar"}'
    )

    critique = parse_critique_payload(payload)

    assert isinstance(critique["analise_contestacao"], str)
    assert len(critique["analise_contestacao"]) > 0
