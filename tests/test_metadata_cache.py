import pytest
from unittest.mock import patch
from smartmule.metadata_engine import MetadataEngine
from smartmule.database import HashDatabase

"""
Este test verifica que la caché de metadatos funciona correctamente.
- Cache Miss: Se ejecuta el pipeline normal (Regex/IA/API) y se guarda en la caché.
- Cache Hit: Se recuperan los datos de la caché y no se ejecuta el pipeline.
"""

@pytest.fixture
def temp_db(tmp_path):
    """Crea una base de datos temporal para pruebas de caché."""
    db_file = tmp_path / "test_cache.db"
    db = HashDatabase(db_file)
    yield db
    db.close()

def test_cache_miss_and_save(temp_db):
    """
    Verifica que en un Cache Miss:
    1. Se ejecute el pipeline normal (Regex/IA/API).
    2. Los resultados se guarden en la tabla metadata_cache.
    """
    engine = MetadataEngine(db=temp_db)
    ed2k_hash = "faked_hash_123"
    filename = "Inception.2010.1080p.mkv"
    
    # Mockeamos el pipeline para evitar llamadas reales a APIs/IA/Disco
    with patch("smartmule.metadata_engine.parse_filename") as mock_regex, \
         patch("smartmule.metadata_engine.TMDBClient.search_movie") as mock_tmdb, \
         patch("smartmule.parsers.media_inspector.inspect_media_file") as mock_inspector:
        
        # Simulamos que la Regex reconoce el archivo con alta confianza
        mock_regex.return_value = {
            "title": "Inception",
            "year": 2010,
            "quality": "1080p",
            "media_type": "movie",
            "confidence": "high"
        }
        # La API devuelve una LISTA de resultados
        mock_tmdb.return_value = [{"title": "Inception", "release_date": "2010-07-16", "score": 8.8}]
        mock_inspector.return_value = {"duration_sec": 8880, "codec": "h264"}

        # Ejecutamos por primera vez (Cache Miss)
        res = engine.identify_file(filename, ed2k_hash=ed2k_hash)
        
        assert res["title"] == "Inception"
        
        # Verificamos que se haya guardado en la BBDD de caché
        cached = temp_db.get_metadata_cache(ed2k_hash)
        assert cached is not None
        assert cached["title"] == "Inception"
        assert "api_data" in cached

def test_cache_hit_skips_pipeline(temp_db):
    """
    Verifica que en un Cache Hit:
    1. Los datos se recuperen de la caché.
    2. El pipeline (Regex/IA/API) NO se ejecute (ahorro de recursos).
    """
    engine = MetadataEngine(db=temp_db)
    ed2k_hash = "faked_hash_hit"
    
    # Pre-insertamos datos en la caché de forma manual
    cached_payload = {
        "title": "Cached Movie",
        "media_type": "movie",
        "year": 2022,
        "api_data": {"source": "CacheTest"}
    }
    temp_db.set_metadata_cache(ed2k_hash, cached_payload)
    
    # Mockeamos el pipeline para verificar que NO se llama
    with patch("smartmule.metadata_engine.parse_filename") as mock_regex:
        # Si hay Cache Hit, identify_file debería retornar antes de llamar a parse_filename
        res = engine.identify_file("Cualquier_Nombre.mkv", ed2k_hash=ed2k_hash)
        
        # Verificamos que los datos vienen de la caché
        assert res["title"] == "Cached Movie"
        assert res["api_data"]["source"] == "CacheTest"
        
        # ¡IMPORTANTE!: Verificamos que el parser Regex NO fue invocado
        mock_regex.assert_not_called()

def test_cache_without_db_works_normally():
    """Verifica que si no hay instancia de DB, el sistema sigue funcionando (sin caché)."""
    engine = MetadataEngine(db=None)
    
    with patch("smartmule.metadata_engine.parse_filename") as mock_regex:
        mock_regex.return_value = {"title": "No Cache", "confidence": "high"}
        
        res = engine.identify_file("test.mkv", ed2k_hash="some_hash")
        assert res["title"] == "No Cache"
        mock_regex.assert_called_once()
