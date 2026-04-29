import zipfile # Es una librería que permite abrir archivos .zip
import patoolib # Es una librería que permite abrir archivos comprimidos de diferentes formatos
import logging
import contextlib 
from io import StringIO # Es una librería que permite capturar la salida de un programa
from pathlib import Path
from typing import Optional

logger = logging.getLogger("SmartMule.inspector") 

# Extensiones peligrosas
DANGEROUS_EXTS = {
    ".exe", ".msi", ".bat", ".cmd", ".vbs", ".js", ".ps1", 
    ".scr", ".pif", ".wsf", ".vbe", ".jse",
    ".reg", ".lnk", ".com", ".jar", ".hta", ".cpl",
    ".xlsm", ".xlsb", ".docm", ".pptm",
    ".doc", ".xls", ".ppt", ".one", ".iqy", ".slk"
}

# Mapeo de extensiones a Media Types
MEDIA_MAPPING = {
    ".mkv": "video", # Matroska Video
    ".mp4": "video", # MPEG-4 Part 14
    ".avi": "video", # Audio Video Interleave
    ".wmv": "video", # Windows Media Video
    ".mov": "video", # Apple QuickTime Movie
    ".mp3": "audio", # MPEG-1 Audio Layer III
    ".flac": "audio", # Free Lossless Audio Codec
    ".m4a": "audio", # MPEG-4 Audio
    ".wav": "audio", # Waveform Audio File Format
    ".pdf": "book", # Portable Document Format
    ".epub": "book", # Electronic Publication
    ".mobi": "book", # Mobipocket
    ".cbz": "book", # Comic Book Zip
    ".cbr": "book", # Comic Book Rar
    ".docx": "documents", # Microsoft Word Document (XML)
    ".xlsx": "documents", # Microsoft Excel Spreadsheet (XML)
    ".txt": "documents", # Text Document
    ".exe": "software", # Executable File
    ".msi": "software", # Microsoft Windows Installer
    ".bat": "software", # Batch File
    ".cmd": "software", # Command File
    ".reg": "software", # Registry File
    ".lnk": "software", # Link File
    ".com": "software", # Command File
    ".jar": "software", # Java Archive
    ".hta": "software", # HTML Application
    ".cpl": "software", # Control Panel Applet
    ".vbs": "software", # Visual Basic Script
    ".js": "software", # JavaScript File
    ".ps1": "software", # PowerShell Script
    ".scr": "software", # Screen Saver
    ".xlsm": "software", # Excel Macro-Enabled Spreadsheet
    ".xlsb": "software", # Excel Binary Workbook
    ".docm": "software", # Word Macro-Enabled Document
    ".pptm": "software", # PowerPoint Macro-Enabled Presentation
    ".doc": "software", # Microsoft Word Document
    ".xls": "software", # Microsoft Excel Spreadsheet
    ".ppt": "software", # Microsoft PowerPoint Presentation
    ".one": "software", # Microsoft OneNote Notebook
    ".iqy": "software", # Internet Query File
    ".slk": "software" # SYLK (Symbolic Link) File
}

# Aplicamos el principio de Responsabilidad Única (Single Responsibility Principle)
# Separamos la lógica de extracción de la lógica de análisis

# Separamos la logica de extraccion en funciones individuales (ZIP nativo vs otros formatos (RAR, 7Z, etc.))

def _list_zip(filepath: str) -> list[str]:
    """Extrae la lista de archivos de un ZIP. Lanza PermissionError si está cifrado."""
    file_list = []
    with zipfile.ZipFile(filepath, 'r') as z:
        for zinfo in z.infolist():
            # El bit 0 del flag indica cifrado en el estándar ZIP
            if zinfo.flag_bits & 0x1:
                raise PermissionError("ZIP cifrado")
            file_list.append(zinfo.filename)
    return file_list


def _list_generic(filepath: str) -> list[str]:
    """Usa patool para listar archivos de otros formatos (.rar, .7z, etc)."""
    output_buffer = StringIO()
    # patool imprime a stdout, así que lo capturamos
    with contextlib.redirect_stdout(output_buffer):
        patoolib.list_archive(filepath)
    return output_buffer.getvalue().splitlines()


def _analyze_file_list(file_list: list[str]) -> tuple[Optional[str], list[str]]:

    """Identifica el tipo de medio principal y detecta archivos potencialmente peligrosos."""

    detected_media = None
    dangerous_files = []
    
    for fname in file_list:
        fname_lower = fname.lower().strip()
        
        # 1. Comprobamos si es una extensión peligrosa
        if any(fname_lower.endswith(dext) for dext in DANGEROUS_EXTS):
            dangerous_files.append(fname)
            
        # 2. Identificamos el medio (video, audio, etc) solo si no tenemos uno ya
        if not detected_media:
            for mext, mtype in MEDIA_MAPPING.items():
                if fname_lower.endswith(mext):
                    detected_media = mtype
                    break
                    
    return detected_media, dangerous_files


# Contiene exclusivamente las reglas de negocio para determinar si un archivo es MALICIOUS, SUSPICIOUS o SAFE.
def _calculate_verdict(path_name: str, expected_type: str, detected_media: Optional[str], 
                       dangerous_files: list, file_list: list) -> dict:

    """Aplica la lógica de seguridad y devuelve el veredicto final."""

    has_dangerous = len(dangerous_files) > 0
    
    # 1. CASO CRÍTICO: Suplantación (Ejecutables donde no debería haberlos)
    if has_dangerous and expected_type not in ["software", "games"]:
        logger.critical(f"💀 [Inspector] ¡SUPLANTACIÓN! {path_name} (esperado {expected_type}) contiene ejecutables.")
        return {"status": "MALICIOUS", "detected_media": "software", "representative": dangerous_files[0]}

    # 2. CASO CRÍTICO: Malware en documentos
    if has_dangerous and expected_type == "documents":
        logger.critical("💀 [Inspector] ¡MALWARE! Documento contenedor de scripts detectado.")
        return {"status": "MALICIOUS", "detected_media": "software"}

    # 3. CASO INFORMATIVO: Software legítimo
    if has_dangerous:
        logger.info(f"✅ [Inspector] Ejecutables en contenedor de {expected_type}. Permitido por contexto.")
    else:
        logger.info(f"✅ [Inspector] Contenedor limpio. Contiene {len(file_list)} elementos.")

    if detected_media:
        logger.info(f"📼 [Inspector] Detectado contenido principal de tipo: {detected_media}")
    else:
        logger.warning("⚠️ [Inspector] No se detectó contenido multimedia válido en el contenedor.")

    # Seleccionamos un archivo representativo para el usuario (priorizando peligrosos para visibilidad)
    representative = None
    if dangerous_files:
        representative = dangerous_files[0]
    elif file_list:
        representative = file_list[0]
    
    return {
        "status": "SAFE", 
        "detected_media": detected_media, 
        "representative": representative
    }


def inspect_archive(filepath: str, expected_type: str = "unknown") -> dict:

    """
    Orquestador de la inspección de archivos comprimidos. Extrae la lista de archivos y delega el análisis de seguridad.
    
    Args:
        filepath: Ruta del archivo.
        expected_type: Tipo de medio que esperamos encontrar.
        
    Returns:
        dict: Resultado con status, medio detectado y representante.
    """

    path = Path(filepath)
    ext = path.suffix.lower()
    
    try:

        # Paso 1: Obtención de la lista de archivos
        try:

            # Si es un ZIP, uso el método nativo de Python. Si no, uso patool.
            if ext == ".zip":
                file_list = _list_zip(filepath)
            else:
                file_list = _list_generic(filepath)


        # Manejo de errores de extracción (archivos ZIP cifrados o corruptos)
        except PermissionError:

            # Captura de ZIPs con contraseña
            logger.warning(f"🔒 [Inspector] Archivo ZIP cifrado: {path.name}")
            return {"status": "SUSPICIOUS", "detected_media": None}

        # Captura de errores de patool o archivos corruptos/cifrados
        except Exception as e:

            err_msg = str(e).lower()

            # Identificamos si es por cifrado/corrupción o un error genérico
            if any(word in err_msg for word in ["password", "encrypt", "checksum"]):

                logger.warning(f"🔒 [Inspector] Archivo cifrado/corrupto ({ext}): {path.name}")
                return {"status": "SUSPICIOUS", "detected_media": None}

            # Si el error no es de cifrado, lo registramos como error genérico
            logger.error(f"❌ [Inspector] Error procesando {path.name}: {e}")
            return {"status": "ERROR", "detected_media": None}

        # Paso 2: Análisis de contenido y Veredicto
        detected_media, dangerous_files = _analyze_file_list(file_list)
        return _calculate_verdict(path.name, expected_type, detected_media, dangerous_files, file_list)

    # Si fallo crítico en la función inspect_archive
    except Exception as e:
        logger.error(f"❌ [Inspector] Fallo crítico en {path.name}: {e}")
        return {"status": "ERROR", "detected_media": None}
