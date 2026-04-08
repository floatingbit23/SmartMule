"""
tests/test_incomplete_downloads.py — Tests para el manejo de archivos y directorios incompletos.

Verifica que el sistema ignore correctamente las descargas en curso (eMule/Torrent) 
y no procese directorios que contengan archivos temporales.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from smartmule.watcher import IncomingHandler
from smartmule.hasher import get_main_file_in_dir
from smartmule.queue_manager import QueueManager
from smartmule.metadata_engine import MetadataEngine
from smartmule.config import IGNORED_EXTENSIONS

@pytest.fixture
def mock_queue_manager():
    return MagicMock(spec=QueueManager)

@pytest.fixture
def handler(mock_queue_manager):
    return IncomingHandler(mock_queue_manager)

def test_is_extension_ignored(handler):
    """Prueba que el helper de extensiones detecte tanto simples como compuestas."""
    assert handler._is_extension_ignored(Path("video.mp4.!ut")) is True
    assert handler._is_extension_ignored(Path("data.part.met.bak")) is True
    assert handler._is_extension_ignored(Path("peli.mkv")) is False
    assert handler._is_extension_ignored(Path("archivo.txt")) is False

def test_should_ignore_directory_with_temp_files(handler, tmp_path):
    """
    Verifica que una carpeta se ignore si contiene archivos temporales, 
    incluso si el nombre de la carpeta no tiene extensión prohibida.
    """
    # 1. Creamos una carpeta de descarga simulada
    torrent_dir = tmp_path / "Looper.2012.1080p"
    torrent_dir.mkdir()
    
    # 2. Añadimos un archivo temporal (como hace uTorrent)
    (torrent_dir / "looper.mp4.!ut").write_text("descarga parcial")
    
    # 3. Verificamos que _should_ignore devuelva True para LA CARPETA
    assert handler._should_ignore(torrent_dir) is True

def test_hasher_ignores_temp_files_in_directory(tmp_path):
    """
    Verifica que get_main_file_in_dir ignore los archivos temporales 
    al buscar el archivo 'representante'.
    """
    download_dir = tmp_path / "Release_Folder"
    download_dir.mkdir()
    
    # Archivo temporal grande (10MB)
    temp_file = download_dir / "movie.mp4.!ut"
    temp_file.write_bytes(b"0" * (10 * 1024 * 1024))
    
    # Archivo real pequeño (100KB)
    real_file = download_dir / "sample.mkv"
    real_file.write_bytes(b"V" * (100 * 1024))
    
    # Aunque el .!ut es más grande, get_main_file_in_dir debe elegir el .mkv
    main_file = get_main_file_in_dir(download_dir)
    assert main_file == real_file
    assert main_file.name == "sample.mkv"

def test_queue_manager_size_ignores_temp_files(tmp_path):
    """
    Verifica que el cálculo de tamaño total de una carpeta en el QueueManager
    omita los archivos con extensiones ignoradas.
    """
    with patch("smartmule.queue_manager.HashDatabase"), \
         patch("smartmule.queue_manager.MetadataEngine"), \
         patch("smartmule.queue_manager.LibraryOrganizer"), \
         patch("threading.Thread"):
        
        qm = QueueManager()
        
        # Omitimos la DB y el fingerprint porque ahora el check ocurre en el worker, no en encolar.
        # Lo que nos interesa es el tamaño calculado en la tarea encolada.
        
        download_dir = tmp_path / "Size_Test_Dir"
        download_dir.mkdir()
        
        # 10MB temporal + 5MB real
        f1 = download_dir / "large_temp.part"
        f1.write_bytes(b"T" * (10 * 1024 * 1024))
        f2 = download_dir / "real_video.mp4"
        f2.write_bytes(b"V" * (5 * 1024 * 1024))
        
        print(f"\nDEBUG: Calling enqueue for {download_dir}")
        qm.enqueue(download_dir)
        
        # Miramos qué hay en la cola
        assert qm.pending_count == 1
        task = qm._queue.get()
        
        print(f"DEBUG: Task size: {task.file_size}")
        
        # El tamaño esperado es solo el del video (5MB)
        assert task.file_size == 5 * 1024 * 1024
