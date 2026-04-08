from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FalhaCritica(BaseModel):
    finding_id: str = ""
    secao_afetada: str = ""
    origem: Literal["contraparte", "parecer_externo"] = "contraparte"
    tipo: Literal[
        "processual",
        "material",
        "logica",
        "jurisprudencia_fraca",
        "citacao_incorreta",
        "prova_insuficiente",
        "prescricao",
        "ilegitimidade",
    ] = "material"
    gravidade: Literal["alta", "media", "baixa"] = "media"
    descricao: str = ""
    argumento_contrario: str = ""
    query_jurisprudencia_contraria: str = ""
    jurisprudencia_encontrada: list[dict[str, Any]] | None = None


class CriticaContraparte(BaseModel):
    falhas_processuais: list[FalhaCritica] = Field(default_factory=list)
    argumentos_materiais_fracos: list[FalhaCritica] = Field(default_factory=list)
    jurisprudencia_faltante: list[str] = Field(default_factory=list)
    score_de_risco: int = Field(ge=0, le=100)
    analise_contestacao: str
    recomendacao: Literal["aprovar", "revisar", "reestruturar"]


class DismissedFinding(BaseModel):
    finding_id: str
    reason: str = ""


class TeseJuridica(BaseModel):
    id: str
    descricao: str
    tipo: Literal["principal", "subsidiaria"] = "principal"
    resposta_pesquisa: str = ""
    jurisprudencia_favoravel: list[dict[str, Any]] = Field(default_factory=list)
    jurisprudencia_contraria: list[dict[str, Any]] = Field(default_factory=list)
    legislacao: list[dict[str, Any]] = Field(default_factory=list)
    confianca: Literal["alta", "media", "baixa"] = "media"


class RodadaAdversarial(BaseModel):
    numero: int
    resumo_rodada: str = ""
    critica_contraparte: CriticaContraparte | None = None
    edicoes_humanas: dict[str, str] | None = None
    apontamentos_humanos: str | None = None
    secoes_revisadas: list[str] = Field(default_factory=list)
    dismissed_findings: list[DismissedFinding] = Field(default_factory=list)


class IntakeMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class IntakeChecklist(BaseModel):
    partes_identificadas: bool = False
    fatos_principais_cobertos: bool = False
    documentos_listados: bool = False


class RatioEscritorioState(BaseModel):
    caso_id: str
    tipo_peca: Literal["peticao_inicial", "contestacao"]
    area_direito: str = ""
    fatos_brutos: str = ""
    fatos_estruturados: list[str] = Field(default_factory=list)
    provas_disponiveis: list[str] = Field(default_factory=list)
    provas_recomendadas: list[str] = Field(default_factory=list)
    pontos_atencao: list[str] = Field(default_factory=list)
    documentos_cliente: list[dict[str, Any]] = Field(default_factory=list)
    teses: list[TeseJuridica] = Field(default_factory=list)
    pesquisa_jurisprudencia: list[dict[str, Any]] = Field(default_factory=list)
    pesquisa_legislacao: list[dict[str, Any]] = Field(default_factory=list)
    pesquisa_legislacao_complementar: list[dict[str, Any]] = Field(default_factory=list)
    peca_sections: dict[str, str] = Field(default_factory=dict)
    proveniencia: dict[str, list[str]] = Field(default_factory=dict)
    evidence_pack: dict[str, list[str]] = Field(default_factory=dict)
    rodadas: list[RodadaAdversarial] = Field(default_factory=list)
    rodada_atual: int = 0
    critica_atual: CriticaContraparte | None = None
    intake_history: list[IntakeMessage] = Field(default_factory=list)
    intake_checklist: IntakeChecklist = Field(default_factory=IntakeChecklist)
    resposta_conversacional_clara: str = ""
    perguntas_pendentes: list[str] = Field(default_factory=list)
    triagem_suficiente: bool = False
    gate1_aprovado: bool = False
    gate2_aprovado: bool = False
    usuario_finaliza: bool = False
    contraparte_retries: int = 0
    token_log: list[dict[str, Any]] = Field(default_factory=list)
    custo_total_usd: float = 0.0
    verificacoes: list[dict[str, Any]] = Field(default_factory=list)
    output_docx_path: str = ""
    status: Literal[
        "intake",
        "gate1",
        "pesquisa",
        "gate2",
        "redacao",
        "adversarial",
        "revisao_humana",
        "verificacao",
        "entrega",
        "finalizado",
    ] = "intake"
    workflow_stage: str = "intake"
