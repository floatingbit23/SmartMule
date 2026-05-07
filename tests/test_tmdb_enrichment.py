import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from smartmule.metadata_engine import MetadataEngine
from smartmule.database import HashDatabase

"""
Test de Integración: Flujo de Enriquecimiento Bilingüe (TMDB).
Verifica que SmartMule capture correctamente:
1. La sinopsis en Español (overview).
2. La sinopsis en Inglés (overview_en).
3. El mapeo de géneros bilingüe (ES | EN).
"""

@pytest.fixture
def temp_db(tmp_path):
    """Crea una base de datos temporal para pruebas de integración."""
    db_file = tmp_path / "test_tmdb_enrichment.db"
    db = HashDatabase(db_file)
    
    # Insertamos un registro base (vídeo)
    db._conn.execute(
        "INSERT INTO files (file_path, file_name, file_size, fingerprint, ed2k_hash, ed2k_link, processed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("incoming/matrix.mkv", "matrix.mkv", 5000, "matrix_fingerprint", "matrix_hash", "ed2k://...", "2026-05-05")
    )
    db._conn.commit()
    
    yield db
    db.close()

def test_tmdb_bilingual_enrichment_flow(temp_db):
    """
    Simula el proceso completo para una película:
    - Búsqueda inicial (ES) -> Captura sinopsis ES.
    - Llamada a detalles (EN) -> Captura sinopsis EN y runtime.
    - Mapeo de géneros -> Genera cadena "ES | EN".
    """
    # Datos simulados de la búsqueda
    mock_search_results = [{
        "id": 603,
        "title": "The Matrix",
        "release_date": "1999-03-31",
        "vote_average": 8.2,
        "overview": "Matrix es una película de acción...",
        "genre_ids": [28, 878] # Acción, Ciencia ficción
    }]
    
    # Datos simulados de los detalles en Inglés
    mock_details_en = {
        "runtime": 136,
        "overview": "A computer hacker learns from mysterious rebels..."
    }

    with patch("smartmule.metadata_engine.parse_filename") as mock_regex, \
         patch("smartmule.api.tmdb_client.TMDBClient.search_movie") as mock_search, \
         patch("smartmule.api.tmdb_client.TMDBClient.get_movie_details") as mock_details, \
         patch("smartmule.metadata_engine.inspect_media_file") as mock_inspector, \
         patch("pathlib.Path.exists", return_value=True):
        
        # Instanciamos el motor DENTRO del patch para que use los mocks
        engine = MetadataEngine(db=temp_db)

        # Configuramos los mocks
        mock_regex.return_value = {"title": "The Matrix", "confidence": "high", "media_type": "movie"}
        mock_search.return_value = mock_search_results
        mock_details.return_value = mock_details_en
        # Simulamos que el archivo dura 136 minutos para que el scoring sea alto
        mock_inspector.return_value = {"duration_sec": 136 * 60, "is_media": True}

        # 1. Ejecutamos la identificación (Pasamos un filepath ficticio para disparar el inspector)
        metadata = engine.identify_file("matrix.mkv", filepath=Path("incoming/matrix.mkv"), ed2k_hash="matrix_hash")
        
        # Verificamos que se pidió la versión en inglés para el enriquecimiento
        mock_details.assert_called_with(603, language="en-US")

        # 2. Persistimos en la base de datos
        temp_db.update_metadata(
            fingerprint="matrix_fingerprint",
            file_size=5000,
            metadata=metadata,
            final_path="library/Movies/The Matrix (1999).mkv"
        )

        # 3. Verificación en la Base de Datos
        cursor = temp_db._conn.execute("SELECT overview, overview_en, genres, genres_en FROM files WHERE fingerprint='matrix_fingerprint'")
        row = cursor.fetchone()
        
        db_overview_es = row[0]
        db_overview_en = row[1]
        db_genres_es = row[2]
        db_genres_en = row[3]

        # Comprobamos sinopsis ES
        assert "película de acción" in db_overview_es
        
        # Comprobamos sinopsis EN (Capturada de los detalles)
        assert "computer hacker" in db_overview_en
        
        # Comprobamos géneros bilingües (ahora en columnas separadas)
        assert "Acción" in db_genres_es
        assert "Action" in db_genres_en
        assert "Ciencia ficción" in db_genres_es
        assert "Science Fiction" in db_genres_en

        print("\n[OK] Test de enriquecimiento bilingüe TMDB completado con éxito.")
