import pytest
from datetime import datetime
from smartmule.database import HashDatabase

@pytest.fixture
def db_advanced(tmp_path):
    """Base de datos con casos reales de Knives Out para pruebas avanzadas."""
    db_file = tmp_path / "test_advanced_search.db"
    db = HashDatabase(db_file)
    
    # Nombres de archivos basados en tests/test_regex_parser.py
    test_data = [
        {
            "file_name": "[DivX - ITA] - Cena con delitto - Knives out (con Daniel Craig) 2019 1.mp4",
            "official_title": "Cena con delitto",
            "media_type": "movie",
            "resolution": "720p",
            "score": 7.9,
            "verdict": "SAFE",
            "organized": 1
        },
        {
            "file_name": "Knives Out (2019)(Puñales por la espalda). (Spanish.English.Subs).BDRip. 1080p.mkv",
            "official_title": "Puñales por la espalda",
            "media_type": "movie",
            "resolution": "1080p",
            "score": 7.8,
            "verdict": "SAFE",
            "organized": 0
        },
        {
            "file_name": "Knives Out Original Soundtrack.mp3",
            "official_title": "Knives Out OST",
            "media_type": "audio",
            "resolution": None,
            "score": 8.5,
            "verdict": "SAFE",
            "organized": 1
        },
        {
            "file_name": "The.Great.Gatsby.epub",
            "official_title": "The Great Gatsby",
            "media_type": "book",
            "resolution": None,
            "score": 9.0,
            "verdict": "SAFE",
            "organized": 0
        }
    ]
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for item in test_data:
        db._conn.execute(
            """INSERT INTO files (
                file_path, file_name, official_title, media_type, score, 
                resolution, security_verdict, is_organized, file_size, 
                ed2k_hash, ed2k_link, processed_at, duration
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"path/{item['file_name']}", item['file_name'], item['official_title'], 
                item['media_type'], item['score'], item['resolution'], 
                item['verdict'], item['organized'], 1024, 
                f"hash_{item['file_name']}", f"link_{item['file_name']}", now, 0
            )
        )
    
    # Sincronizamos FTS5
    db._conn.execute("INSERT INTO files_fts(rowid, file_name, official_title) SELECT id, file_name, official_title FROM files")
    db._conn.commit()
    
    yield db
    db.close()

def test_search_or_logic(db_advanced):
    """Prueba que type:movie type:audio devuelva ambos (OR)"""
    results = db_advanced.search_by_name("type:movie type:audio")
    # Debería encontrar 2 películas y 1 audio = 3 resultados
    assert len(results) == 3
    types = [r['media_type'] for r in results]
    assert "movie" in types
    assert "audio" in types
    assert "book" not in types

def test_search_partial_like(db_advanced):
    """Prueba que type:mov encuentre movie (LIKE)"""
    results = db_advanced.search_by_name("type:mov")
    assert len(results) == 2
    assert all(r['media_type'] == "movie" for r in results)

def test_search_verdict_partial(db_advanced):
    """Prueba que verdict:saf encuentre SAFE (LIKE)"""
    results = db_advanced.search_by_name("verdict:saf")
    assert len(results) == 4 # Todos son SAFE en este set

def test_search_organized_flexible(db_advanced):
    """Prueba variaciones de organized: y, 1, true"""
    # Usando 'y'
    res_y = db_advanced.search_by_name("organized:y")
    assert len(res_y) == 2 # La primera película y el audio
    
    # Usando '1'
    res_1 = db_advanced.search_by_name("organized:1")
    assert len(res_1) == 2
    
    # Usando 'no'
    res_no = db_advanced.search_by_name("organized:no")
    assert len(res_no) == 2 # La segunda película y el libro

def test_search_added_today(db_advanced):
    """Prueba el filtro temporal added:today"""
    results = db_advanced.search_by_name("added:today")
    assert len(results) == 4 # Todos han sido insertados 'hoy' en el fixture

def test_search_complex_mix(db_advanced):
    """Mezcla de texto libre y filtros avanzados"""
    # Buscar "Puñales" que sea película y segura
    results = db_advanced.search_by_name("Puñales type:movie verdict:safe")
    assert len(results) == 1
    assert "Puñales" in results[0]['official_title']
    assert results[0]['resolution'] == "1080p"
