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
    "info": {".nfo", ".sfv", ".md5", ".sha1"} # Información y Verificación de la Escena
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

# Etiquetas de P2P comunes a eliminar (Categorización, Códics, Calidades, Release Groups (ripeos), ...)
SCENE_TAGS = [
    # Calidades y Formatos
    r"hdrip", r"web-?dl", r"web-?rip", r"bluray", r"brrip", r"bdrip", r"dvdrip", r"dvd-?scr",
    r"remux", r"hybrid", r"bdmux", r"telesync", r"ts", r"cam", r"hdcam", r"hdts", r"hdtv",
    r"proper", r"repack", r"rerip", r"internal", r"remastered", r"uncut", r"unrated", r"uncensored",
    r"imax", r"criterion", r"anniversary", r"extended", r"directors?.?cut", r"special.?edition",
    r"theatrical", r"3d", r"sbs", r"half-?ou", r"half-?sbs", r"open.?matte", r"cc", r"v\.?o\.?s\.?",
    
    # Códecs y Tecnología
    r"x264", r"x265", r"x266", r"hevc", r"h264", r"h265", r"h266", r"xvid", r"divx",
    r"aac", r"ac3", r"e-ac3", r"dts", r"dts-?hd", r"truehd", r"atmos", r"8ch", r"6ch",
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
    
    # Grupos Españoles y eMule (Scene ES)
    r"proteinicos", r"emulesonic", r"divxtotal", r"hispashare", r"elitetorrent",
    r"exploradoresp2p", r"rodosky", r"mck", r"juanito", r"djt", r"punky", r"rodos",
    r"pax", r"abril", r"alies", r"ett", r"donkey", r"mule", r"olimp", r"btdx8",
    r"p73", r"armor", r"mokona", r"bone", r"bkk", r"micro", r"getb", r"istance",
    r"toy", r"foracrew", r"nahom", r"cnzoo", r"swtyblz", r"davide29", r"rodosky",
    r"mmtraxx", r"syncup", r"juanito",
    
    # Metadatos de Audio/Tech adicionales
    r"kbps", r"320", r"192", r"128", r"vbr", r"cbr", r"ytshorts", r"savetube",
    r"h\s*264", r"h\s*265", r"5\s*1", r"7\s*1", r"runneo", r"ddp", r"dd\+"
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

    # === REGEX ===

    # 1. Limpieza de dominios web (Buscamos esto ANTES de quitar los puntos)
    # ej: Pelicula.com -> Pelicula
    clean_name = re.sub(r'(?i)\b\w+\.(me|es|com|net|org|io|tv|info|mx|to|li|tw|re|be|yt|us)\b', ' ', base_name)

    # 2. Sustitución de separadores comunes por espacios.
    clean_name = re.sub(r'[\._]', ' ', clean_name)
    
    # === NORMALIZACIÓN INICIAL ===
    # Separar números de letras (ej: h265Español -> h265 Español)
    # Esto es CRÍTICO para que las regex posteriores (\b) funcionen con tags pegados.
    clean_name = re.sub(r'([a-zA-ZáéíóúüñÁÉÍÓÚÜÑ])(\d)', r'\1 \2', clean_name)
    clean_name = re.sub(r'(\d)([a-zA-ZáéíóúüñÁÉÍÓÚÜÑ])', r'\1 \2', clean_name)
    
    # Extraer año (Buscamos 19xx o 20xx)
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', clean_name)

    if year_match:
        result["year"] = int(year_match.group(1))
        # Reemplazamos el año del título
        clean_name = clean_name.replace(year_match.group(0), " ")
        

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
            # Si el tag es una resolución conocida (según tus facetas de BDD), la guardamos en resolution
            if re.match(r'\d{3,4}p|4k|uhd|2k', val):
                result["resolution"] = val
            clean_name = clean_name.replace(q_match.group(0), " ")
            break
            
    # Eliminar resto de basura de Scene Tags
    for tag in SCENE_TAGS:
        clean_name = re.sub(r'(?i)\b' + tag + r'\b', ' ', clean_name)

    # Eliminar la firma del uploader (como "by mDudikoff" o "-GrpName")
    clean_name = re.sub(r'(?i)\bby\s+[\w]+\b', '', clean_name)
    # Mejorada para capturar grupos al final (ej: -GETB8 o -GETB 8) sin romper títulos con guion
    clean_name = re.sub(r'-\s*[a-zA-Z0-9]+(\s*\d{1,2})?$', '', clean_name)
    
    # Limpiar prefijos inútiles al inicio (ej: FILM -, __, [DIVE - ITA])
    clean_name = re.sub(r'(?i)^(film|video|movie|audio|documentary)\s*-\s*', '', clean_name)
    
    # Extraer resoluciones ANTES de borrarlas (ej: 1920x1080)
    res_matches = re.findall(r'(?i)\b\d{3,4}\s*x\s*\d{3,4}\b', clean_name)
    if res_matches:
        # Usamos set() para evitar duplicados y normalizamos quitando espacios (ej: 1920 x 1080 -> 1920x1080)
        res_clean = [r.lower().replace(" ", "") for r in res_matches]
        result["resolution"] = ", ".join(sorted(set(res_clean)))
    clean_name = re.sub(r'(?i)\b\d{3,4}\s*x\s*\d{3,4}\b', ' ', clean_name)

    # === EXTRACCIÓN Y NORMALIZACIÓN DE IDIOMAS ===
    
    # Generamos un patrón dinámico con todas las claves de nuestro mapa de idiomas
    lang_pattern = r'\b(' + '|'.join(re.escape(k) for k in LANGUAGE_MAP.keys()) + r')\b'
    
    # 1. Buscamos combinaciones (ej: ESP-ENG) o idiomas sueltos (ej: Latino, Spanish)
    # También buscamos códigos prefijados con + (ej: +ES)
    found_langs = re.findall(r'(?i)\b(?:[a-z]{2,10}[-+\/&])+[a-z]{2,10}\b', clean_name)
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
            # Guardamos códigos únicos y ordenados (ej: EN-ES)
            result["languages"] = "-".join(sorted(list(set(valid_codes))))

    # === EXTRACCIÓN DE SUBTÍTULOS (VOSE, VOS, SUBS, HC) ===
    # Buscamos patrones de subtítulos (incluyendo V O S con espacios y HCSubs)
    sub_pattern = r'(?i)\b(v\s*o\s*s\s*e|v\s*\.\s*o\s*\.\s*s\s*\.\s*e\s*\.?|v\s*\.\s*o\s*\.\s*s\s*\.?|v\s*o\s*s|subs?|subtitles?|hc-?subs?)\b'
    sub_matches = re.findall(sub_pattern, clean_name)
    
    if sub_matches:
        subs_found = []
        for sm in sub_matches:
            sm_clean = sm.lower().replace(".", "").replace(" ", "").replace("-", "")
            if "vose" in sm_clean:
                subs_found.append("ES")
            elif "vos" in sm_clean:
                subs_found.append("Original")
            elif "hc" in sm_clean:
                subs_found.append("Hardcoded")
            else:
                subs_found.append("Yes")
        
        if subs_found:
            result["subtitles"] = "/".join(sorted(set(subs_found)))

    # Limpieza de rastros de idiomas y subtítulos en el título
    clean_name = re.sub(r'(?i)\b([a-z]{2,10}[-+\/&])+[a-z]{2,10}\b', ' ', clean_name)
    clean_name = re.sub(r'(?i)\b(\+[a-z]{2,10})\b', ' ', clean_name)
    clean_name = re.sub(r'(?i)\b(subs?&\w+)\b', ' ', clean_name)
    clean_name = re.sub(sub_pattern, ' ', clean_name)
    clean_name = re.sub(r'(?i)\b(hq)\b', ' ', clean_name) # Limpiamos HQ específicamente

    # Limpieza inteligente de paréntesis y corchetes:
    # 1. Quitar contenido de paréntesis o corchetes si parece una lista o metadata (contiene comas o espacios)
    clean_name = re.sub(r'[\(\[][^\]\)]*,[^\]\)]*[\)\]]', ' ', clean_name)
    # 2. Quitar tags de idioma pegados tipo "Spanishsub"
    clean_name = re.sub(r'(?i)\b\w+sub\b', ' ', clean_name)
    # 3. Quitar solo los símbolos para el resto, preservando el texto (títulos duales)
    clean_name = re.sub(r'[\[\]\(\)]', ' ', clean_name)
    
    # Quitar palabras técnicas y extensiones falsas (Lista extendida y más agresiva)
    clean_name = re.sub(r'(?i)\b(audio|subs?|torrent|mkv|avi|mp4|bluray|bd|br|hdr|hevc|web-?dl|web-?rip|bd-?rip|micro|10b|atticusF|bone|mokona|braemen|yts|yolow|rarbg|cyber|olimpo|hmr|djt|wrs|kvm|lucy|yg|mogli\d*|premiere|proper|advanced|good|quality|fant|various|artists|motion|picture|soundtrack|original|vip|hdlatino|ac3|aac\d*|av1|xvid|ld-aac|ld|md|allsubs|multisubs|multisub|multisubtitulos|v2|repack|adv|hdts|runneo|sharethefiles|cinecalidad)\b', ' ', clean_name)
    
    # Quitar códecs con puntos o espacios (ej: H.264, DD5.1, DD5 1)
    clean_name = re.sub(r'(?i)\b(h[\.\s]?264|x[\.\s]?264|h[\.\s]?265|x[\.\s]?265|dd[\.\s]?5[\.\s]?1|ac3|dts|aac|av1|xvid|ld-aac)\b', ' ', clean_name)

    # Quitar palabras de idiomas (solo las largas o técnicas) usando el mapa dinámico
    # Filtramos el mapa para NO incluir códigos de 2 letras (evita colisiones con "en", "es"), 
    # pero SÍ incluimos los de 3 letras (SPA, ENG, ITA) que son seguros.
    lang_clean_list = [k for k in LANGUAGE_MAP.keys() if len(k) > 2]
    lang_clean_pattern = '|'.join(re.escape(k) for k in lang_clean_list)
    clean_name = re.sub(r'(?i)\b(' + lang_clean_pattern + r'|subs?|sub|dual|vose|multi|v\.o\.s\.?|v\.o\.s\.e\.?)\b', ' ', clean_name)

    # Limpieza de etiquetas de calidad pegadas y tipos de ripeo de cine
    clean_name = re.sub(r'(?i)\b(bd|br|web|hd)1080p\b', ' ', clean_name)
    clean_name = re.sub(r'(?i)\b(telesync|ts|tc|hdts|hc-ts|hcsubs|camrip|cam|ld|md)\b', ' ', clean_name)


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
    
    # 1. Eliminar cualquier palabra de 1 o 2 letras que haya quedado suelta al final (típicos restos de tags)
    clean_name = re.sub(r'\s+[a-zA-Z0-9]{1,2}$', '', clean_name)

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

        # Penalizamos si quedan guiones huérfanos, caracteres raros o el título es muy corto
        has_noise = re.search(r'[+&/]', clean_name)

        # Si el título termina en guion o tiene guiones vacios, bajamos confianza
        is_clean = not has_noise and "." not in clean_name and " - -" not in clean_name
        
        if len(clean_name) > 5 and is_clean:
            result["confidence"] = "high"
        else:
            result["confidence"] = "low"
        
    if result["media_type"] in ["book", "software", "audio"]:
        result["confidence"] = "high"
        
    return result
