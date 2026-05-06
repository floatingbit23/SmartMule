import pytest
import sys
from unittest.mock import patch

from smartmule.embeddings import is_available

if is_available():
    import numpy as np
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
    
    # RRF occurs inside search_hybrid. Let's mock search_by_name, search_semantic and rerank_results
    def mock_rerank_impl(q, r_list):
        for r in r_list:
            r['rerank_score'] = r.get('semantic_score', 0.5)
            r['is_reranked'] = True
        return sorted(r_list, key=lambda x: x['rerank_score'], reverse=True)

    with patch.object(db, 'search_by_name') as mock_fts, \
         patch.object(db, 'search_semantic') as mock_sem, \
         patch('smartmule.embeddings.rerank_results', side_effect=mock_rerank_impl) as mock_rerank:
         
        mock_fts.return_value = [{"id": 1, "file_name": "movie1.mkv"}]
        mock_sem.return_value = [
            {"id": 1, "semantic_score": 0.8}, 
            {"id": 2, "semantic_score": 0.9}
        ]
        
        results = db.search_hybrid("query test")
        
        # El archivo 2 debe ser el primero ahora debido al re-ranking (score 0.9 vs 0.8)
        assert results[0]["id"] == 2
        assert results[0]["search_origin"] == "semantic"
        assert results[0]["is_reranked"] == True
        
        # El archivo 1 debe estar presente y marcado como híbrido (porque estaba en FTS)
        assert any(r["id"] == 1 for r in results)
        record1 = next(r for r in results if r["id"] == 1)
        assert record1["search_origin"] == "hybrid"


@pytest.mark.skipif(not is_available(), reason="FastEmbed not installed")
def test_rerank_results_logic():
    """El re-ranker debería ser capaz de re-ordenar resultados basándose en la semántica profunda."""
    from smartmule.embeddings import rerank_results
    
    query = "película de ciencia ficción en el espacio"
    results = [
        {"id": 1, "official_title": "El Padrino", "overview": "Crimen y mafia en Nueva York."},
        {"id": 2, "official_title": "Interstellar", "overview": "Un grupo de astronautas viaja a través de un agujero de gusano en el espacio."}
    ]
    
    # Re-rankeamos
    reranked = rerank_results(query, results)
    
    # Interstellar debería estar el primero ahora
    assert reranked[0]["id"] == 2
    assert reranked[0]["is_reranked"] == True
    assert "rerank_score" in reranked[0]
