"""
TEST SUITE: MOTOR DE EXTRACCIÓN Y LIMPIEZA REGEX (METADATA PRECISION)

Este suite valida la inteligencia del motor de parsing de SmartMule, encargado de 
convertir nombres de archivos "sucios" de redes P2P en metadatos limpios y estructurados.

1. Limpieza de Títulos (Noise Removal):
   - Objetivo: Extraer el nombre puro de la obra eliminando etiquetas técnicas y de grupo.
   - Verificación: Procesamiento de archivos con tags pegados (ej: h265Español), múltiples años, y ruidos de 'scene'.
   - Resultado esperado: Título normalizado ideal para búsquedas en APIs (TMDB/OpenLibrary).

2. Clasificación de Medios (Type Inference):
   - Objetivo: Determinar si el archivo es una película, serie, libro o software.
   - Verificación: Detección de patrones de series (ej: S01E01, 1x01...) y extensiones específicas.
   - Resultado esperado: Asignación correcta del 'media_type' y nivel de confianza.

3. Normalización de Idiomas y Calidad:
   - Objetivo: Identificar el idioma del audio y la resolución del vídeo.
   - Verificación: Mapeo dinámico de códigos de idioma (ES, EN, VOSE...) y tags de calidad (1080p, 4K...).
   - Resultado esperado: Población de los campos 'languages' y 'quality' del registro.
"""

import pytest
from smartmule.parsers.regex_parser import parse_filename

def test_parse_movie_simple():
    res = parse_filename("The.Matrix.1999.1080p.mkv")
    assert res["title"] == "The Matrix"
    assert res["year"] == 1999
    assert res["quality"] == "1080p"
    assert res["media_type"] == "video"
    assert res["extension"] == ".mkv"
    assert res["confidence"] == "high"

def test_parse_serie_standard():
    res = parse_filename("Breaking.Bad.S01E05.720p.WEB-DL.mkv")
    assert res["title"] == "Breaking Bad"
    assert res["season"] == 1
    assert res["episode"] == 5
    assert res["quality"] == "720p"
    assert res["confidence"] == "high"

def test_parse_serie_alternative():
    res = parse_filename("Friends 1x03 Spanish.avi")
    assert res["title"] == "Friends"
    assert int(res["season"]) == 1
    assert int(res["episode"]) == 3
    assert res["media_type"] == "video"

def test_parse_book():
    res = parse_filename("El_Señor_De_Los_Anillos.pdf")
    assert res["title"] == "El Señor De Los Anillos"
    assert res["media_type"] == "book"
    assert res["extension"] == ".pdf"
    assert res["confidence"] == "high"

def test_parse_audio():
    res = parse_filename("01 - Bohemian Rhapsody.mp3")
    assert res["title"] == "01 - Bohemian Rhapsody"
    assert res["media_type"] == "audio"
    assert res["confidence"] == "high"

def test_parse_trash_names():
    res = parse_filename("MyMovie.1080p.x265.HDRip.by.pepito.mp4")
    assert res["title"] == "MyMovie"
    assert res["quality"] == "1080p"
    assert res["media_type"] == "video"

def test_parse_unknown():
    res = parse_filename("Algo_rarisimo_sin_sentido")
    assert res["title"] == "Algo rarisimo sin sentido"
    assert res["confidence"] == "low"
    assert res["media_type"] == "unknown"

def test_parse_complex_with_stuck_tags():
    """
    Test crítico basado en el caso del archivo de la película Michael (2026).
    Verifica que la normalización separa 'h265Español' y extrae el título limpio.
    """
    filename = "Michael.2026.1080p.HDTS.h265Español.RuNNeo.mkv"
    res = parse_filename(filename)
    
    assert res["title"] == "Michael"
    assert res["year"] == 2026
    assert res["quality"] == "1080p"
    assert "ES" in res["languages"]
    assert res["confidence"] == "high"
