import pytest
import numpy as np
import sys
from unittest.mock import patch

from smartmule.embeddings import is_available

if is_available():
    from smartmule.embeddings import encode_text, decode_blob, cosine_similarity_batch, build_metadata_text
    from smartmule.database import HashDatabase

@pytest.mark.skipif(not is_available(), reason="FastEmbed not installed")
def test_blob_serialization_roundtrip():
    """Vector → BLOB → Vector produce el mismo resultado."""
    original_vec = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    blob = original_vec.tobytes()
    decoded_vec = decode_blob(blob)
    assert np.array_equal(original_vec, decoded_vec)

@pytest.mark.skipif(not is_available(), reason="FastEmbed not installed")
def test_cosine_similarity_identical():
    """Similitud de un vector consigo mismo = 1.0."""
    vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    blob = vec.tobytes()
    
    scores = cosine_similarity_batch([blob], vec)
    assert pytest.approx(scores[0], 0.001) == 1.0

@pytest.mark.skipif(not is_available(), reason="FastEmbed not installed")
def test_cosine_similarity_orthogonal():
    """Vectores ortogonales → similitud ≈ 0.0."""
    vec1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vec2 = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    
    blob1 = vec1.tobytes()
    
    scores = cosine_similarity_batch([blob1], vec2)
    assert pytest.approx(scores[0], 0.001) == 0.0

@pytest.mark.skipif(not is_available(), reason="FastEmbed not installed")
def test_build_metadata_text_complete():
    """Texto con título + año + géneros + overview."""
    record = {
        "official_title": "Matrix",
        "release_date": "1999-03-31",
        "genres": "Sci-Fi",
        "author": "Wachowskis",
        "overview": "Neo discovers the truth."
    }
    text = build_metadata_text(record)
    assert text == "Matrix. (1999). de Wachowskis. Sci-Fi. Neo discovers the truth."

@pytest.mark.skipif(not is_available(), reason="FastEmbed not installed")
def test_build_metadata_text_minimal():
    """Fallback a file_name cuando no hay metadatos."""
    record = {
        "file_name": "the_matrix_1080p.mkv"
    }
    text = build_metadata_text(record)
    assert text == "Archivo: the_matrix_1080p.mkv"

def test_is_available_without_deps():
    """Devuelve False si fastembed no está instalado."""
    with patch.dict('sys.modules', {'fastembed': None}):
        assert is_available() == False

@pytest.mark.skipif(not is_available(), reason="FastEmbed not installed")
def test_rrf_fusion_behavior():
    """Verifica que Weighted RRF fusiona correctamente FTS y Semantic en la BBDD."""
    db = HashDatabase(":memory:")
    
    # RRF occurs inside search_hybrid. Let's mock search_by_name and search_semantic
    with patch.object(db, 'search_by_name') as mock_fts, \
         patch.object(db, 'search_semantic') as mock_sem:
         
        mock_fts.return_value = [{"id": 1, "file_name": "movie1.mkv"}]
        mock_sem.return_value = [
            {"id": 1, "semantic_score": 0.8}, 
            {"id": 2, "semantic_score": 0.9}
        ]
        
        results = db.search_hybrid("query test")
        
        # El archivo 1 debe tener 'search_origin' = 'hybrid' y estar ordenado (dependiendo del score final)
        assert len(results) == 2
        
        # Verificar el origen
        assert results[0]["id"] == 1
        assert results[0]["search_origin"] == "hybrid"
        
        assert results[1]["id"] == 2
        assert results[1]["search_origin"] == "semantic"
