import zipfile # Es una librería que permite abrir archivos .zip
import patoolib # Es una librería que permite abrir archivos comprimidos de diferentes formatos
import logging
import contextlib 
from io import StringIO # Es una librería que permite capturar la salida de un programa
from pathlib import Path

logger = logging.getLogger("SmartMule.inspector") 

# Extensiones peligrosas
DANGEROUS_EXTS = {".exe", ".vbs", ".js", ".bat", ".cmd", ".ps1", ".scr", ".pif", ".wsf", ".msi"}

# Mapeo de extensiones a Media Types
MEDIA_MAPPING = {
    ".mkv": "video", 
    ".mp4": "video", 
    ".avi": "video", 
    ".wmv": "video", 
    ".mov": "video",
    ".mp3": "audio", 
    ".flac": "audio", 
    ".m4a": "audio", 
    ".wav": "audio",
    ".pdf": "book", 
    ".epub": "book", 
    ".mobi": "book", 
    ".cbz": "book", 
    ".cbr": "book"
}

# Función para inspeccionar archivos comprimidos
def inspect_archive(filepath: str) -> dict:

    """
    Inspecciona contenedores (.zip, .rar, .7z...) para listar su contenido. No extrae datos, solo lee el índice por motivos de seguridad y velocidad.
    
    Devuelve un diccionario con:
    - "status": "SAFE" | "SUSPICIOUS" | "MALICIOUS" | "ERROR"  (Estado del archivo dentro del contenedor)
    - "detected_media": "video", "audio", "book", "software" o None (Tipo de archivo detectado dentro del contenedor)
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
        
        for fname in file_list: # Recorro los archivos dentro de la lista

            fname_lower = fname.lower() # Convierto el nombre del archivo a minúsculas
            
            # Buscar extensiones peligrosas (.exe, .vbs...)
            for dext in DANGEROUS_EXTS:
                if fname_lower.endswith(dext): # Si el nombre del archivo termina en una extensión peligrosa
                    has_dangerous = True # Activo el flag de archivos peligrosos
                    logger.warning(f"⚠️ [Inspector] ENCONTRADO ARCHIVO EJECUTABLE CAMUFLADO: {fname}")
                    break
                    

            # Buscar medios verdaderos si no hemos encontrado aún
            if not detected_media:
                for mext, mtype in MEDIA_MAPPING.items(): # Recorro el diccionario de mapeo
                    # mext = extensión, mtype = Media Type
                    if fname_lower.endswith(mext): # Si el nombre del archivo termina en una extensión válida
                        detected_media = mtype # Le asigno el Media Type correspondiente
                        break
                        
        # Si se encontró AL MENOS 1 archivo peligroso en el contenedor
        if has_dangerous: 
            logger.critical(f"💀 [Inspector] ¡PELIGRO! {path.name} contiene malware encubierto.")
            return {"status": "MALICIOUS", "detected_media": "software"}
            
        # Si no se encontró ningún archivo peligroso
        logger.info(f"✅ [Inspector] Contenedor limpio. Contiene {len(file_list)} elementos.")
        
        # Si se detectó un tipo de medio (si hay varios archivos, se toma el primer Media Type que se encuentre por orden de aparición)
        if detected_media:
            logger.info(f"📼 [Inspector] Detectado contenido principal de tipo: {detected_media}")
            
        # Si no se encontró ningún tipo de medio
        else:
            logger.warning(f"⚠️ [Inspector] No se detectó contenido multimedia válido en el contenedor.")
            
        # Devolvemos el estado (seguro) y el tipo de medio detectado
        return {"status": "SAFE", "detected_media": detected_media}

    except Exception as e:
        logger.error(f"❌ [Inspector] Fallo crítico inspeccionando {path.name}: {e}")
        return {"status": "ERROR", "detected_media": None}
