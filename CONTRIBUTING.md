# Contributing to Ratio

Obrigado por contribuir com o Ratio.

## 1. Antes de comecar

- Use Python 3.10 ou superior.
- Instale dependencias com:

```bash
py -m pip install -r requirements.txt
py -m pip install pytest
```

- Copie `.env.example` para `.env` e preencha `GEMINI_API_KEY`.

## 2. Rodando localmente

Backend:

```bash
py -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend:

```bash
py -m http.server 5500 --directory frontend
```

Abra `http://127.0.0.1:5500`.

## 3. Fluxo de contribuicao

1. Crie uma branch descritiva a partir de `main`.
2. FaÃ§a mudancas pequenas e focadas.
3. Adicione ou atualize testes quando houver mudanca de comportamento.
4. Rode testes localmente:

```bash
py -m pytest
```

5. Abra PR com:
- contexto do problema
- descricao da solucao
- risco conhecido e como validar

## 4. Padrao de PR

- Evite misturar refatoracao ampla com feature/correcao.
- Nao inclua dados locais pesados (`data/`, `lancedb_store/`, `logs/runtime/`).
- Nao commite segredos (`.env`, chaves, tokens).

## 5. Bugs e ideias

- Use Issues para bugs e requests de melhoria.
- Para vulnerabilidades, siga [SECURITY.md](SECURITY.md).


