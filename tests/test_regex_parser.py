"""
TEST SUITE: MOTOR DE EXTRACCIÓN Y LIMPIEZA REGEX (METADATA PRECISION)

Este suite (GOLDEN SET) valida la inteligencia del motor de parsing de SmartMule, encargado de 
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
    assert res["author"] == "01"
    assert res["title"] == "Bohemian Rhapsody"
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

def test_parse_knives_out_variants():
    """
    Casos extremos basados en las variantes de archivo encontradas en eMule de la película de 2019 'Knives Out'.
    Verifica títulos multilingües, listas de actores en el nombre y tags de audio complejos.
    """
    
    # 1. Caso con actores y tags de audio pegados
    # [DivX - ITA] - Cena con delitto - Knives out (con Daniel Craig, Chris Evans...) 2019 1.mp4
    case1 = "[DivX - ITA] - Cena con delitto - Knives out (con Daniel Craig, Chris Evans, Ana De Armas, Jamie Lee Curtis, Michael Shannon, Don Johnson) 2019 1.mp4"
    res1 = parse_filename(case1)
    assert "Cena con delitto" in res1["title"]
    assert res1["year"] == 2019
    assert "IT" in res1["languages"]

    # 2. Caso con traducción española y tags de subs complejos
    # Knives Out (2019. Rian Johnson)(Puñales por la espalda). (Spanish.English.Subs).BDRip. 1080p.x264-AC3.mkv
    case2 = "Knives Out (2019. Rian Johnson)(Puñales por la espalda). (Spanish.English.Subs).BDRip. 1080p.x264-AC3.mkv"
    res2 = parse_filename(case2)
    assert res2["year"] == 2019
    assert res2["quality"] == "1080p"
    assert "ES" in res2["languages"]

    # 3. Caso con dominios y tags de audio 5.1/6ch
    # Cena con delitto - Knives Out [2019,Rian Johnson,Daniel Craig, Chris Evans, Ana de Armas,x265,1080p,DTS,6ch].mkv
    case3 = "Cena con delitto - Knives Out [2019,Rian Johnson,Daniel Craig, Chris Evans, Ana de Armas,x265,1080p,DTS,6ch].mkv"
    res3 = parse_filename(case3)
    assert "Cena con delitto" in res3["title"]
    assert res3["year"] == 2019
    assert res3["quality"] == "1080p"

    # 4. Caso con guiones y tags de audio específicos (Audio ENG - Subs DUT ENG)
    # Knives Out (2019) - 1080p - 1920x1080 -Audio ENG - Subs DUT ENG.mkv
    case4 = "Knives Out (2019) - 1080p - 1920x1080 -Audio ENG - Subs DUT ENG.mkv"
    res4 = parse_filename(case4)
    assert "Knives Out" in res4["title"]
    assert "EN" in res4["languages"]
    assert res4["resolution"] == "1920x1080"

    # 5. Caso con dominios en el nombre
    # Knives.Out.2019.720p.BluRay.x264-YOLOW.[sharethefiles.com].mkv
    case5 = "Knives.Out.2019.720p.BluRay.x264-YOLOW.[sharethefiles.com].mkv"
    res5 = parse_filename(case5)
    assert "sharethefiles.com" not in res5["title"]

def test_parse_super_extreme_variants():
    """
    Casos 'Super Extreme' basados en la segunda imagen.
    Años al inicio, caracteres chinos, cicatrices de guiones bajos y tags de calidad antiguos.
    """

    # 1. Caso con año al principio y múltiples idiomas (EN-SP-IT-FR-GER)
    case1 = "2019 Knives Out - Puñales por la espalda-Cena con delitto.EN-SP-IT-FR-GER.mkv"
    res1 = parse_filename(case1)
    assert "Knives Out" in res1["title"]
    assert res1["year"] == 2019
    assert "ES" in res1["languages"] # Detectado por 'SP' o 'Puñales'

    # 2. Caso con caracteres chinos y calidad 2160p x265 10bit
    # [利刃出鞘].Knives.Out.2019.BluRay.2160p.TrueHD.7.1.Atmos.x265.10bit.HEVC-CNZOO.mkv
    case2 = "[利刃出鞘].Knives.Out.2019.BluRay.2160p.TrueHD.7.1.Atmos.x265.10bit.HEVC-CNZOO.mkv"
    res2 = parse_filename(case2)
    assert "Knives Out" in res2["title"]
    assert res2["year"] == 2019
    assert res2["quality"] == "2160p"

    # 3. Caso con cicatrices de inicio (guiones bajos) y calidad HDCAM
    # __Knives Out 2019 720p HDCAM-GETB8.mkv
    case3 = "__Knives Out 2019 720p HDCAM-GETB8.mkv"
    res3 = parse_filename(case3)
    assert res3["title"] == "Knives Out"
    assert res3["year"] == 2019
    assert res3["quality"] == "720p"

    # 4. Caso con calidad MD.CAM (Muy común en eMule antiguo)
    # Cena.Con.Delitto.Knives.Out.2019.iTALiAN.MD.CAM.XviD-iSTANCE.avi
    case4 = "Cena.Con.Delitto.Knives.Out.2019.iTALiAN.MD.CAM.XviD-iSTANCE.avi"
    res4 = parse_filename(case4)
    assert "Cena Con Delitto" in res4["title"]
    assert res4["year"] == 2019
    assert "IT" in res4["languages"]

    # 5. Caso con prefijo "FILM -" y director en el nombre
    # FILM - Cena Con Delitto - Knives Out - di Rian Johnson - 2019.iTA.AC3.BrRip.x264.Toy-FoRaCReW.mkv
    case5 = "FILM - Cena Con Delitto - Knives Out - di Rian Johnson - 2019.iTA.AC3.BrRip.x264.Toy-FoRaCReW.mkv"
    res5 = parse_filename(case5)
    assert "Cena Con Delitto" in res5["title"]
    assert res5["year"] == 2019

def test_parse_hail_mary_variants():
    """
    Casos de 'Project Hail Mary' (Proyecto Salvación).
    Publicidad, calidades híbridas y metadatos de autor.
    """

    # 1. Caso con publicidad, calidad GOOD QUALITY y V.O.S.
    # Project Hail Mary (Proyecto Salvación 2026) 1080p GOOD QUALITY (V.O.S. Spa-Eng) - Spanish subs integrados by JuAnItO.mkv
    case1 = "Project Hail Mary (Proyecto Salvación 2026) 1080p GOOD QUALITY (V.O.S. Spa-Eng) - Spanish subs integrados by JuAnItO.mkv"
    res1 = parse_filename(case1)
    assert "Project Hail Mary" in res1["title"]
    assert res1["year"] == 2026
    assert res1["quality"] == "1080p"
    assert "ES" in res1["languages"]

    # 2. Caso con calidad HC-TS (Hard-Coded Telesync) y grupo 'pilongo'
    # Proyecto Fin del Mundo (Proyecto Salvación) (Project Hail Mary) (2026)[1080p HC-TS](Latino. Audio)(pilongo).mkv
    case2 = "Proyecto Fin del Mundo (Proyecto Salvación) (Project Hail Mary) (2026)[1080p HC-TS](Latino. Audio)(pilongo).mkv"
    res2 = parse_filename(case2)
    assert "Project Hail Mary" in res2["title"]
    assert res2["year"] == 2026

    # 3. Caso con publicidad No-Logo-ADS y grupo MmTRaXx
    # L.Ultima.Missione. (Project.Hail.Mary). 2026. 1080p. x265. No-Logo-ADS. MD-DDP5. 1. ITA. ReMaster. MmTRaXx.mkv
    case3 = "L.Ultima.Missione. (Project.Hail.Mary). 2026. 1080p. x265. No-Logo-ADS. MD-DDP5. 1. ITA. ReMaster. MmTRaXx.mkv"
    res3 = parse_filename(case3)
    assert "Project Hail Mary" in res3["title"]
    assert "ADS" not in res3["title"]
    assert "MmTRaXx" not in res3["title"]

    # 4. Caso de libro con autor al principio
    # Andy Weir - Project Hail Mary (Mondadori 2023-02).epub
    case4 = "Andy Weir - Project Hail Mary (Mondadori 2023-02).epub"
    res4 = parse_filename(case4)
    # Ahora el autor se separa del título para la BDD
    assert res4["author"] == "Andy Weir"
    assert "Project Hail Mary" in res4["title"]
    assert res4["year"] == 2023

def test_parse_nolan_variants():
    """
    Casos de la suite de Christopher Nolan.
    Títulos duales, directores con preposiciones y dominios clásicos de eMule.
    """

    # 1. Caso con año al principio entre paréntesis y tags italianos
    # (2020) Tenet [Christopher Nolan] (John David Washington, Robert Pattinson) (Spanish.English.Spanishsub).BDrip. 1080p.x264-AC3.mkv
    case1 = "(2020) Tenet [Christopher Nolan] (John David Washington, Robert Pattinson) (Spanish.English.Spanishsub).BDrip. 1080p.x264-AC3.mkv"
    res1 = parse_filename(case1)
    # Christopher Nolan se mantiene en el título
    assert "Tenet" in res1["title"]
    assert "Christopher Nolan" in res1["title"]
    assert res1["year"] == 2020
    assert res1["quality"] == "1080p"

    # 2. Caso con título dual y múltiples puntos/comas
    # Origen.-.Inception. (Christopher.Nolan,, 2010). (Spanish.English.Subs).BDrip. 1080p.HEVC. 10b-AC3.by.mck.mkv
    case2 = "Origen.-.Inception. (Christopher.Nolan,, 2010). (Spanish.English.Subs).BDrip. 1080p.HEVC. 10b-AC3.by.mck.mkv"
    res2 = parse_filename(case2)
    assert "Origen" in res2["title"]
    assert "Inception" in res2["title"]
    assert res2["year"] == 2010

    # 3. Caso con dominio clásico español (proteinicos.es)
    # Insomnio.[Insomnia].(Christopher Nolan.2002).(Spanish.English).HDrip.XviD-AC3.by.rodosky.(proteinicos.es).avi
    case3 = "Insomnio.[Insomnia].(Christopher Nolan.2002).(Spanish.English).HDrip.XviD-AC3.by.rodosky.(proteinicos.es).avi"
    res3 = parse_filename(case3)
    assert "Insomnio" in res3["title"]
    assert "Insomnia" in res3["title"]
    assert "proteinicos" not in res3["title"]

    # 4. Caso con director 'di Christopher Nolan' y género 'Fantascienza'
    # Interstellar (2014) di Christopher Nolan con Matthew McConaughey, Anne Hathaway, Jessica Chastain) Ita-Fantascienza.avi
    case4 = "Interstellar (2014) di Christopher Nolan con Matthew McConaughey, Anne Hathaway, Jessica Chastain) Ita-Fantascienza.avi"
    res4 = parse_filename(case4)
    assert "Interstellar" in res4["title"]
    assert "Fantascienza" not in res4["title"]
    assert res4["year"] == 2014

def test_parse_fight_club_axis_case():
    """
    Caso real detectado donde el ruido de uploader '-axis' y el dominio 'emulesonic.com' confundían a la API inicial.
    """
    filename = "El.club.de.la.lucha.(Fight.club).(David.Fincher,.1999).(Spanish.English.Subs).BDrip.1080p.x265-AC3.by.ana-axis.(emulesonic.com).mkv"
    res = parse_filename(filename)
    
    # El título debe estar limpio de grupos y dominios
    assert "El club de la lucha" in res["title"]
    assert "Fight club" in res["title"]
    assert "axis" not in res["title"]
    assert "emulesonic" not in res["title"]
    assert "by" not in res["title"]
    assert res["year"] == 1999
    assert res["quality"] == "1080p"

def test_parse_weird_titles():
    """
    Test de 'Casos Raros' (Weird Titles).
    Títulos que son solo números, leetspeak, títulos extremadamente largos o con delimitadores complejos.
    """

    # 1. Títulos que parecen años (Confusión con Year)
    case1 = "1917.2019.1080p.BluRay.x264.mkv"
    res1 = parse_filename(case1)
    assert "1917" in res1["title"]
    assert res1["year"] == 2019

    case2 = "2012.2009.720p.BluRay.mkv"
    res2 = parse_filename(case2)
    assert "2012" in res2["title"]
    assert res2["year"] == 2009

    # 2. Leetspeak (Números integrados en palabras)
    case3 = "Se7en.1995.BDRip.x264.mkv"
    res3 = parse_filename(case3)
    assert "Se7en" in res3["title"]
    assert res3["year"] == 1995

    case4 = "Thir13en.Ghosts.2001.720p.mkv"
    res4 = parse_filename(case4)
    assert "Thir13en Ghosts" in res4["title"]
    assert res4["year"] == 2001

    # 3. Títulos con números al principio y en medio
    case5 = "2.Fast.2.Furious.2003.1080p.mkv"
    res5 = parse_filename(case5)
    assert "2 Fast 2 Furious" in res5["title"]

    # 4. Títulos con delimitadores de puntos/guiones que son parte del título
    case6 = "4.3.2.1.2010.1080p.mkv"
    res6 = parse_filename(case6)
    assert "4 3 2 1" in res6["title"]

    case7 = "3-10.to.Yuma.2007.720p.mkv"
    res7 = parse_filename(case7)
    assert "3-10 to Yuma" in res7["title"]

    # 5. Título extremadamente largo
    long_title = "Night of the Day of the Dawn of the Son of the Bride of the Return of the Revenge of the Terror of the Attack of the Evil, Mutant, Hellbound, Flesh-Eating Subhumanoid Zombified Living Dead, Part 2"
    case8 = f"{long_title} (1991).mkv"
    res8 = parse_filename(case8)
    # Verificamos que no se haya truncado agresivamente
    assert "Night of the Day" in res8["title"]
    assert "Zombified Living Dead" in res8["title"]
    assert res8["year"] == 1991

    # 6. Título con fracciones/números raros
    case9 = "8.1.2.Federico.Fellini.1963.720p.mkv"
    res9 = parse_filename(case9)
    assert "8 1 2" in res9["title"]
    assert "Federico Fellini" in res9["title"]
