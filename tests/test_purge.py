import pytest
import os
from pathlib import Path
from smartmule.database import HashDatabase

@pytest.fixture
def temp_db(tmp_path):
    """Crea una base de datos temporal para pruebas."""
    db_file = tmp_path / "test_purge.db"
    db = HashDatabase(db_file)
    yield db
    db.close()

@pytest.fixture
def mock_files(tmp_path):
    """Crea archivos de prueba en carpetas temporales."""
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    library.mkdir()
    
    f1 = incoming / "Matrix.mkv"
    f1.write_text("dummy")
    
    f2 = library / "The Matrix (1999).mkv"
    f2.write_text("dummy")
    
    return {
        "incoming": str(f1),
        "library": str(f2),
        "name": "Matrix.mkv"
    }

def test_search_by_name_literal(temp_db):
    """Prueba la búsqueda literal simple."""
    temp_db._conn.execute(
        "INSERT INTO hashes (file_path, file_name, file_size, ed2k_hash, ed2k_link, processed_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("path/to/Matrix.mkv", "Matrix.mkv", 100, "hash1", "link1", "2026-01-01")
    )
    
    results = temp_db.search_by_name("Matrix")
    assert len(results) == 1
    assert results[0]['file_name'] == "Matrix.mkv"

def test_search_by_wildcard(temp_db):
    """Prueba la búsqueda con comodines (*) estilo shell."""
    temp_db._conn.execute(
        "INSERT INTO hashes (file_path, file_name, file_size, ed2k_hash, ed2k_link, processed_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("path/to/Netfly.ps1", "Netfly.ps1", 100, "hash2", "link2", "2026-01-01")
    )
    
    # Caso 1: Empieza por N
    results = temp_db.search_by_name("N*")
    assert len(results) == 1
    
    # Caso 2: Termina en .ps1
    results = temp_db.search_by_name("*.ps1")
    assert len(results) == 1
    
    # Caso 3: No coincide
    results = temp_db.search_by_name("Z*")
    assert len(results) == 0

def test_search_by_regex(temp_db):
    """Prueba la búsqueda usando expresiones regulares puras."""
    temp_db._conn.execute(
        "INSERT INTO hashes (file_path, file_name, file_size, ed2k_hash, ed2k_link, processed_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("path/to/Foto_2024.jpg", "Foto_2024.jpg", 100, "hash3", "link3", "2026-01-01")
    )
    
    # Buscar archivos que contengan números
    results = temp_db.search_by_name(r".*[0-9]+.*")
    assert len(results) == 1
    assert "2024" in results[0]['file_name']

def test_delete_record(temp_db):
    """Prueba que el borrado de la base de datos funciona."""
    temp_db._conn.execute(
        "INSERT INTO hashes (id, file_path, file_name, file_size, ed2k_hash, ed2k_link, processed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (99, "path", "name", 10, "h", "l", "t")
    )
    
    temp_db.delete_by_id(99)
    results = temp_db.search_by_name("name")
    assert len(results) == 0
