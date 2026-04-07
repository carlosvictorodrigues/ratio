import pytest

from backend.escritorio.models import RatioEscritorioState, TeseJuridica
from backend.escritorio.redaction import (
    build_redaction_prompt,
    build_revision_prompt,
    generate_sections_with_gemini,
    generate_revision_with_gemini,
    infer_section_provenance,
    parse_sections_payload,
)
from backend.escritorio.state import build_redator_revision_payload


def test_build_redaction_prompt_mentions_sectioned_output_and_sources():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        fatos_brutos="Cliente relata cobrança indevida.",
        teses=[TeseJuridica(id="t1", descricao="CDC", tipo="principal")],
        pesquisa_jurisprudencia=[{"doc_id": "doc-1", "processo": "REsp 123"}],
        pesquisa_legislacao=[{"doc_id": "lei-1", "diploma": "CDC"}],
    )

    prompt = build_redaction_prompt(state)

    assert "objeto json" in prompt.lower()
    assert "peca_sections" not in prompt.lower()
    assert "Cliente relata cobrança indevida." in prompt
    assert "REsp 123" in prompt


def test_parse_sections_payload_returns_dict_of_sections():
    payload = """
    {
      "dos_fatos": "Texto dos fatos.",
      "do_direito": "Texto do direito."
    }
    """

    sections = parse_sections_payload(payload)

    assert sections["dos_fatos"] == "Texto dos fatos."
    assert sections["do_direito"] == "Texto do direito."


@pytest.mark.anyio
async def test_generate_sections_with_gemini_defaults_to_reasoning_model():
    captured = {}

    class _FakeModels:
        def generate_content(self, *, model, contents):
            captured["model"] = model
            captured["contents"] = contents
            return type(
                "Resp",
                (),
                {"text": '{"dos_fatos":"Texto dos fatos.","do_direito":"Texto do direito."}'},
            )()

    class _FakeClient:
        models = _FakeModels()

    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        fatos_brutos="Cliente relata cobrança indevida.",
    )

    sections = await generate_sections_with_gemini(state, client=_FakeClient())

    assert captured["model"] == "gemini-3.1-pro-preview"
    assert sections["dos_fatos"] == "Texto dos fatos."


def test_build_revision_prompt_mentions_preserve_human_anchors_and_edited_sections():
    payload = build_redator_revision_payload(
        RatioEscritorioState(
            caso_id="caso-1",
            tipo_peca="peticao_inicial",
            peca_sections={"dos_fatos": "Texto original."},
        ),
        current_critique={"falhas_processuais": [], "argumentos_materiais_fracos": []},
        preserve_human_anchors=True,
        human_notes="preservar meu estilo",
        edited_sections=["dos_fatos"],
    )

    prompt = build_revision_prompt(payload)

    assert "preserve_human_anchors" in prompt
    assert "dos_fatos" in prompt
    assert "preservar meu estilo" in prompt


@pytest.mark.anyio
async def test_generate_revision_with_gemini_uses_reasoning_model():
    captured = {}

    class _FakeModels:
        def generate_content(self, *, model, contents):
            captured["model"] = model
            captured["contents"] = contents
            return type("Resp", (), {"text": '{"dos_fatos":"Texto revisado."}'})()

    class _FakeClient:
        models = _FakeModels()

    payload = {
        "caso_id": "caso-1",
        "tipo_peca": "peticao_inicial",
        "current_sections": {"dos_fatos": "Texto original."},
        "current_critique": {"falhas_processuais": [], "argumentos_materiais_fracos": []},
        "historical_round_summaries": [],
        "preserve_human_anchors": True,
    }

    sections = await generate_revision_with_gemini(payload, client=_FakeClient())

    assert captured["model"] == "gemini-3.1-pro-preview"
    assert sections["dos_fatos"] == "Texto revisado."


def test_infer_section_provenance_extracts_canonical_keys_from_section_text():
    sections = {
        "do_direito": "Conforme REsp 1.234.567/SP e art. 186 do CC, a tese procede."
    }

    provenance = infer_section_provenance(sections)

    assert "do_direito" in provenance
    assert "resp_1234567" in provenance["do_direito"]
    assert "art_186_cc" in provenance["do_direito"]
