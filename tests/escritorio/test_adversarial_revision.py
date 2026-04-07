from backend.escritorio.adversarial import dismiss_findings, register_critique_round, submit_human_revision
from backend.escritorio.models import RatioEscritorioState


def test_revision_payload_excludes_dismissed_findings_and_keeps_human_edits():
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        peca_sections={"fatos": "texto humano"},
    )
    state = register_critique_round(
        state,
        critique_payload={
            "falhas_processuais": [
                {
                    "secao_afetada": "fatos",
                    "descricao": "falta data",
                    "argumento_contrario": "ataque",
                    "query_jurisprudencia_contraria": "falta data peticao",
                }
            ],
            "argumentos_materiais_fracos": [],
            "jurisprudencia_faltante": [],
            "score_de_risco": 40,
            "analise_contestacao": "ha problema",
            "recomendacao": "revisar",
        },
    )
    finding_id = state.critica_atual.falhas_processuais[0].finding_id
    state = dismiss_findings(state, finding_ids=[finding_id], reason="juiz local nao exige isso")

    payload = submit_human_revision(
        state,
        section_updates={"fatos": "texto humano revisado"},
        notes="preservar meu estilo",
    )

    assert payload["current_sections"]["fatos"] == "texto humano revisado"
    assert payload["current_critique"]["falhas_processuais"] == []
    assert payload["preserve_human_anchors"] is True
