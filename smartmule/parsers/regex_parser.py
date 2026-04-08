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

# Etiquetas de P2P comunes a eliminar (Códecs, Calidades, Release Groups (ripeos), ...)
SCENE_TAGS = [
    r"hdrip", r"web-dl", r"x264", r"x265", r"hevc", r"aac", r"ac3", r"e-ac3",
    r"bluray", r"brrip", r"proper", r"repack", r"webrip", r"dvdrip", r"xvid",
    r"yify", r"rarbg", r"xrg", r"vpp", r"ion10", r"psa", r"qxr", r"sparks", 
    r"geckos", r"drones", r"amiable", r"divx", r"10b", r"hdr", r"ts", r"cam", r"bdrip",
    # Audio Tags
    r"kbps", r"320", r"192", r"128", r"vbr", r"cbr", r"ytshorts", r"savetube",
    # Additional Technical Tags
    r"h264", r"5\s*1", r"7\s*1", r"dts", r"10bit", r"multi"
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
QUALITY_TAGS = [r"4k", r"2160p", r"1080p", r"720p", r"480p", r"1080i", r"uhd"]

# uhd = Ultra High Definition


def parse_filename(filename: str) -> dict:

    """
    Intenta limpiar y extraer toda la información del nombre del archivo usando parseo estructurado y Regex.
    Es el paso inicial de la "Capa 1" del pipeline.
    """
    
    # 1. Obtenemos extensión real (Convertimos a Path temporal para manejar esto).
    path_obj = Path(filename) 
    extension = path_obj.suffix.lower() 
    base_name = path_obj.stem # Sin extensión

    # Ejemplo: filename = "The.Matrix.1999.1080p.BluRay.x264-SPARKS.mkv"
    # extension = ".mkv"
    # base_name = "The.Matrix.1999.1080p.BluRay.x264-SPARKS"

    # Mapear media_type
    media_type = "unknown"

    # Recorremos el diccionario EXTENSION_MAPPING
    for m_type, exts in EXTENSION_MAPPING.items():
        if extension in exts: # Si la extensión está en el diccionario
            media_type = m_type # Asignamos el tipo de medio
            break # Salimos del bucle
            

    # Datos por defecto
    result = {
        "title": base_name, # 
        "year": None, 
        "season": None,
        "episode": None,
        "quality": None,
        "media_type": media_type,
        "extension": extension,
        "confidence": "low" # Confianza baja por defecto
    }

    # === REGEX ===

    # Sustitución de separadores comunes por espacios.
    clean_name = re.sub(r'[\._]', ' ', base_name)
    
    # Extraer año
    year_match = re.search(r'\(?(19\d{2}|20\d{2})\)?', clean_name)

    if year_match:
        result["year"] = int(year_match.group(1))
        # Reemplazamos el año del título
        clean_name = clean_name.replace(year_match.group(0), " ")
        

    # Extraer temporada y episodio. Patrones como S01E03, 1x03, Season 1 Episode 3... 
    # S01E03
    s_e_match = re.search(r's(\d{1,2})e(\d{1,2})', clean_name, re.IGNORECASE)

    if not s_e_match:
        # Capta patrón 1x03
        s_e_match = re.search(r'(?i)\b(\d{1,2})x(\d{1,2})\b', clean_name)
    
    if s_e_match:
        result["season"] = int(s_e_match.group(1))
        result["episode"] = int(s_e_match.group(2))
        clean_name = clean_name.replace(s_e_match.group(0), " ") 
        
    # Extraer Calidad de vídeo
    for q_tag in QUALITY_TAGS:
        q_match = re.search(r'\b' + q_tag + r'\b', clean_name, re.IGNORECASE)

        if q_match:
            result["quality"] = q_match.group(0).lower()
            clean_name = clean_name.replace(q_match.group(0), " ")
            break
            
    # Eliminar resto de basura de Scene Tags
    for tag in SCENE_TAGS:
        clean_name = re.sub(r'(?i)\b' + tag + r'\b', ' ', clean_name)

    # Eliminar la firma del uploader (como "by mDudikoff" o "-GrpName")
    clean_name = re.sub(r'(?i)\bby\s+[\w\d-]+\b', '', clean_name)
    clean_name = re.sub(r'-\s*\w+$', '', clean_name)
    
    # Eliminar paréntesis y corchetes que queden solos o tengan extras
    clean_name = re.sub(r'[\[\]\(\)]', ' ', clean_name)
    
    # Quitar palabras como "Spanish", "English", "Subs", "Dual"
    clean_name = re.sub(r'(?i)\b(spanish|spa|eng|english|subs|sub|dual|ita|iTALiAN|ita|fre|latino|castellano)\b', ' ', clean_name)

    # Limpieza de dominios web (ej: savetube.me, viciao.es, etc.)
    clean_name = re.sub(r'(?i)\b\w+\.(me|es|com|net|org|io|me|tv|info)\b', ' ', clean_name)

    # Limpieza de resoluciones (ej: 1920x1080, 1280x720)
    clean_name = re.sub(r'(?i)\b\d{3,4}x\d{3,4}\b', ' ', clean_name)

    # Limpieza final de espacios duplicados y trim
    clean_name = re.sub(r'\s+', ' ', clean_name).strip()
    
    # Si tras la reducción el string ha perdido todo sentido ("") o ha quitado de más 
    # (por ejemplo "1" de "Matrix 1" fue tomado como algo raro aunque no deberia),
    if not clean_name:
        clean_name = base_name  # Fallback: nos rendimos, la IA deberá arreglarlo

    result["title"] = clean_name

    # Determinación heurística de LA CONFIANZA.
    # Si logramos extraer el nombre y hay año o es temporada clara, confiamos MUCHO.
    if result["year"] is not None or (result["season"] is not None):
        result["confidence"] = "high"
        
    # Los libros, audios, software o archivos comprimidos suelen ser limpios directamente o los tratamos directamente:
    if result["media_type"] in ["book", "software", "audio", "compressed"]:
        result["confidence"] = "high"
        
    return result
