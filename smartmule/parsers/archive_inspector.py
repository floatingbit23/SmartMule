import zipfile # Es una librería que permite abrir archivos .zip
import patoolib # Es una librería que permite abrir archivos comprimidos de diferentes formatos
import logging
import contextlib 
from io import StringIO # Es una librería que permite capturar la salida de un programa
from pathlib import Path

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

# Función para inspeccionar archivos comprimidos
def inspect_archive(filepath: str, expected_type: str = "unknown") -> dict:

    """
    Inspecciona contenedores (.zip, .rar, .7z...) para listar su contenido. No extrae datos, solo lee el índice por motivos de seguridad y velocidad.
    
    Args:
        filepath: Ruta del archivo.
        expected_type: Tipo de medio que esperamos encontrar (determinado por IA o Regex).

    Devuelve un diccionario con:
    - "status": "SAFE" | "SUSPICIOUS" | "MALICIOUS" | "ERROR"
    - "detected_media": "video", "audio", "book", "software", "games", "documents" o None
    """

    path = Path(filepath) 
    ext = path.suffix.lower() 
    
    file_list = [] # Lista vacía de archivos dentro del contenedor

    status = "SAFE" # Estado inicial del archivo (seguro por defecto)
    
    try:

        if ext == ".zip":

            with zipfile.ZipFile(filepath, 'r') as z: # Abro el archivo ZIP en modo lectura
                 
                for zinfo in z.infolist(): # Recorro los archivos dentro del ZIP
                    
                    # Si el bit índice 0 del flag está a 1, el archivo está cifrado.

                    if zinfo.flag_bits & 0x1: # operador BITWISE AND para aislar el bit 0, llamado Encyption Flag
                        # (si es 1 = cifrado, si es 0 = no cifrado)
                        logger.warning(f"🔒  [Inspector] Archivo ZIP cifrado con contraseña: {path.name}")
                        return {"status": "SUSPICIOUS", "detected_media": None}
                    
                    file_list.append(zinfo.filename) # Agrego a la lista de archivos
                    
        else: # .rar, .7z, .tar, etc. vía patool

            logger.info(f"🔎  [Inspector] Escaneando contenedor {path.name}...")
            
            output_buffer = StringIO() # Buffer para capturar la salida de patool

            try:

                # list_archive imprime por pantalla, por lo que redirigimos stdout a nuestro buffer.
                with contextlib.redirect_stdout(output_buffer):
                    patoolib.list_archive(filepath)
                    
                output_str = output_buffer.getvalue()
                
                # patool imprime una línea por archivo, entre otra info de cabecera
                lines = output_str.splitlines()

                for line in lines: # Recorro las líneas

                    line = line.strip() # Elimino espacios en blanco al inicio y al final

                    # Si una línea termina en alguna de las extensiones conocidas, consideramos que es un archivo.
                    # Hacemos esto extrayendo todas las "palabras" que parezcan archivos
                    # Sin embargo, una forma robusta es simplemente buscar las extensiones directamente en todo el texto del listing.
                    file_list.append(line)
                    
            except patoolib.util.PatoolError as e:

                # patool lanza excepción si el archivo requiere contraseña para listar (como los RAR con cabecera cifrada) o si falla al abrir.
                err_msg = str(e).lower()

                # Si el mensaje de error contiene "password", "encrypt" o "checksum error", es que el archivo está cifrado o corrupto
                if "password" in err_msg or "encrypt" in err_msg or "checksum error" in err_msg: 
                    logger.warning(f"🔒 [Inspector] Archivo cifrado y/o corrupto detectado ({ext}): {path.name}")
                    return {"status": "SUSPICIOUS", "detected_media": None}
                
                # Si no es ninguno de los casos anteriores, es un error de patool
                logger.error(f"❌ [Inspector] Error listando {path.name}: {e}")
                return {"status": "ERROR", "detected_media": None}


        # == EVALUACIÓN DE INCONSISTENCIA SEMÁNTICA ==

        detected_media = None # Variable para almacenar el Media Type detectado
        has_dangerous = False # Flag para detectar archivos peligrosos
        dangerous_files = [] # Lista para almacenar archivos peligrosos
        
        for fname in file_list: # Recorro los archivos dentro de la lista

            fname_lower = fname.lower() # Convierto el nombre del archivo a minúsculas
            
            # Buscar extensiones peligrosas (.exe, .vbs...)
            for dext in DANGEROUS_EXTS:
                if fname_lower.endswith(dext): # Si el nombre del archivo termina en una extensión peligrosa
                    has_dangerous = True # Activo el flag de archivos peligrosos
                    dangerous_files.append(fname)
                    break
                    

            # Buscar medios verdaderos si no hemos encontrado aún
            if not detected_media:
                for mext, mtype in MEDIA_MAPPING.items(): # Recorro el diccionario de mapeo
                    # mext = extensión, mtype = Media Type
                    if fname_lower.endswith(mext): # Si el nombre del archivo termina en una extensión válida
                        detected_media = mtype # Le asigno el Media Type correspondiente
                        break
                        
        # --- LÓGICA DE VEREDICTO POR CONTEXTO ---

        # Si NO esperamos software ni juegos, pero hay ejecutables -> MALICIOUS (Suplantación)

        if has_dangerous and expected_type not in ["software", "games"]:
             logger.critical(f"💀 [Inspector] ¡SUPLANTACIÓN! {path.name} (que debería ser {expected_type}) contiene ejecutables.")
             return {"status": "MALICIOUS", "detected_media": "software", "representative": dangerous_files[0]}
             
        # Si esperamos juegos o software, el ejecutable es NORMAL, pero por seguridad lo dejamos bajo sospecha o revisión si son muchos

        if has_dangerous and expected_type in ["software", "games"]:
             logger.info(f"✅ [Inspector] Ejecutables encontrados en contenedor de {expected_type}. Permitido por contexto.")
             # No es Malicious, dejamos que VirusTotal decida después.
             
        # Los documentos NO deben tener ejecutables dentro de sus contenedores (si comprimidos)
        
        if has_dangerous and expected_type == "documents":
             logger.critical(f"💀 [Inspector] ¡MALWARE! Documento contenedor de scripts/ejecutables detectado.")
             return {"status": "MALICIOUS", "detected_media": "software"}

        # Si no se encontró ningún archivo peligroso
        logger.info(f"✅ [Inspector] Contenedor limpio. Contiene {len(file_list)} elementos.")
        
        # Si se detectó un tipo de medio
        if detected_media:
            logger.info(f"📼 [Inspector] Detectado contenido principal de tipo: {detected_media}")
            
        # Si no se encontró ningún tipo de medio
        else:
            logger.warning(f"⚠️ [Inspector] No se detectó contenido multimedia válido en el contenedor.")
            
        # Devolvemos el estado (seguro), el tipo de medio detectado y el archivo representante (si hay)
        representative = dangerous_files[0] if dangerous_files else (file_list[0] if file_list else None)
        return {"status": "SAFE", "detected_media": detected_media, "representative": representative}

    except Exception as e:
        logger.error(f"❌ [Inspector] Fallo crítico inspeccionando {path.name}: {e}")
        return {"status": "ERROR", "detected_media": None}
