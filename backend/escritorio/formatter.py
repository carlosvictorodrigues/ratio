from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from backend.escritorio.models import RatioEscritorioState


class FormatadorPeticao:
    BLACK = RGBColor(0, 0, 0)

    def __init__(self, *, output_dir: str | Path):
        self.output_dir = Path(output_dir).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.doc = Document()
        self._configure_document()

    def _configure_document(self) -> None:
        section = self.doc.sections[0]
        section.left_margin = Cm(3)
        section.top_margin = Cm(3)
        section.right_margin = Cm(2)
        section.bottom_margin = Cm(2)

        style = self.doc.styles["Normal"]
        style.font.name = "Times New Roman"
        style.font.size = Pt(12)
        style.font.color.rgb = self.BLACK
        style.paragraph_format.line_spacing = 1.5
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.first_line_indent = Cm(2)
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

        for level in range(1, 4):
            heading = self.doc.styles[f"Heading {level}"]
            heading.font.name = "Times New Roman"
            heading.font.bold = True
            heading.font.size = Pt(14 if level == 1 else 12)
            heading.font.color.rgb = self.BLACK
            heading.paragraph_format.first_line_indent = Cm(0)
            heading.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT

    def add_cabecalho(self, tribunal: str = "", vara: str = "", processo: str = "") -> None:
        header = self.doc.sections[0].header
        paragraph = header.paragraphs[0]
        paragraph.text = ""
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if tribunal:
            run = paragraph.add_run(f"{tribunal}\n")
            run.font.name = "Times New Roman"
            run.font.size = Pt(11)
            run.font.color.rgb = self.BLACK
            run.bold = True
        if vara:
            run = paragraph.add_run(f"{vara}\n")
            run.font.name = "Times New Roman"
            run.font.size = Pt(10)
            run.font.color.rgb = self.BLACK
        if processo:
            run = paragraph.add_run(f"Processo: {processo}")
            run.font.name = "Times New Roman"
            run.font.size = Pt(10)
            run.font.color.rgb = self.BLACK

    def add_enderecamento(self, texto_enderecamento: str):
        paragraph = self.doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run(str(texto_enderecamento or "").strip().upper())
        run.bold = True
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)
        run.font.color.rgb = self.BLACK
        self.doc.add_paragraph("")
        self.doc.add_paragraph("")
        return paragraph

    def add_secao(self, titulo: str, conteudo: str) -> None:
        self.doc.add_heading(titulo, level=1)
        self.doc.add_paragraph(conteudo)

    def add_citacao_longa(self, texto: str):
        paragraph = self.doc.add_paragraph(str(texto or "").strip())
        paragraph.paragraph_format.left_indent = Cm(4)
        paragraph.paragraph_format.line_spacing = 1.0
        paragraph.paragraph_format.first_line_indent = Cm(0)
        paragraph.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        for run in paragraph.runs:
            run.font.name = "Times New Roman"
            run.font.size = Pt(10)
            run.font.color.rgb = self.BLACK
        return paragraph

    def add_citacao(self, texto: str, *, verificada: bool = True):
        paragraph = self.doc.add_paragraph()
        run = paragraph.add_run(texto)
        run.font.name = "Times New Roman"
        run.font.size = Pt(10)
        run.font.color.rgb = self.BLACK
        if verificada:
            run.bold = True
            run.italic = True
        else:
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW
            marker = paragraph.add_run(" [VERIFICAR]")
            marker.font.name = "Times New Roman"
            marker.font.size = Pt(12)
            marker.font.bold = True
            marker.font.color.rgb = RGBColor(255, 0, 0)
            marker.font.highlight_color = WD_COLOR_INDEX.YELLOW
        return paragraph

    def add_numeracao_paginas(self) -> None:
        footer = self.doc.sections[0].footer
        paragraph = footer.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run()
        fld_begin = OxmlElement("w:fldChar")
        fld_begin.set(qn("w:fldCharType"), "begin")
        run._element.append(fld_begin)
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = "PAGE"
        run._element.append(instr)
        fld_end = OxmlElement("w:fldChar")
        fld_end.set(qn("w:fldCharType"), "end")
        run._element.append(fld_end)

    def gerar(self, state: RatioEscritorioState, verificacoes: list[dict]) -> str:
        self.add_cabecalho(processo=state.caso_id)
        enderecamento = getattr(state, "enderecamento", "") or ""
        if enderecamento:
            self.add_enderecamento(enderecamento)

        for titulo, conteudo in state.peca_sections.items():
            self.add_secao(titulo.upper().replace("_", " "), conteudo)

        for verificacao in verificacoes:
            referencia = str(verificacao.get("referencia") or "").strip()
            if not referencia:
                continue
            verificada = str(verificacao.get("level") or "") in {"exact_match", "strong_match"}
            self.add_citacao(referencia, verificada=verificada)

        self.add_numeracao_paginas()
        output_path = self.output_dir / "peticao_final.docx"
        self.doc.save(output_path)
        return str(output_path)
