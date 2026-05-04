import pytest
from pathlib import Path
from smartmule.database import HashDatabase

@pytest.fixture
def db(tmp_path):
    """Crea una base de datos temporal con datos iniciales para pruebas de búsqueda."""
    db_file = tmp_path / "test_search.db"
    db = HashDatabase(db_file)
    
    # Insertamos datos de prueba representativos
    test_data = [
        # file_path, file_name, official_title, media_type, score
        ("path/1", "Matrix.mkv", "The Matrix", "movie", 8.7),
        ("path/2", "Amélie.mp4", "Amélie", "movie", 8.3),
        ("path/3", "Netfly.ps1", "", "unknown", 0.0),
        ("path/4", "Foto_2024.jpg", "", "image", 0.0),
        ("path/5", "Inception.mp4", "Inception", "movie", 8.8),
        ("path/6", "Puñales por la espalda (2019).mkv", "Puñales por la espalda", "movie", 7.9),
    ]
    
    for path, name, title, mtype, score in test_data:
        # Añadimos una duración de prueba (120 min = 7200 seg) solo para películas
        duration = 7200 if mtype == "movie" else 0
        db._conn.execute(
            """INSERT INTO files (file_path, file_name, official_title, media_type, score, file_size, ed2k_hash, ed2k_link, processed_at, duration) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (path, name, title, mtype, score, 100, f"hash_{name}", f"link_{name}", "2026-01-01 10:00:00", duration)
        )
    
    # Forzamos sincronización inicial de FTS5 (en el constructor ya se hace si está vacía, 
    # pero aquí hemos insertado después del constructor).
    db._conn.execute("""
        INSERT INTO files_fts(rowid, file_name, official_title)
        SELECT id, file_name, official_title FROM files
    """)
    db._conn.commit()
    
    yield db
    db.close()

# --- TESTS FASE 1: FTS5 Y REGEXP ---

def test_fts5_basic(db):
    """FTS5 básico: Encuentra Matrix.mkv y The Matrix"""
    results = db.search_by_name("Matrix")
    assert len(results) >= 1
    # Debería encontrar el registro con official_title "The Matrix"
    assert any("Matrix" in (r['official_title'] or "") for r in results)

def test_fts5_accents(db):
    """FTS5 con acentos: Encuentra Amélie buscando 'amelie'"""
    results = db.search_by_name("amelie")
    assert len(results) == 1
    assert "Amélie" in results[0]['official_title']

def test_fts5_p2p_chars(db):
    """FTS5 con caracteres P2P: No crashea (sanitización)"""
    # Intentamos una búsqueda con puntos y años típica de P2P
    try:
        results = db.search_by_name("The.Matrix.1999")
        # No esperamos necesariamente resultados exactos si no hay coincidencia 1:1, 
        # pero sí que no lance excepción de sintaxis SQLite.
        assert isinstance(results, list)
    except Exception as e:
        pytest.fail(f"La búsqueda FTS5 crasheó con caracteres P2P: {e}")

def test_wildcard_compat(db):
    """Wildcard retrocompatible: Sigue funcionando (fallback REGEXP)"""
    results = db.search_by_name("N*")
    assert len(results) == 1
    assert results[0]['file_name'] == "Netfly.ps1"

def test_regex_compat(db):
    """Regex puro retrocompatible: Sigue funcionando (fallback REGEXP)"""
    results = db.search_by_name(r".*[0-9]+.*")
    assert len(results) >= 1
    assert any("2024" in r['file_name'] for r in results)

def test_empty_query(db):
    """Query vacía: Devuelve todos los archivos"""
    results = db.search_by_name("")
    # Tenemos 6 archivos en test_data
    assert len(results) == 6

# --- TESTS FASE 2: FUZZY SEARCH ---

def test_fuzzy_typo(db):
    """Fuzzy typo: Encuentra Matrix buscando 'Matirx' (distancia 2)"""
    results = db.search_by_name("Matirx")
    assert len(results) >= 1
    assert "Matrix" in (results[0]['official_title'] or results[0]['file_name'])

def test_fuzzy_word_in_long_title(db):
    """Fuzzy por palabra: Encuentra 'Puñales por la espalda' buscando 'Punnñales' (con typo)"""
    # Antes esto fallaba porque 'Punnñales' (10) no es similar en longitud a 'Puñales por la espalda' (22) y el filtro de longitud lo descartaba.
    results = db.search_by_name("Punnñales")
    assert len(results) >= 1
    assert "Puñales por la espalda" in results[0]['official_title']

# --- TESTS FASE 3: FILTROS ---

def test_filter_type(db):
    """Filtro tipo: Búsqueda filtrada por media_type"""
    results = db.search_by_name("type:movie Matrix")
    assert len(results) == 1
    assert results[0]['media_type'] == "movie"

def test_filter_score(db):
    """Filtro score: Búsqueda filtrada por puntuación"""
    results = db.search_by_name("score>8.5")
    # Matrix (8.7) e Inception (8.8)
    assert len(results) == 2
    for r in results:
        assert r['score'] > 8.5
