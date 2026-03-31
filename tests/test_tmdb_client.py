import pytest
from unittest.mock import patch, MagicMock
from smartmule.api.tmdb_client import TMDBClient

@pytest.fixture(autouse=True)
def mock_env_vars():
    with patch('smartmule.api.tmdb_client.TMDB_BEARER_TOKEN', 'test_token'):
        yield

@pytest.fixture
def tmdb_client():
    return TMDBClient()

@patch('smartmule.api.tmdb_client.requests.get')
def test_search_movie_success(mock_get, tmdb_client):
    """Verifica que search_movie devuelve una lista de resultados cuando hay éxito."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {"id": 1, "title": "The Matrix", "release_date": "1999-03-31"}
        ]
    }
    mock_get.return_value = mock_response

    result = tmdb_client.search_movie("The Matrix", 1999)
    
    assert isinstance(result, list)
    assert len(result) > 0
    assert result[0]["title"] == "The Matrix"
    mock_get.assert_called_once()


@patch('smartmule.api.tmdb_client.requests.get')
def test_search_movie_empty(mock_get, tmdb_client):
    """Verifica que search_movie devuelve una lista vacía si no hay resultados."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": []}
    mock_get.return_value = mock_response

    result = tmdb_client.search_movie("Not Found Movie")
    assert result == []


@patch('smartmule.api.tmdb_client.requests.get')
def test_rate_limit(mock_get, tmdb_client):
    """Verifica que search_movie devuelve una lista vacía si hay Rate Limit (429)."""
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_get.return_value = mock_response

    result = tmdb_client.search_movie("The Matrix")
    assert result == []
