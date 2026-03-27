"""
config.py — Configuración centralizada de SmartMule.

Cargo todas las variables de entorno desde el archivo .env y las expongo como constantes tipadas para que el resto de módulos las importen directamente.
Valido que las rutas críticas existan al arrancar para evitar errores silenciosos.
"""

import os # os es un módulo que permite interactuar con el sistema operativo
import sys # sys es un módulo que permite interactuar con el intérprete de Python
import logging # logging es un módulo que permite registrar eventos
from pathlib import Path # Path es una clase que representa rutas de archivos y directorios
from dotenv import load_dotenv # load_dotenv es una función que carga las variables de entorno desde un archivo .env

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
        # Guardamos el nombre original para restaurarlo después (por si hay otros handlers)
        original_name = record.name
        
        # Aplicamos el color al nombre del componente
        comp_color = self.COMPONENT_COLORS.get(original_name, "")
        if comp_color:
            record.name = f"{comp_color}{original_name}{self.RESET}"

        # Formateamos el mensaje base usando el formato estándar
        log_message = super().format(record)
        
        # Restauramos el nombre original
        record.name = original_name
        
        # Lógica de colores por nivel/emojis (como antes)
        msg_str = str(record.msg) if record.msg else ""
        
        if msg_str.startswith("❌"):
            return f"{self.RED}{log_message}{self.RESET}"
        elif msg_str.startswith("⚠️"):
            return f"{self.YELLOW}{log_message}{self.RESET}"
        elif msg_str.startswith("✅"):
            return f"{self.GREEN}{log_message}{self.RESET}"
        
        return log_message


def setup_logging() -> logging.Logger:

    """
    Configuro el sistema de logging con colores y un formato estructurado.
    Uso un StreamHandler para que los logs salgan por la consola con colores ANSI.

    Returns:
        Logger raíz configurado con el nivel especificado en LOG_LEVEL.
    """

    log_format = "%(asctime)s  %(levelname)-8s [%(name)s]  %(message)s\n"
    date_format = "%H:%M:%S"

    # Configuro el logger raíz
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

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
