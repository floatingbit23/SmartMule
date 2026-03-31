import pytest
from unittest.mock import patch, MagicMock
from smartmule.parsers.media_inspector import inspect_media_file
import json

def test_inspect_media_file_success():
    """
    Simula una respuesta exitosa de ffprobe para verificar que el parseo de JSON
    y el cálculo de minutos funciona correctamente.
    """
    mock_ffprobe_output = {
        "format": {
            "duration": "7200.5" # 2 horas y media
        },
        "streams": [
            {
                "width": 1920,
                "height": 1080
            }
        ]
    }

    # Mock de Path.exists y subprocess.check_output
    with patch("smartmule.parsers.media_inspector.Path.exists", return_value=True):
        with patch("subprocess.check_output") as mock_run:
            mock_run.return_value = json.dumps(mock_ffprobe_output).encode("utf-8")
            
            result = inspect_media_file("fake_peli.mkv")
            
            assert result["is_media"] is True
            assert result["duration_sec"] == 7200
            assert result["width"] == 1920
            assert result["height"] == 1080

def test_inspect_media_file_no_duration():
    """
    Verifica el comportamiento si ffprobe devuelve JSON pero sin duración 
    (ej: un archivo corrupto o binario que no es media).
    """
    mock_ffprobe_output = {"format": {}, "streams": []}
    
    with patch("smartmule.parsers.media_inspector.Path.exists", return_value=True):
        with patch("subprocess.check_output") as mock_run:
            mock_run.return_value = json.dumps(mock_ffprobe_output).encode("utf-8")
            
            result = inspect_media_file("not_a_movie.exe")
            
            assert result["is_media"] is False
            assert result["duration_sec"] == 0

def test_inspect_media_file_error():
    """
    Verifica que si ffprobe falla (ej: No instalado o comando inválido),
    el programa no explote y devuelva el diccionario por defecto.
    """
    with patch("subprocess.check_output", side_effect=Exception("ffprobe not found")):
        result = inspect_media_file("problematic.mp4")
        
        assert result["is_media"] is False
        assert result["duration_sec"] == 0
