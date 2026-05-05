import pytest
from unittest.mock import patch, MagicMock
from smartmule.metadata_engine import MetadataEngine
from smartmule.database import HashDatabase

"""
Test de Integración: Flujo de Enriquecimiento de Libros (OpenLibrary).
Verifica que los metadatos profundos (Sinopsis, Personajes, Lugares) se obtengan de la API y se guarden correctamente en la base de datos principal.
"""

@pytest.fixture
def temp_db(tmp_path):
    """Crea una base de datos temporal para pruebas de integración."""
    db_file = tmp_path / "test_enrichment.db"
    db = HashDatabase(db_file)
    
    # Insertamos un registro base para poder actualizar sus metadatos
    db._conn.execute(
        "INSERT INTO files (file_path, file_name, file_size, fingerprint, ed2k_hash, ed2k_link, processed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("incoming/hobbit.epub", "hobbit.epub", 1000, "fake_fingerprint", "fake_hash", "ed2k://...", "2026-05-05")
    )
    db._conn.commit()
    
    yield db
    db.close()

def test_openlibrary_integration_flow(temp_db):
    """
    Simula el proceso completo:
    1. El motor identifica un archivo como libro.
    2. Se llama a la búsqueda de OpenLibrary (Mocked).
    3. Se llama a los detalles de OpenLibrary (Mocked) para traer personajes/lugares.
    4. Se actualiza la base de datos y se verifica que los campos bilingües estén llenos.
    """
    engine = MetadataEngine(db=temp_db)
    
    # Datos simulados de la búsqueda (Fase 1)
    mock_search_result = {
        "title": "The Hobbit",
        "author_name_str": "J.R.R. Tolkien",
        "first_publish_year": 1937,
        "ratings_average": 4.5,
        "key": "/works/OL12345W",
        "subject": ["Fantasy", "Adventure"]
    }
    
    # Datos simulados de los detalles (Fase 0.5 - El cambio que acabamos de hacer)
    mock_details_result = {
        "description": "In a hole in the ground there lived a hobbit.",
        "people": ["Bilbo Baggins", "Gandalf"],
        "places": ["The Shire", "Middle-earth"]
    }

    with patch("smartmule.metadata_engine.parse_filename") as mock_regex, \
         patch("smartmule.api.openlibrary_client.OpenLibraryClient.search_book") as mock_search, \
         patch("smartmule.api.openlibrary_client.OpenLibraryClient.get_book_details") as mock_details:
        
        # Configuramos los mocks
        mock_regex.return_value = {"title": "The Hobbit", "confidence": "high", "media_type": "book"}
        mock_search.return_value = mock_search_result
        mock_details.return_value = mock_details_result

        # 1. Ejecutamos la identificación (esto disparará las dos llamadas a la API)
        metadata = engine.identify_file("hobbit.epub", ed2k_hash="fake_hash")
        
        # Verificamos que se hicieron las llamadas correctas
        mock_search.assert_called_once()
        mock_details.assert_called_with("/works/OL12345W")

        # 2. Persistimos los datos en la tabla 'files' de la BBDD
        # En el flujo real, esto lo hace el organizador o el daemon usando update_metadata
        temp_db.update_metadata(
            fingerprint="fake_fingerprint",
            file_size=1000,
            metadata=metadata,
            final_path="library/Books/The Hobbit.epub"
        )

        # 3. Verificación Final en la Base de Datos
        cursor = temp_db._conn.execute("SELECT overview, genres, author FROM files WHERE fingerprint='fake_fingerprint'")
        row = cursor.fetchone()
        
        db_overview = row[0]
        db_genres = row[1]
        db_author = row[2]

        # Comprobamos que la sinopsis llegó a la BBDD
        assert db_overview == "In a hole in the ground there lived a hobbit."
        
        # Comprobamos que el autor es correcto
        assert db_author == "J.R.R. Tolkien"
        
        # Comprobamos que los géneros son el "Combo" (Temas + Personajes + Lugares)
        # El orden esperado según nuestro código es: subjects + people + places
        expected_genres = "Fantasy, Adventure, Bilbo Baggins, Gandalf, The Shire, Middle-earth"
        assert db_genres == expected_genres

        print("\n[OK] Test de integración de OpenLibrary completado con éxito.")
