import re
from pathlib import Path

# Diccionarios y Listas constantes para limpieza y categorización:

# Mapeo de extensiones a Media Type
EXTENSION_MAPPING = { 
    "video": {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".mpg", ".mpeg", ".m4v", ".ts", ".m2ts", ".ogm", ".divx", ".vob"}, # Vídeos/Películas/Series
    "book": {".pdf", ".epub", ".mobi", ".djvu", ".cbz", ".cbr", ".azw3", ".fb2", ".azw"}, # Libros/Ebooks/Cómics
    "software": {".exe", ".msi", ".bat", ".cmd", ".com", ".reg", ".lnk", ".jar", ".hta", ".cpl", ".vbs", ".ps1", ".scr", ".xlsm", ".xlsb", ".docm", ".pptm", ".doc", ".xls", ".ppt", ".one", ".iqy", ".slk", ".dmg", ".pkg", ".apk", ".deb", ".rpm", ".appx"}, # Ejecutables e Instaladores
    "compressed": {".rar", ".zip", ".7z", ".iso", ".bin", ".cue", ".tar.gz", ".tgz", ".bz2", ".xz", ".lzma"}, # Archivos comprimidos
    "subtitles": {".srt", ".vtt", ".sub", ".ass", ".ssa", ".lrc"}, # Subtítulos
    "audio": {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".aac", ".opus", ".wma", ".m4b", ".ape", ".mpc", ".wv"}, # Audio/Música
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".raw", ".svg", ".ico"}, # Imágenes
    "documents": {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf", ".odt", ".ods", ".odp"}, # Documentos
    "info": {".nfo", ".sfv", ".md5", ".sha1", ".emulecollection", ".torrent"} # Información, Colecciones y Metadatos P2P
}

# Mapa de normalización de idiomas (Alias -> Código Estándar)
LANGUAGE_MAP = {
    "SPANISH": "ES", "ESPAÑOL": "ES", "ESP": "ES", "SPA": "ES", "LATINO": "ES", "CASTELLANO": "ES", "SP": "ES",
    "ENGLISH": "EN", "ENG": "EN", "INGLES": "EN", "INGLÉS": "EN", "EN": "EN",
    "ITALIAN": "IT", "ITALIANO": "IT", "ITA": "IT", "IT": "IT",
    "GERMAN": "DE", "DEUT": "DE", "GER": "DE", "DE": "DE",
    "FRENCH": "FR", "FRE": "FR", "FRA": "FR", "FR": "FR",
    "RUSSIAN": "RU", "RUS": "RU",
    "PORTUGUESE": "PT",
    "CHINESE": "ZH", "CHI": "ZH",
    "JAPANESE": "JP", "JAP": "JP"
}

# Etiquetas de P2P comunes a eliminar (Categorización, Códecs, Calidades, Release Groups (ripeos), ...)
SCENE_TAGS = [
    # Calidades y Formatos
    r"hdrip", r"web-?dl", r"web-?rip", r"bluray", r"brrip", r"bdrip", r"dvdrip", r"dvd-?scr",
    r"remux", r"hybrid", r"bdmux", r"telesync", r"ts", r"cam", r"hdcam", r"hd-?ts", r"hdtv",
    r"proper", r"repack", r"rerip", r"internal", r"remaster(ed)?", r"v-?a", r"no-?ads?", r"uncut", r"unrated", r"uncensored",
    r"imax", r"criterion", r"anniversary", r"extended", r"directors?.?cut", r"special.?edition",
    r"theatrical", r"3d", r"sbs", r"half-?ou", r"half-?sbs", r"open.?matte", r"cc", r"v\.?o\.?s\.?",
    
    # Códecs y Tecnología
    r"x264", r"x265", r"x266", r"hevc", r"h264", r"h265", r"h266", r"xvid", r"divx",
    r"aac\d*", r"ac3", r"e-ac3", r"dts", r"dts-?hd", r"truehd", r"atmos", r"8ch", r"6ch",
    r"10bit", r"hi10p", r"hdr", r"hdr10", r"dolby.?vision", r"dv", r"dovi", r"hlg", r"pq", r"sdr",
    
    # Resoluciones
    r"2160p", r"1080p", r"720p", r"480p", r"576p", r"4k", r"uhd", r"2k", r"hd",
    
    # Idiomas y Subtítulos
    r"multi", r"dual", r"vostfr", r"subita", r"subesp", r"subfrench", r"spanishsub", r"englishsub",
    
    # Grupos Internacionales (Scene & P2P)
    r"yify", r"yts", r"rarbg", r"psa", r"qxr", r"tigole", r"vyndros", r"evo", r"cyber",
    r"yolow", r"sparks", r"geckos", r"drones", r"amiable", r"framestor", r"flux", r"ntb",
    r"epsilon", r"don", r"hallowed", r"bhdstudio", r"ctrlhd", r"ebp", r"victor", r"kings",
    r"tommy", r"flights", r"phoenix", r"cmrg", r"ntg", r"sic", r"thefarm", r"xepa",
    r"amiable", r"rovers", r"strife", r"deflate", r"inflate", r"hdtim", r"hds", r"wiki",
    r"amiable", r"megusta", r"skytrooper", r"juggs", r"fgt", r"rarbg", r"yts",
    r"utp", r"pahe", r"joy", r"galaxyrg", r"tgx", r"pix", r"ana-axis",
    r"asap", r"lol", r"dimension", r"tue", r"eth",
    
    # Grupos Españoles y eMule (Scene ES)
    r"proteinicos", r"emulesonic", r"divxtotal", r"hispashare", r"elitetorrent",
    r"exploradoresp2p", r"rodosky", r"mck", r"juanito", r"djt", r"punky", r"rodos",
    r"pax", r"abril", r"alies", r"ett", r"donkey", r"mule", r"olimp", r"btdx8",
    r"p73", r"armor", r"mokona", r"bone", r"bkk", r"micro", r"getb", r"istance",
    r"toy", r"foracrew", r"nahom", r"cnzoo", r"swtyblz", r"davide29", r"rodosky",
    r"mmtraxx", r"syncup", r"juanito", r"animelliure", r"frozen-layer", r"animersion",
    r"espa-mule", r"esp-mule", r"crg", r"llsw", r"unioncosplay", r"vampire", r"valhalla",
    r"gran-torrent", r"mejordivx", r"morpheus", r"pgm", r"mks", r"pctfenix", r"newpct",
    r"hd-spain", r"pixelados", r"emulepedia", r"p2p-spain", r"divx",
    
    # Metadatos de Audio/Tech adicionales y Ruido de Uploader
    r"kbps", r"320", r"192", r"128", r"vbr", r"cbr", r"ytshorts", r"savetube",
    r"h\s*26[4-6]", r"x\s*26[4-6]", r"5\s*1", r"7\s*1", r"runneo", r"ddp?", r"dd\+", r"dovi", r"hdr\s*10",
    r"no-?logo-?ads?", r"no-?ads?", r"ads?",
    r"by\.?[a-zA-Z0-9_-]+", r"rip\.?[a-zA-Z0-9_-]+", r"sub\.?[a-zA-Z0-9_-]+",
    r"www\.[a-zA-Z0-9_-]+\.[a-z]{2,3}", r"[a-zA-Z0-9_-]+\.(com|net|org|me|li|la|io|tv|cc|pw)"
]

# hdrip = High Definition Rip
# web-dl = Web Download
# x264 = H.264 codec
# x265 = H.265 codec
# hevc = High Efficiency Video Coding
# aac = Advanced Audio Coding
# ac3 = Dolby Digital
# e-ac3 = Enhanced Dolby Digital
# bluray = Blu-ray Disc
# brrip = Blu-ray Rip
# proper = Proper Rip
# repack = Repack
# webrip = Web Rip
# dvdrip = DVD Rip
# xvid = Xvid codec
# divx = DivX codec
# 10b = 10-bit
# hdr = High Dynamic Range
# ts = TeleSync
# cam = Camcorder (Grabación con cámara)
# bdrip = Blu-ray Disc Rip

# Etiquetas de calidad de video
QUALITY_TAGS = [r"4\s*k", r"2160\s*p", r"1080\s*p", r"720\s*p", r"480\s*p", r"1080\s*i", r"uhd"]

def fix_mojibake(text: str) -> str:
    """Intenta reparar errores de codificación comunes (Mojibake)."""
    if not text:
        return text
    try:
        # El patrón típico de eMule: UTF-8 leído como Latin-1
        # Solo lo intentamos si detectamos caracteres sospechosos
        if any(c in text for c in "Ã Ã± Ã¡ Ã© Ã­ Ã³ Ãº"):
            return text.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    
    # Si falla, simplemente eliminamos caracteres de control no imprimibles
    return "".join(c for c in text if c.isprintable())

def parse_filename(filename: str) -> dict:

    """
    Intenta limpiar y extraer toda la información del nombre del archivo usando parseo estructurado y Regex.
    Es el paso inicial de la "Capa 1" del pipeline.
    """
    
    # 0. Reparar codificación antes de empezar
    filename = fix_mojibake(filename)
    
    # 1. Obtenemos extensión real.
    # Si el nombre NO tiene punto al final o es una carpeta, el suffix de Path puede ser engañoso.
    path_obj = Path(filename)
    
    # Solo consideramos extensión si el archivo realmente tiene un tipo conocido al final
    raw_ext = path_obj.suffix.lower()
    extension = ""
    base_name = filename

    # Verificamos si la extensión es válida buscando en nuestro mapeo
    for exts in EXTENSION_MAPPING.values():
        if raw_ext in exts:
            extension = raw_ext
            base_name = path_obj.stem
            break

    # Mapear media_type
    media_type = "unknown"
    for m_type, exts in EXTENSION_MAPPING.items():
        if extension in exts:
            media_type = m_type
            break
            

    # Datos por defecto
    result = {
        "title": base_name,
        "author": "",
        "year": None, 
        "season": None,
        "episode": None,
        "quality": None,
        "resolution": "",
        "languages": "",
        "subtitles": "",
        "media_type": media_type,
        "extension": extension,
        "confidence": "low"
    }

    # === LIMPIEZA PREVIA DE METADATOS TÉCNICOS (IDs y Versiones) ===
    # Lo hacemos ANTES de tocar puntos o guiones para que el Regex sea efectivo (ej: r1.0)
    # Solo eliminamos tags técnicos aislados, NO listas de metadatos (eso va al final)
    
    # Quitar contenido si solo son números de IDs (evitando años de 4 cifras) o etiquetas de versión
    # ej: [14611] -> vacio, (r1.0) -> vacio, pero (2024) se mantiene para el extractor de años
    base_name = re.sub(r'[\(\[]\s*(\d{1,3}|\d{5,}|r\d+(\.\d+)?|v\d+(\.\d+)?|rev\d+)\s*[\)\]]', ' ', base_name, flags=re.IGNORECASE)

    # === REGEX ===

    # 1. Limpieza de dominios web (Buscamos esto ANTES de quitar los puntos)
    # Solo limpiamos si empieza por www. o si está entre paréntesis/corchetes (ruido típico)
    # ej: www.Pelicula.com -> Pelicula, (emulesonic.com) -> vacio
    clean_name = re.sub(r'(?i)\bwww\.[a-z0-9-]+\.(me|es|com|net|org|io|tv|info|mx|to|li|tw|re|be|yt|us)\b', ' ', base_name)
    clean_name = re.sub(r'(?i)[\(\[][^\]\)]*\.(me|es|com|net|org|io|tv|info|mx|to|li|tw|re|be|yt|us)[\)\]]', ' ', clean_name)

    # 2. Sustitución de separadores comunes por espacios.
    clean_name = re.sub(r'[\._]', ' ', clean_name)

    # 3. Separación de letras y números (ej: h264Español -> h264 Español)
    # Refinado para NO romper títulos con leetspeak (como "Se7en" o "Thir13en")
    # Solo separamos si el número es grande (3+ cifras como años/resoluciones) o si empieza por prefijos técnicos (h, x, s, e)
    clean_name = re.sub(r'(?i)([a-záéíóúüñ])(\d{3,4})', r'\1 \2', clean_name)
    clean_name = re.sub(r'(?i)(\d{3,4})([a-záéíóúüñ])', r'\1 \2', clean_name)
    clean_name = re.sub(r'(?i)\b([hxse])(\d+)\b', r'\1 \2', clean_name)

    # Extraer año (Buscamos 19xx o 20xx)
    # Buscamos TODOS los candidatos y seleccionamos el más probable (el último que no sea resolución)
    year_candidates = list(re.finditer(r'\b(19\d{2}|20\d{2})\b', clean_name))
    valid_year_match = None
    
    for match in reversed(year_candidates):
        # Verificamos que no sea parte de una resolución (ej: 1920 x 1080)
        # Solo rechazamos si la 'x' está rodeada de dígitos cerca del match
        start, end = match.span()
        context = clean_name[max(0, start-5):end+5].lower()
        if re.search(r'\d+\s*x\s*\d+', context):
            continue # Parte de una resolución
            
        valid_year_match = match
        break

    if valid_year_match:
        potential_year = int(valid_year_match.group(1))
        start, end = valid_year_match.span()
        temp_name = clean_name[:start] + " " + clean_name[end:]
        
        if temp_name.strip():
            result["year"] = potential_year
            clean_name = temp_name
        else:
            # Si el título queda vacío, el "año" era el título (ej: 1917.mkv)
            pass

    # Extraer temporada y episodio. Patrones como S01E03, 1x03, Season 1 Episode 3... 
    s_e_match = re.search(r's\s*(\d{1,2})\s*e\s*(\d{1,2})', clean_name, re.IGNORECASE)

    if not s_e_match:
        s_e_match = re.search(r'(?i)\b(\d{1,2})\s*x\s*(\d{1,2})\b', clean_name)
    
    if s_e_match:
        result["season"] = int(s_e_match.group(1))
        result["episode"] = int(s_e_match.group(2))
        clean_name = clean_name.replace(s_e_match.group(0), " ") 
        
    # Extraer Calidad de vídeo y Resolución (720p, 1080p, 4K...)
    for q_tag in QUALITY_TAGS:
        q_match = re.search(r'\b' + q_tag + r'\b', clean_name, re.IGNORECASE)
        if q_match:
            val = q_match.group(0).lower().replace(" ", "")
            result["quality"] = val
            # Solo guardamos en 'resolution' si NO tenemos una resolución real ya detectada
            if re.match(r'\d{3,4}p|4k|uhd|2k', val) and not result.get("resolution"):
                result["resolution"] = val
            clean_name = clean_name.replace(q_match.group(0), " ")
            break
            
    # === EXTRACCIÓN Y NORMALIZACIÓN DE IDIOMAS ===
    # Lo hacemos ANTES de la limpieza de tags para evitar que el ruido rompa bloques multilingües
    
    # Generamos un patrón dinámico con todas las claves de nuestro mapa de idiomas
    lang_pattern = r'\b(' + '|'.join(re.escape(k) for k in LANGUAGE_MAP.keys()) + r')\b'
    
    # 1. Buscamos combinaciones (ej: ESP-ENG) o idiomas sueltos (ej: Latino, Spanish)
    # También buscamos códigos prefijados con + (ej: +ES)
    found_langs = re.findall(r'(?i)\b(?:[a-z]{2,3}[-+\/&])+[a-z]{2,3}\b', clean_name)
    found_langs += re.findall(r'(?i)' + lang_pattern, clean_name)
    found_langs += re.findall(r'(?i)\b\+([a-z]{2,10})\b', clean_name)

    if found_langs:
        valid_codes = []
        # Lista de palabras técnicas que NO pueden ser idiomas (para evitar falsos positivos como WEB-DL)
        technical_blacklist = {"WEB", "DL", "RIP", "BD", "BR", "HD", "TS", "TC", "MD", "HC", "V2", "PROPER", "REPACK"}

        for match in found_langs:
            # Si el match es una combinación (ej: ES-EN), la dividimos
            parts = re.split(r'[-+\/&]', match) if any(c in match for c in "-+/&") else [match]
            
            for p in parts:
                p_clean = p.upper().strip()
                
                # REGLA: Si la palabra está en la lista negra técnica, la ignoramos como idioma
                if p_clean in technical_blacklist:
                    continue

                # Normalizamos usando el mapa
                if p_clean in LANGUAGE_MAP:
                    valid_codes.append(LANGUAGE_MAP[p_clean])
                elif len(p_clean) == 2 and p_clean.isalpha() and p_clean != "BY":
                    # Aceptamos códigos de 2 letras si no son palabras comunes como "BY"
                    valid_codes.append(p_clean)
        
        if valid_codes:
            result["languages"] = "-".join(sorted(set(valid_codes)))

    # Detectar subtítulos (ej: Sub Spanish, Subs Eng, VOS)
    sub_pattern = r'(?i)\b(vost?f?|vos[as]?|subs?|subtitles|v\.o\.s\.)\s*([a-z]{2,10})?\b'
    sub_matches = re.findall(sub_pattern, clean_name)
    if sub_matches:
        subs_found = []
        for m in sub_matches:
            if m[1]: # Si hay un idioma capturado después de "subs"
                lang_code = m[1].upper()
                if lang_code in LANGUAGE_MAP:
                    subs_found.append(LANGUAGE_MAP[lang_code])
                else:
                    subs_found.append(lang_code)
            else:
                subs_found.append("YES")
        if subs_found:
            result["subtitles"] = "/".join(sorted(set(subs_found)))

    # === LIMPIEZA DE TAGS Y RUIDO ===

    # Eliminar resto de basura de Scene Tags
    for tag in SCENE_TAGS:
        clean_name = re.sub(r'(?i)\b' + tag + r'\b', ' ', clean_name)

    # Eliminar la firma del uploader (como "by mDudikoff", "by.ana-axis", "by-Group")
    clean_name = re.sub(r'(?i)\bby[\s\.-]+[a-z0-9_-]+\b', ' ', clean_name)
    
    # Limpieza de grupo al final (solo si hay un guion claro antes del grupo, para evitar borrar palabras del título)
    clean_name = re.sub(r'-\s*[a-zA-Z0-9_-]+(\s*\d{1,4})?$', ' ', clean_name)
    
    # Limpiar prefijos inútiles al inicio (ej: FILM -, __, [DIVE - ITA])
    clean_name = re.sub(r'(?i)^(film|video|movie|audio|documentary)\s*-\s*', '', clean_name)
    
    # Extraer resoluciones ANTES de borrarlas (ej: 1920x1080)
    res_matches = re.findall(r'(?i)\b\d{3,4}\s*x\s*\d{3,4}\b', clean_name)
    if res_matches:
        # Usamos set() para evitar duplicados y normalizamos quitando espacios (ej: 1920 x 1080 -> 1920x1080)
        res_clean = [r.lower().replace(" ", "") for r in res_matches]
        result["resolution"] = ", ".join(sorted(set(res_clean)))
    clean_name = re.sub(r'(?i)\b\d{3,4}\s*x\s*\d{3,4}\b', ' ', clean_name)

    # Limpieza de rastros de idiomas y subtítulos en el título (basado en lo extraído antes)
    clean_name = re.sub(r'(?i)\b([a-z]{2,3}[-+\/&])+[a-z]{2,3}\b', ' ', clean_name)
    clean_name = re.sub(r'(?i)\b(\+[a-z]{2,10})\b', ' ', clean_name)
    clean_name = re.sub(r'(?i)\b(subs?&\w+)\b', ' ', clean_name)
    if 'sub_pattern' in locals():
        clean_name = re.sub(sub_pattern, ' ', clean_name)
    
    # Limpiar lo que haya quedado de los mapas de idiomas
    # REGLA DE ORO: Solo borramos palabras LARGAS (>2 letras) o combinaciones.
    # No borramos códigos de 2 letras sueltos para evitar colisiones con preposiciones (DE, EN).
    lang_clean_list = [k for k in LANGUAGE_MAP.keys() if len(k) > 2]
    lang_clean_pattern = r'(?i)\b(' + '|'.join(re.escape(k) for k in lang_clean_list) + r')\b'
    clean_name = re.sub(lang_clean_pattern, ' ', clean_name)

    clean_name = re.sub(r'(?i)\b(hq)\b', ' ', clean_name) # Limpiamos HQ específicamente

    # Quitar contenido de paréntesis o corchetes si parece una lista o metadata (contiene comas o espacios)
    # Lo hacemos al final porque el año ya ha sido extraído y borrado de clean_name.
    clean_name = re.sub(r'[\(\[][^\]\)]*,[^\]\)]*[\)\]]', ' ', clean_name)

    # Quitar tags de idioma pegados tipo "Spanishsub"
    clean_name = re.sub(r'(?i)\b\w+sub\b', ' ', clean_name)
    # Quitar solo los símbolos residuales para el resto, preservando el texto (títulos duales)
    clean_name = re.sub(r'[\[\]\(\)]', ' ', clean_name)
    
    # Quitar palabras técnicas, grupos de ripeo y extensiones falsas
    
    # Agrupamos en una lista para evitar una regex monolítica ilegible
    tech_keywords = [
        r"audio", r"subs?", r"torrent", r"mkv", r"avi", r"mp4", r"bluray", r"bd", r"br", r"hdr", r"hevc",
        r"web-?dl", r"web-?rip", r"bd-?rip", r"micro", r"10b", r"yts", r"yolow", r"rarbg", r"cyber",
        r"olimpo", r"hmr", r"djt", r"wrs", r"kvm", r"lucy", r"yg", r"mogli\d*", r"premiere", r"proper",
        r"advanced", r"good", r"quality", r"fant", r"various", r"artists", r"motion", r"picture",
        r"soundtrack", r"original", r"vip", r"hdlatino", r"ac3", r"aac\d*", r"av1", r"xvid", r"ld-aac",
        r"ld", r"md", r"allsubs", r"multisubs", r"multisub", r"multisubtitulos", r"v2", r"repack",
        r"adv", r"hdts", r"runneo", r"sharethefiles", r"cinecalidad", r"atticusF", r"bone", r"mokona", r"braemen",
        r"no-?logo-?ads?", r"no-?ads?", r"ads?"
    ]
    tech_pattern = r'(?i)\b(' + '|'.join(tech_keywords) + r')\b'
    clean_name = re.sub(tech_pattern, ' ', clean_name)
    
    # Quitar códecs con puntos o espacios (ej: H.264, DD5.1, DD5 1)
    codec_list = [
        r"[hx][.\s]?26[456]", r"dd[.\s]?5[.\s]?1", r"dd[.\s]?plus",
        r"ac3", r"dts", r"aac\d*", r"av1", r"xvid", r"ld-aac"
    ]
    codec_pattern = r'(?i)\b(' + '|'.join(codec_list) + r')\b'
    clean_name = re.sub(codec_pattern, ' ', clean_name)

    # Quitar palabras de idiomas (solo las largas o técnicas) usando el mapa dinámico
    # Filtramos el mapa para NO incluir códigos de 2 letras (evita colisiones con "en", "es"), 
    # pero SÍ incluimos los de 3 letras (SPA, ENG, ITA) que son seguros.
    lang_clean_list = [k for k in LANGUAGE_MAP.keys() if len(k) > 2]
    lang_clean_list += ["subs?", "sub", "dual", "vose", "multi", r"v\.o\.s\.?e?\.?"]
    lang_clean_pattern = r'(?i)\b(' + '|'.join(re.escape(k) if "\\" not in k else k for k in lang_clean_list) + r')\b'
    clean_name = re.sub(lang_clean_pattern, ' ', clean_name)

    # Limpieza de etiquetas de calidad pegadas y tipos de ripeo de cine
    clean_name = re.sub(r'(?i)\b(bd|br|web|hd)1080p\b', ' ', clean_name)
    rip_list = ["telesync", "ts", "tc", "hdts", "hc-?ts", "hcsubs", "camrip", "cam", "ld", "md"]
    rip_pattern = r'(?i)\b(' + '|'.join(rip_list) + r')\b'
    clean_name = re.sub(rip_pattern, ' ', clean_name)


    # Eliminar puntuación residual pero PRESERVANDO apóstrofes internos para contracciones (He's, Don't)
    # Primero quitamos puntuación de los bordes de las palabras
    clean_name = re.sub(r'(?<![a-zA-Z])\'|\'(?![a-zA-Z])', '', clean_name)
    # Luego quitamos otros símbolos molestos excepto el apóstrofe y el guion
    # Preservamos caracteres españoles áéíóúüñÁÉÍÓÚÜÑ
    clean_name = re.sub(r'[^a-zA-Z0-9\'áéíóúüñÁÉÍÓÚÜÑ\- ]', ' ', clean_name)

    # Eliminar caracteres no-latinos "basura" al principio y al final
    clean_name = re.sub(r'^[^a-zA-Z0-9(]+', '', clean_name)
    clean_name = re.sub(r'[^a-zA-Z0-9)]+$', '', clean_name)

    # === FASE FINAL: Normalización de "Cicatrices" ===
    
    # 1. Eliminar cualquier residuo de 1 o 2 letras sueltas al final que NO sea un número
    # (ej: "Pelicula by", "Pelicula - de") -> Pero preservar "Terminator 2"
    clean_name = re.sub(r'\s+[a-zA-Z]{1,2}$', '', clean_name)

    # 2. Convertir múltiples espacios o guiones en uno solo (de forma separada para no romper " - ")
    clean_name = re.sub(r'\s{2,}', ' ', clean_name)
    clean_name = re.sub(r'-{2,}', '-', clean_name)
    
    # 3. Eliminar guiones o puntos que hayan quedado volando al principio o final
    clean_name = clean_name.strip(' .-')

    # 4. Eliminar "cicatrices" de guiones dobles en medio (ej: "Titulo - - Subtitulo")
    clean_name = clean_name.replace('- -', '-')
    clean_name = re.sub(r'\s+-\s*$', '', clean_name) # Guion huérfano al final
    
    # 5. Si después de todo queda vacío, devolvemos el original
    if not clean_name.strip():
        clean_name = base_name

    # === EXTRACCIÓN DE AUTOR (Para Libros y Música) ===
    # Patrón común en P2P: "Autor - Titulo"
    if media_type in ["book", "audio"] and " - " in clean_name:
        parts = clean_name.split(" - ", 1)
        result["author"] = parts[0].strip()
        result["title"] = parts[1].strip()
    else:
        result["title"] = clean_name.strip()

    # --- DETERMINACIÓN DE CONFIANZA ---

    # Solo confiamos si tenemos año/temporada Y el título está MUY limpio
    if (result["year"] or result["season"]):

        # Penalizamos si quedan guiones huérfanos, caracteres raros, etiquetas de audio (DD) o números residuales
        has_noise = re.search(r'[+&/]', clean_name)
        # Si quedan etiquetas como "DD" o "SM" que son ruido típico
        has_tag_noise = re.search(r'(?i)\b(dd|sm|atmos|dovi|hdr|ts|tc|cam|rip)\b', clean_name)
        
        # Si quedan números sospechosos al final (más de 2 dígitos que no son el año)
        # O si queda un SOLO dígito al final tras un guion o espacio (típico residuo de 5.1 o similar)
        has_residual_numbers = re.search(r'\s\d{2,}\s*$', clean_name) or re.search(r'[\s-]\d\s*$', clean_name)

        # Si el título termina en guion o tiene guiones vacios, bajamos confianza
        is_clean = not has_noise and not has_tag_noise and not has_residual_numbers and "." not in clean_name and " - -" not in clean_name
        
        if len(clean_name) > 5 and is_clean:
            result["confidence"] = "high"
        else:
            result["confidence"] = "low"
        
    if result["media_type"] in ["book", "software", "audio", "info", "subtitles"]:
        result["confidence"] = "high"
        
    return result
