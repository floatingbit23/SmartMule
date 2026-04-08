"""
tests/test_directory_support.py — Tests de validación para el soporte de carpetas como unidad.

Verifica que el sistema maneje correctamente directorios en todas sus fases:
bloqueo, hashing e inspección técnica.
"""

import pytest
import shutil
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from smartmule.file_locker import is_file_locked
from smartmule.hasher import calculate_ed2k, calculate_fingerprint, get_main_file_in_dir
from smartmule.parsers.media_inspector import inspect_media_file

@pytest.fixture
def complex_dir(tmp_path):
    """Crea una estructura de carpeta de release típica."""
    release_dir = tmp_path / "Looper.2012.1080p"
    release_dir.mkdir()
    
    # Archivo pequeño (NFO)
    (release_dir / "info.nfo").write_text("Metadatos basura")
    
    # Archivo grande (Video representante) - 10MB para el test
    main_video = release_dir / "looper.mp4"
    main_video.write_bytes(b"V" * (10 * 1024 * 1024))
    
    # Subcarpeta con subtítulos
    subs_dir = release_dir / "Subs"
    subs_dir.mkdir()
    (subs_dir / "spanish.srt").write_text("Subtítulos")
    
    return release_dir

def test_is_file_locked_recursive(complex_dir):
    """Verifica que el locker detecte un archivo bloqueado dentro de una carpeta."""
    # En estado normal, la carpeta no está bloqueada
    assert is_file_locked(complex_dir) is False
    
    # Simulamos un bloqueo en el archivo de video (usando mock de open)
    # En lugar de un lock real, parcheamos la función responsable de detectar el fallo de apertura
    with patch("smartmule.file_locker.Path.is_file", side_effect=lambda: True):
        with patch("builtins.open", side_effect=PermissionError("File in use")):
            # Si intentamos abrir cualquier archivo y da PermissionError, la carpeta debe informar bloqueo
            assert is_file_locked(complex_dir) is True

def test_hasher_selects_largest_file(complex_dir):
    """Verifica que el hasher use el archivo de 10MB y no el .nfo."""
    # Obtenemos el hash esperado del video principal directamente
    main_video = complex_dir / "looper.mp4"
    expected_hash = calculate_ed2k(main_video)
    
    # El hash de la carpeta entera debe ser idéntico al del video principal
    folder_hash = calculate_ed2k(complex_dir)
    assert folder_hash == expected_hash
    assert folder_hash != ""

def test_fingerprint_selects_largest_file(complex_dir):
    """Verifica que el fingerprint se base en el video principal."""
    main_video = complex_dir / "looper.mp4"
    expected_fp = calculate_fingerprint(main_video, main_video.stat().st_size)
    
    # El fingerprint de la carpeta debe coincidir
    folder_fp = calculate_fingerprint(complex_dir, 0) # El tamaño se recalcula internamente
    assert folder_fp == expected_fp

def test_media_inspector_targets_main_file(complex_dir):
    """Verifica que ffprobe se ejecute sobre el mp4 y no sobre la carpeta."""
    mock_output = {
        "format": {"duration": "7200"},
        "streams": [{"width": 1920, "height": 1080}]
    }
    
    with patch("subprocess.check_output") as mock_run:
        mock_run.return_value = json.dumps(mock_output).encode("utf-8")
        
        result = inspect_media_file(str(complex_dir))
        
        # Verificamos que se llamó a ffprobe con la ruta del video, no de la carpeta
        args, kwargs = mock_run.call_args
        cmd_sent = args[0]
        assert str(complex_dir / "looper.mp4") in cmd_sent
        assert result["duration_sec"] == 7200

def test_metadata_engine_software_directory_targets_file(tmp_path):
    """Verifica que el triaje de VirusTotal apunte al .exe y no a la carpeta."""
    from smartmule.metadata_engine import MetadataEngine
    
    # Preparamos un motor de metadatos
    engine = MetadataEngine()
    
    # Carpeta limpia para Software
    software_dir = tmp_path / "Setup_Office"
    software_dir.mkdir()
    
    # Creamos un ejecutable
    exe_path = software_dir / "installer.exe"
    exe_path.write_bytes(b"MZ" + b"\x00" * 1024) 
    
    # Mockeamos el parser de IA/Regex para que devuelva tipo 'software'
    with patch("smartmule.metadata_engine.parse_filename", return_value={"title": "Test", "media_type": "software", "confidence": "high"}):
        with patch("smartmule.api.virustotal_client.VirusTotalClient.scan_software") as mock_vt:
            # Configuramos el mock para que devuelva un resultado válido
            mock_vt.return_value = {
                "stats": {"malicious": 0, "suspicious": 0},
                "results": {},
                "hash": "fakehash123"
            }
            
            engine.identify_file("Setup_Office", str(software_dir))
            
            # El punto clave: ¿Qué ruta recibió VirusTotal?
            args, _ = mock_vt.call_args
            target_used = args[0]
            
            assert target_used == str(exe_path)
            assert Path(target_used).is_file()
            assert target_used != str(software_dir)

def test_get_main_file_empty_dir(tmp_path):
    """Verifica el comportamiento con una carpeta vacía."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert get_main_file_in_dir(empty_dir) is None
