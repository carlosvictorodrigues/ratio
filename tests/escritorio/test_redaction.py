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


def test_build_redaction_prompt_includes_theo_research_text_per_tese():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        fatos_brutos="Cliente relata cobrança indevida.",
        teses=[
            TeseJuridica(
                id="t1",
                descricao="Responsabilidade objetiva",
                tipo="principal",
                resposta_pesquisa="Theo concluiu que a banca responde objetivamente pelos danos materiais.",
            ),
            TeseJuridica(
                id="t2",
                descricao="Dano moral",
                tipo="subsidiaria",
                resposta_pesquisa="Theo identificou tese subsidiaria de dano moral in re ipsa.",
            ),
        ],
    )

    prompt = build_redaction_prompt(state)

    assert "Analise do Theo" in prompt
    assert "Responsabilidade objetiva" in prompt
    assert "Theo concluiu que a banca responde objetivamente" in prompt
    assert "Dano moral" in prompt
    assert "Theo identificou tese subsidiaria de dano moral" in prompt


def test_build_redaction_prompt_includes_complementary_legislation_groups():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        fatos_brutos="Autor pede gratuidade de justica e inversao do onus da prova.",
        teses=[
            TeseJuridica(
                id="t1",
                descricao="Responsabilidade objetiva",
                tipo="principal",
                resposta_pesquisa="Theo concluiu que ha defeito do servico.",
            )
        ],
        pesquisa_legislacao=[
            {"doc_id": "lei-1", "diploma": "CDC", "article": "14", "categoria": "material"},
        ],
        pesquisa_legislacao_complementar=[
            {"doc_id": "lei-2", "diploma": "CPC", "article": "98", "categoria": "processual"},
            {"doc_id": "lei-3", "diploma": "CDC", "article": "6", "categoria": "material"},
        ],
    )

    prompt = build_redaction_prompt(state)

    assert "Legislacao complementar" in prompt
    assert "PROCESSUAL" in prompt
    assert "MATERIAL" in prompt
    assert "art. 98 do CPC" in prompt
    assert "art. 6 do CDC" in prompt


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
        def generate_content(self, *, model, contents, config=None):
            captured["model"] = model
            captured["contents"] = contents
            captured["config"] = config
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
    assert getattr(getattr(captured["config"], "http_options", None), "timeout", None) == 120000


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
        def generate_content(self, *, model, contents, config=None):
            captured["model"] = model
            captured["contents"] = contents
            captured["config"] = config
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
    assert getattr(getattr(captured["config"], "http_options", None), "timeout", None) == 120000


@pytest.mark.anyio
async def test_generate_sections_with_gemini_falls_back_to_flash_preview_on_deadline():
    captured_models = []

    class _FakeModels:
        def generate_content(self, *, model, contents, config=None):
            captured_models.append((model, getattr(getattr(config, "http_options", None), "timeout", None)))
            if len(captured_models) == 1:
                raise RuntimeError("504 DEADLINE_EXCEEDED")
            return type("Resp", (), {"text": '{"dos_fatos":"Texto fallback."}'})()

    class _FakeClient:
        models = _FakeModels()

    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        fatos_brutos="Cliente relata cobrança indevida.",
    )

    sections = await generate_sections_with_gemini(state, client=_FakeClient())

    assert sections["dos_fatos"] == "Texto fallback."
    assert captured_models == [
        ("gemini-3.1-pro-preview", 120000),
        ("gemini-3-flash-preview", 120000),
    ]


def test_parse_sections_payload_strips_fences_and_trailing():
    payload = """```json
    {
      "dos_fatos": "Texto dos fatos.",
      "do_direito": "Texto do direito."
    }
    ```
    Espero que ajude.
    """

    sections = parse_sections_payload(payload)

    assert sections["dos_fatos"] == "Texto dos fatos."
    assert sections["do_direito"] == "Texto do direito."


def test_parse_sections_payload_flattens_nested_dict_values():
    """CRITICAL: Gemini sometimes returns each section as a nested dict.

    We must extract the content — never drop it or call str() naively.
    """
    payload = """
    {
      "dos_fatos": {"titulo": "Dos Fatos", "conteudo": "O autor compareceu ao exame..."},
      "do_direito": {"titulo": "Do Direito", "texto": "Nos termos do art. 186 CC..."}
    }
    """

    sections = parse_sections_payload(payload)

    assert "O autor compareceu ao exame" in sections["dos_fatos"]
    assert "Nos termos do art. 186 CC" in sections["do_direito"]


def test_parse_sections_payload_flattens_list_values():
    """Gemini may return a section as a list of paragraphs."""
    payload = """
    {
      "dos_fatos": ["Primeiro paragrafo.", "Segundo paragrafo."],
      "do_direito": "Texto simples."
    }
    """

    sections = parse_sections_payload(payload)

    assert "Primeiro paragrafo." in sections["dos_fatos"]
    assert "Segundo paragrafo." in sections["dos_fatos"]
    assert sections["do_direito"] == "Texto simples."


def test_parse_sections_payload_unwraps_envelope():
    """Gemini may wrap sections inside ``{"peca_sections": {...}}``."""
    payload = """
    {
      "peca_sections": {
        "dos_fatos": "Texto dos fatos.",
        "do_direito": "Texto do direito."
      }
    }
    """

    sections = parse_sections_payload(payload)

    assert sections["dos_fatos"] == "Texto dos fatos."
    assert sections["do_direito"] == "Texto do direito."


def test_parse_sections_payload_preserves_all_dict_fields_when_no_canonical_key():
    """A section dict without conteudo/texto/descricao must still produce content."""
    payload = """
    {
      "dos_fatos": {"fundamento": "art. 186 CC", "argumento": "nexo causal comprovado"}
    }
    """

    sections = parse_sections_payload(payload)

    # Both fields must survive in the output
    assert "art. 186 CC" in sections["dos_fatos"]
    assert "nexo causal comprovado" in sections["dos_fatos"]


def test_infer_section_provenance_extracts_canonical_keys_from_section_text():
    sections = {
        "do_direito": "Conforme REsp 1.234.567/SP e art. 186 do CC, a tese procede."
    }

    provenance = infer_section_provenance(sections)

    assert "do_direito" in provenance
    assert "resp_1234567" in provenance["do_direito"]
    assert "art_186_cc" in provenance["do_direito"]
