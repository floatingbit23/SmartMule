"""
config.py — Configuración centralizada de SmartMule.

Cargo todas las variables de entorno desde el archivo .env y las expongo como constantes tipadas para que el resto de módulos las importen directamente.
Valido que las rutas críticas existan al arrancar para evitar errores silenciosos.
"""

import os # os es un módulo que permite interactuar con el sistema operativo
import sys # sys es un módulo que permite interactuar con el intérprete de Python
import logging
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Cargo las variables de entorno desde el archivo .env que está en la raíz del proyecto
load_dotenv(override=False)

# === Rutas del sistema de archivos ===

# Ruta a la carpeta Incoming de eMule, donde llegan las descargas completadas
# Es la carpeta que voy a monitorizar con el Watcher
INCOMING_PATH: Path = Path(os.getenv("INCOMING_PATH", r"C:\Users\Javi\eMule\Incoming"))

# Ruta a la carpeta Library, donde organizaré los archivos clasificados
# Está en la misma partición que Incoming, así que puedo hacer os.rename() atómico
LIBRARY_PATH: Path = Path(os.getenv("LIBRARY_PATH", r"C:\Users\Javi\eMule\SmartMule\Library"))

# === Parámetros del hashing ED2K ===

# Tamaño de bloque del algoritmo ED2K (estándar fijo, NO configurable por el usuario).
# Este valor está definido por el protocolo eDonkey y no debe cambiarse NUNCA.
ED2K_CHUNK_SIZE: int = 9_728_000  # 9,728,000 bytes = exactamente 9.28 MB

# Ruta a la base de datos SQLite donde guardo el historial de hashes procesados.
# La BBDD vive dentro de Library para ser parte de la "biblioteca" del usuario.
DB_PATH: Path = LIBRARY_PATH / "smartmule.db"


# === Parámetros del Watcher (debouncing) ===

# Tiempo en segundos que espero sin recibir nuevos eventos de un mismo archivo antes de considerarlo "estable" y procesarlo. 
# Windows genera múltiples eventos (created + modified) para una sola operación de archivo, así que necesito este margen (3 segundos) para agruparlos en una sola acción.
DEBOUNCE_SECONDS: float = float(os.getenv("DEBOUNCE_SECONDS", "3.0"))


# === Parámetros del File Locker (retry con backoff exponencial) ===

# Al finalizar una descarga, eMule antiene el archivo bloqueado durante unos segundos mientras:
# 1. Une los trozos (.part) en el archivo definitivo
# 2. Calcula el hash ED2K del archivo final
# 3. Actualiza el archivo known.met (los Shared Files)
# 4. Hace el uploading del archivo a la red

# Tiempo máximo en segundos que espero a que eMule libere el bloqueo de un archivo. 
# Si transcurre este tiempo (120 segundos) y el archivo sigue bloqueado, lo descarto con un error.
FILE_LOCK_TIMEOUT: int = int(os.getenv("FILE_LOCK_TIMEOUT", "120"))

# Delay inicial entre reintentos cuando un archivo está bloqueado (en segundos).
# Después de cada intento fallido, duplico este valor (backoff exponencial).
FILE_LOCK_INITIAL_DELAY: float = 1.0

# Delay máximo entre reintentos. El backoff exponencial nunca superará este valor, aunque se hayan acumulado muchos intentos. 
# De esta forma evito esperas absurdas.
FILE_LOCK_MAX_DELAY: float = 15.0

# === Extensiones a ignorar ===

# Estas son las extensiones de los archivos temporales de eMule.
# Los ignoro completamente porque son archivos incompletos o metadatos internos de eMule que no debo procesar. 

# El Watcher descartará cualquier evento que involucre archivos con estas extensiones:
IGNORED_EXTENSIONS: set = {
    ".part",          # Descarga incompleta de eMule
    ".part.met",      # Metadatos de la descarga en curso
    ".part.met.bak",  # Backup de los metadatos
    ".tmp",           # Archivos temporales genéricos
}


# === Logging ===

# Nivel de log configurable desde .env. Controla la verbosidad de los mensajes:
# DEBUG = todo, INFO = operaciones normales, WARNING = anomalías, ERROR = fallos.
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()


# === APIs y LLMs ===

# TMDB (The Movie Database)
TMDB_BEARER_TOKEN: str = os.getenv("TMDB_BEARER_TOKEN", "")
TMDB_BASE_URL: str = "https://api.themoviedb.org/3"

# User-Agent genérico para APIs Comunitarias (Exigido por OpenLibrary y MusicBrainz)
CONTACT_EMAIL_USER_AGENT: str = os.getenv("CONTACT_EMAIL_USER_AGENT", "SmartMule/1.0 (contacto@example.com)")

# OpenLibrary
OPENLIBRARY_BASE_URL: str = "https://openlibrary.org"

# MusicBrainz
MUSICBRAINZ_BASE_URL: str = "https://musicbrainz.org/ws/2"

# VirusTotal (Triaje de Software)
VIRUSTOTAL_API_KEY: str = os.getenv("VIRUSTOTAL_API_KEY", "")
VIRUSTOTAL_BASE_URL: str = "https://www.virustotal.com/api/v3"

# Parámetros HTTP Generales
API_TIMEOUT: int = 20  # Timeout en segundos para solicitudes HTTP

# LLMs (IA)
USE_LOCAL_LLM: bool = os.getenv("USE_LOCAL_LLM", "True").lower() in ("true", "1", "yes")
LMSTUDIO_API_KEY: str = os.getenv("LMSTUDIO_API_KEY", "lm-studio")
LOCAL_LLM_URL: str = "http://127.0.0.1:1234/v1"

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

class ColoredFormatter(logging.Formatter):
    """
    Formateador de logs que añade colores ANSI según el nivel y el contenido.
    - ERROR: Rojo
    - WARNING: Amarillo
    - Mensajes que empiezan con ✅: Verde
    """
    
    # Códigos ANSI para colores
    RESET = "\033[0m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    
    # Colores para módulos
    BLUE = "\033[94m"     # main
    CYAN = "\033[96m"     # watcher
    MAGENTA = "\033[95m"  # queue_manager
    WHITE = "\033[97m"    # hasher
    GREY = "\033[37m"     # database
    
    # Mapeo de colores por nombre de logger
    COMPONENT_COLORS = {
        "SmartMule.main": BLUE,
        "SmartMule.watcher": CYAN,
        "SmartMule.queue_manager": MAGENTA,
        "SmartMule.hasher": WHITE,
        "SmartMule.database": GREY,
    }

    def format(self, record):
        # Extraemos salto de línea manual para que no rompa el prefijo (timestamp, logger)
        has_manual_newline = False
        msg_str = str(record.msg) if record.msg else ""
        if msg_str.startswith("\n"):
            has_manual_newline = True
            record.msg = msg_str[1:] # Lo quitamos temporalmente

        # Guardamos el nombre original para restaurarlo después (por si hay otros handlers)
        original_name = record.name
        
        # Aplicamos el color al nombre del componente
        comp_color = self.COMPONENT_COLORS.get(original_name, "")
        if comp_color:
            record.name = f"{comp_color}{original_name}{self.RESET}"

        # Formateamos el mensaje base usando el formato estándar
        log_message = super().format(record)
        
        # Restauramos el nombre original y el mensaje
        record.name = original_name
        record.msg = msg_str 
        
        # Lógica de colores por nivel (Prioridad: CRITICAL siempre Violeta)
        if record.levelno == logging.CRITICAL:
            log_message = f"{self.MAGENTA}{log_message}{self.RESET}"
        
        # Lógica de colores por emojis si no es crítico (ya que ya tiene color violeta)
        else:
            if getattr(record, 'msg', '').startswith("\n") and getattr(record, 'msg', '')[1:].startswith("❌"):
                log_message = f"{self.RED}{log_message}{self.RESET}"
            elif msg_str.startswith("❌"):
                log_message = f"{self.RED}{log_message}{self.RESET}"
            elif msg_str.startswith("⚠️"):
                log_message = f"{self.YELLOW}{log_message}{self.RESET}"
            elif msg_str.startswith("✅"):
                log_message = f"{self.GREEN}{log_message}{self.RESET}"
            
        # Si el usuario mandó un \n al principio del log (ej: Procesando), lo metemos antes de toda la línea (antes de la hora).
        if has_manual_newline:
            log_message = f"\n{log_message}"

        # Petición: Todos los logs que no sean de tipo INFO tendrán un \n arriba y otro abajo.
        if record.levelno != logging.INFO:
            log_message = f"\n{log_message}\n"
        
        return log_message


def setup_logging(level: Optional[str] = None) -> logging.Logger:

    """
    Configuro el sistema de logging con colores y un formato estructurado.
    Uso un StreamHandler para que los logs salgan por la consola con colores ANSI.
    
    Args:
        level: Nivel de log opcional (ej: "DEBUG"). Si no se pasa, usa LOG_LEVEL de .env.

    Returns:
        Logger raíz configurado con el nivel especificado.
    """
    
    # Prioridad: nivel pasado por argumento > LOG_LEVEL de config/env > INFO (fallback)
    target_level_str = level or LOG_LEVEL
    target_level = getattr(logging, target_level_str.upper(), logging.INFO)

    log_format = "%(asctime)s  %(levelname)-8s [%(name)s]  %(message)s"
    date_format = "%H:%M:%S"

    # Configuro el logger raíz
    root_logger = logging.getLogger()
    root_logger.setLevel(target_level)

    # Limpio handlers anteriores si existen (por si se llama dos veces)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Creo el handler de consola con mi formateador de colores
    console_handler = logging.StreamHandler(sys.stdout)
    formatter = ColoredFormatter(log_format, date_format)
    console_handler.setFormatter(formatter)
    
    root_logger.addHandler(console_handler)

    return logging.getLogger("SmartMule")


def validate_paths() -> bool:

    """
    Verifico que las rutas críticas existan antes de arrancar el servicio.
    Si la carpeta Incoming no existe, no tiene sentido continuar porque no hay nada que monitorizar. 
    Si la carpeta Library no existe, la creo automáticamente porque es donde voy a organizar los archivos.

    Returns:
        True si todo está correcto, False si hay un error irrecuperable.
    """

    # Obtengo el logger para esta función
    logger = logging.getLogger("SmartMule.config")

    # Verifico que la carpeta Incoming existe
    if not INCOMING_PATH.exists():
        logger.error(
            f"❌  La carpeta Incoming no existe: {INCOMING_PATH}. "
            f"Verifica que eMule esté instalado y la ruta sea correcta en .env"
        )
        return False

    if not INCOMING_PATH.is_dir():
        logger.error(
            f"❌  La ruta Incoming no es un directorio: {INCOMING_PATH}"
        )
        return False

    # La carpeta Library la creo si no existe, porque es responsabilidad mía mantenerla. 
    if not LIBRARY_PATH.exists():
        logger.info(f"🔹  Creando carpeta Library: {LIBRARY_PATH}")
        LIBRARY_PATH.mkdir(parents=True, exist_ok=True) # parents=True crea también los directorios intermedios.

    return True
