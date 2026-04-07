from backend.escritorio.tools.google_search import (
    build_google_legislation_query,
    parse_google_search_results,
)


def test_build_google_legislation_query_targets_official_legislation_domains():
    query = build_google_legislation_query("responsabilidade civil concurso público")

    assert "planalto.gov.br" in query
    assert "senado.leg.br" in query
    assert "legislação brasileira" in query


def test_parse_google_search_results_extracts_title_url_and_legislation_hints():
    html = """
    <html><body>
      <a href="/url?q=https://www.planalto.gov.br/ccivil_03/leis/l8078compilado.htm&sa=U&ved=2ah">
        <h3>Lei nº 8.078 - Código de Defesa do Consumidor</h3>
      </a>
      <div>Art. 14. O fornecedor responde independentemente de culpa...</div>
    </body></html>
    """

    rows = parse_google_search_results(html, limit=5)

    assert rows[0]["url"].startswith("https://www.planalto.gov.br/")
    assert "Código de Defesa do Consumidor" in rows[0]["title"]
    assert rows[0]["diploma"] == "CDC"
    assert rows[0]["article"] == "14"
