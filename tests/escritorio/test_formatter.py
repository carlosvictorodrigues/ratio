from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from backend.escritorio.formatter import FormatadorPeticao
from backend.escritorio.models import RatioEscritorioState


def test_formatador_peticao_gera_docx_com_secoes_do_state(tmp_path: Path):
    state = RatioEscritorioState(
        caso_id="caso-1",
        tipo_peca="peticao_inicial",
        peca_sections={
            "dos_fatos": "Texto dos fatos.",
            "do_direito": "Texto do direito.",
        },
    )
    formatter = FormatadorPeticao(output_dir=tmp_path)

    path = formatter.gerar(state, verificacoes=[])

    assert Path(path).exists()
    doc = Document(path)
    texts = [p.text for p in doc.paragraphs if p.text.strip()]
    assert "DOS FATOS" in texts
    assert "Texto dos fatos." in texts
    assert "DO DIREITO" in texts
    assert "Texto do direito." in texts


def test_formatador_peticao_destaca_citacao_nao_verificada(tmp_path: Path):
    formatter = FormatadorPeticao(output_dir=tmp_path)
    paragraph = formatter.add_citacao("REsp 1.234.567", verificada=False)

    marker_text = "".join(run.text for run in paragraph.runs)
    assert "[VERIFICAR]" in marker_text


def test_formatador_configura_estilo_normal_justificado_com_espacamento_e_cor(tmp_path: Path):
    formatter = FormatadorPeticao(output_dir=tmp_path)
    style = formatter.doc.styles["Normal"]

    assert style.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY
    assert style.paragraph_format.space_after == Pt(6)
    assert style.font.color.rgb == formatter.BLACK


def test_formatador_add_enderecamento_centralizado_em_caixa_alta(tmp_path: Path):
    formatter = FormatadorPeticao(output_dir=tmp_path)
    paragraph = formatter.add_enderecamento("Excelentíssimo Senhor Doutor Juiz de Direito")

    assert paragraph.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert paragraph.runs[0].text == "EXCELENTÍSSIMO SENHOR DOUTOR JUIZ DE DIREITO"
    assert paragraph.runs[0].bold is True


def test_formatador_add_citacao_longa_usa_bloco_recuado_e_fonte_10(tmp_path: Path):
    formatter = FormatadorPeticao(output_dir=tmp_path)
    paragraph = formatter.add_citacao_longa("Texto da ementa em bloco.")

    assert round(paragraph.paragraph_format.left_indent.cm, 1) == 4.0
    assert paragraph.paragraph_format.line_spacing == 1.0
    assert paragraph.paragraph_format.first_line_indent == Cm(0)
    assert paragraph.runs[0].font.size == Pt(10)


def test_formatador_add_numeracao_paginas_injeta_campo_page_no_rodape(tmp_path: Path):
    formatter = FormatadorPeticao(output_dir=tmp_path)
    formatter.add_numeracao_paginas()

    footer_xml = formatter.doc.sections[0].footer.paragraphs[0]._element.xml
    assert "PAGE" in footer_xml
