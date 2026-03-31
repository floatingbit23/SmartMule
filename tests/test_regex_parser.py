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
