import pytest
from unittest.mock import patch, MagicMock
from smartmule.api.openlibrary_client import OpenLibraryClient

@pytest.fixture
def ol_client():
    return OpenLibraryClient()

@patch('smartmule.api.openlibrary_client.requests.get')
def test_search_book_success(mock_get, ol_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "docs": [
            {
                "title": "El Señor de los Anillos",
                "author_name": ["J. R. R. Tolkien"],
                "first_publish_year": 1954
            }
        ]
    }
    mock_get.return_value = mock_response

    result = ol_client.search_book("El Señor de los Anillos")
    assert result is not None
    assert result["title"] == "El Señor de los Anillos"
    assert result["author_name_str"] == "J. R. R. Tolkien"
    mock_get.assert_called_once()

@patch('smartmule.api.openlibrary_client.requests.get')
def test_search_book_empty(mock_get, ol_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"docs": []}
    mock_get.return_value = mock_response

    result = ol_client.search_book("Non Existing Book ZZZZ")
    assert result is None
