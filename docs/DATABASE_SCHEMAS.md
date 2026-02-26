# Relatório de Estrutura dos Bancos de Dados (Schema)

Gerado em: inspect_schemas.py

# Schema: Acordaos
**Path:** `data/acordaos/acordaos.db`

## Table: `acordaos`

| CID | Name | Type | NotNull | Default | PK |
|---|---|---|---|---|---|
| 0 | **id** | TEXT | 0 | None | 1 |
| 1 | **dg_unique** | TEXT | 0 | None | 0 |
| 2 | **titulo** | TEXT | 0 | None | 0 |
| 3 | **processo_codigo** | TEXT | 0 | None | 0 |
| 4 | **processo_numero** | INTEGER | 0 | None | 0 |
| 5 | **classe_sigla** | TEXT | 0 | None | 0 |
| 6 | **classe_extenso** | TEXT | 0 | None | 0 |
| 7 | **orgao_julgador** | TEXT | 0 | None | 0 |
| 8 | **relator** | TEXT | 0 | None | 0 |
| 9 | **ministros** | TEXT | 0 | None | 0 |
| 10 | **julgamento_data** | TEXT | 0 | None | 0 |
| 11 | **publicacao_data** | TEXT | 0 | None | 0 |
| 12 | **ementa** | TEXT | 0 | None | 0 |
| 13 | **acordao_ata** | TEXT | 0 | None | 0 |
| 14 | **partes** | TEXT | 0 | None | 0 |
| 15 | **uf_sigla** | TEXT | 0 | None | 0 |
| 16 | **uf_completo** | TEXT | 0 | None | 0 |
| 17 | **inteiro_teor_url** | TEXT | 0 | None | 0 |
| 18 | **acompanhamento_url** | TEXT | 0 | None | 0 |
| 19 | **dje_url** | TEXT | 0 | None | 0 |
| 20 | **legislacao_citada** | TEXT | 0 | None | 0 |
| 21 | **indexacao** | TEXT | 0 | None | 0 |
| 22 | **observacao** | TEXT | 0 | None | 0 |
| 23 | **tese** | TEXT | 0 | None | 0 |
| 24 | **tese_tema** | TEXT | 0 | None | 0 |
| 25 | **is_repercussao_geral** | BOOLEAN | 0 | None | 0 |
| 26 | **is_questao_ordem** | BOOLEAN | 0 | None | 0 |
| 27 | **is_colac** | BOOLEAN | 0 | None | 0 |
| 28 | **is_sessao_virtual** | BOOLEAN | 0 | None | 0 |
| 29 | **raw_json** | TEXT | 0 | None | 0 |
| 30 | **extracted_at** | TEXT | 0 | None | 0 |
| 31 | **ramo_direito** | TEXT | 0 | None | 0 |
| 32 | **ai_tags** | TEXT | 0 | None | 0 |
| 33 | **ai_processed** | INTEGER | 0 | 0 | 0 |

**Total Rows:** 223077

### Sample Row (First Record)
```json
{
  "id": "sjur549063",
  "dg_unique": "sjur549063",
  "titulo": "HC 264221 ED",
  "processo_codigo": "HC 264221 ED",
  "processo_numero": 264221,
  "classe_sigla": "HC",
  "classe_extenso": "EMB.DECL. NO HABEAS CORPUS",
  "orgao_julgador": "Primeira Turma",
  "relator": "ALEXANDRE DE MORAES",
  "ministros": "ALEXANDRE DE MORAES",
  "julgamento_data": "2025-11-26",
  "publicacao_data": "2025-12-01",
  "ementa": "Ementa: EMBARGOS DE DECLARA\u00c7\u00c3O RECEBIDOS COMO AGRAVO REGIMENTAL EM HABEAS CORPUS. MAT\u00c9RIAS SUSCITADAS N\u00c3O EXAMINADAS PELO SUPERIOR TRIBUNAL DE JUSTI\u00c7A. SUPRESS\u00c3O DE INST\u00c2NCIA. PEDIDO SUCED\u00c2NEO DE REVI... [TRUNCATED]",
  "acordao_ata": "A Turma, por unanimidade, recebeu os embargos de declara\u00e7\u00e3o como agravo regimental e negou-lhe provimento, nos termos do voto do Relator, Ministro Alexandre de Moraes. Primeira Turma, Sess\u00e3o Virtual d... [TRUNCATED]",
  "partes": "EMBTE.(S)  : ALEF RIBEIRO DE SOUZA \nADV.(A/S)  : SAMIRA PEREIRA LOURENCO DOS SANTOS (74392/DF, 525480/SP) \nEMBDO.(A/S)  : SUPERIOR TRIBUNAL DE JUSTI\u00c7A",
  "uf_sigla": "SP",
  "uf_completo": "SP - S\u00c3O PAULO",
  "inteiro_teor_url": "https://portal.stf.jus.br/jurisprudencia/obterInteiroTeor.asp?idDocumento=793016999",
  "acompanhamento_url": "https://portal.stf.jus.br/processos/listarProcessos.asp?numeroProcesso=264221&classe=HC",
  "dje_url": "https://portal.stf.jus.br/servicos/dje/listarDiarioJustica.asp?tipoPesquisaDJ=AP&numero=264221&classe=HC",
  "legislacao_citada": null,
  "indexacao": null,
  "observacao": null,
  "tese": null,
  "tese_tema": null,
  "is_repercussao_geral": 0,
  "is_questao_ordem": 0,
  "is_colac": 0,
  "is_sessao_virtual": 0,
  "raw_json": "{\"base\": \"acordaos\", \"id\": \"sjur549063\", \"dg_unique\": \"sjur549063\", \"titulo\": \"HC 264221 ED\", \"ministro_facet\": [\"ALEXANDRE DE MORAES\"], \"procedencia_geografica_uf_sigla\": \"SP\", \"procedencia_geografic... [TRUNCATED]",
  "extracted_at": "2026-02-06T14:59:38.850348",
  "ramo_direito": "Penal",
  "ai_tags": "[]",
  "ai_processed": 1
}
```

---

## Table: `extraction_progress`

| CID | Name | Type | NotNull | Default | PK |
|---|---|---|---|---|---|
| 0 | **id** | INTEGER | 0 | None | 1 |
| 1 | **last_offset** | INTEGER | 0 | None | 0 |
| 2 | **total_records** | INTEGER | 0 | None | 0 |
| 3 | **started_at** | TEXT | 0 | None | 0 |
| 4 | **updated_at** | TEXT | 0 | None | 0 |

**Total Rows:** 1

### Sample Row (First Record)
```json
{
  "id": 1,
  "last_offset": 10000,
  "total_records": 362494,
  "started_at": "2026-02-06T14:54:16.490448",
  "updated_at": "2026-02-06T15:00:17.415996"
}
```

---

## Table: `year_progress`

| CID | Name | Type | NotNull | Default | PK |
|---|---|---|---|---|---|
| 0 | **year** | INTEGER | 0 | None | 1 |
| 1 | **total_in_year** | INTEGER | 0 | None | 0 |
| 2 | **extracted** | INTEGER | 0 | None | 0 |
| 3 | **completed** | BOOLEAN | 0 | None | 0 |
| 4 | **updated_at** | TEXT | 0 | None | 0 |

**Total Rows:** 0

_Table is empty._

---

# Schema: Sumulas
**Path:** `data/sumulas/sumulas.db`

## Table: `sumulas`

| CID | Name | Type | NotNull | Default | PK |
|---|---|---|---|---|---|
| 0 | **numero** | INTEGER | 0 | None | 1 |
| 1 | **titulo** | TEXT | 0 | None | 0 |
| 2 | **status** | TEXT | 0 | None | 0 |
| 3 | **enunciado** | TEXT | 0 | None | 0 |
| 4 | **data_aprovacao** | TEXT | 0 | None | 0 |
| 5 | **jurisprudencia** | TEXT | 0 | None | 0 |
| 6 | **observacoes** | TEXT | 0 | None | 0 |
| 7 | **url** | TEXT | 0 | None | 0 |
| 8 | **extracted_at** | TEXT | 0 | None | 0 |

**Total Rows:** 736

### Sample Row (First Record)
```json
{
  "numero": 1,
  "titulo": "S\u00famula 1",
  "status": "vigente",
  "enunciado": "\u00c9 vedada a expuls\u00e3o de estrangeiro casado com brasileira, ou que tenha filho brasileiro, dependente da economia paterna.",
  "data_aprovacao": "13-12-1963",
  "jurisprudencia": "[{\"tipo\": \"topico\", \"texto\": \"Condi\u00e7\u00f5es para expuls\u00e3o\u00a0em caso de casamento ou paternidade de filho brasileiroRecurso em habeas corpus. Expuls\u00e3o de estrangeiro. Direito de permanecer no Brasil. N\u00e3o oco... [TRUNCATED]",
  "observacoes": "",
  "url": "https://portal.stf.jus.br/jurisprudencia/sumariosumulas.asp?base=30&sumula=1451",
  "extracted_at": "2026-02-06T14:22:53.035367"
}
```

---

# Schema: Informativos
**Path:** `data/informativos/informativos.db`

## Table: `informativos`

| CID | Name | Type | NotNull | Default | PK |
|---|---|---|---|---|---|
| 0 | **id** | TEXT | 0 | None | 1 |
| 1 | **dg_unique** | TEXT | 0 | None | 0 |
| 2 | **titulo** | TEXT | 0 | None | 0 |
| 3 | **informativo_numero** | INTEGER | 0 | None | 0 |
| 4 | **informativo_titulo** | TEXT | 0 | None | 0 |
| 5 | **informativo_data** | TEXT | 0 | None | 0 |
| 6 | **resumo** | TEXT | 0 | None | 0 |
| 7 | **observacao** | TEXT | 0 | None | 0 |
| 8 | **processo_codigo** | TEXT | 0 | None | 0 |
| 9 | **processo_numero** | INTEGER | 0 | None | 0 |
| 10 | **classe_sigla** | TEXT | 0 | None | 0 |
| 11 | **orgao_julgador** | TEXT | 0 | None | 0 |
| 12 | **relator** | TEXT | 0 | None | 0 |
| 13 | **ministros** | TEXT | 0 | None | 0 |
| 14 | **julgamento_data** | TEXT | 0 | None | 0 |
| 15 | **publicacao_data** | TEXT | 0 | None | 0 |
| 16 | **ementa** | TEXT | 0 | None | 0 |
| 17 | **partes** | TEXT | 0 | None | 0 |
| 18 | **inteiro_teor_url** | TEXT | 0 | None | 0 |
| 19 | **tese** | TEXT | 0 | None | 0 |
| 20 | **raw_json** | TEXT | 0 | None | 0 |
| 21 | **extracted_at** | TEXT | 0 | None | 0 |

**Total Rows:** 11385

### Sample Row (First Record)
```json
{
  "id": "novo-informativo-11499",
  "dg_unique": "novo_informativo_11499",
  "titulo": "ADI 5014",
  "informativo_numero": null,
  "informativo_titulo": null,
  "informativo_data": null,
  "resumo": null,
  "observacao": null,
  "processo_codigo": null,
  "processo_numero": 5014,
  "classe_sigla": "ADI",
  "orgao_julgador": "Tribunal Pleno",
  "relator": "DIAS TOFFOLI",
  "ministros": "DIAS TOFFOLI",
  "julgamento_data": "2023-11-10T03:00:00-03:00",
  "publicacao_data": null,
  "ementa": null,
  "partes": null,
  "inteiro_teor_url": null,
  "tese": null,
  "raw_json": "{\"base\": \"novo_informativo\", \"id\": \"novo-informativo-11499\", \"dg_unique\": \"novo_informativo_11499\", \"titulo\": \"ADI 5014\", \"processo_classe_processual_unificada_classe_sigla\": \"ADI\", \"processo_numero\":... [TRUNCATED]",
  "extracted_at": "2026-02-06T15:33:54.514103"
}
```

---

