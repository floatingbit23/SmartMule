"""
Punto de entrada de SmartMule.

Aquí orquesto todos los componentes de la implementación inicial:
1. Cargo la configuración desde .env
2. Configuro el logging
3. Establezco la prioridad de I/O baja para no competir con otros programas
4. Creo el QueueManager (PriorityQueue + Worker Thread)
5. Creo el SmartMuleWatcher (FileSystemObserver + debouncer)
6. Hago un scan inicial de archivos existentes en Incoming
7. Mantengo el programa corriendo en segundo plano o consola.

Implementa un Singleton mediante PID y un comando `stop`.
"""

import sys # Manejo de argumentos
import os # Manejo de archivos y procesos
import signal # Manejo de señales de terminación
import psutil # Manejo de procesos
import logging # Manejo de logs
import argparse # Manejo de argumentos
from typing import Optional # Tipado

from smartmule.config import (
    BASE_DIR, # Directorio base
    INCOMING_PATH,
    LIBRARY_PATH,
    DEBOUNCE_SECONDS,
    FILE_LOCK_TIMEOUT,
    setup_logging,
    validate_paths,
)
from smartmule.queue_manager import QueueManager
from smartmule.watcher import SmartMuleWatcher

# Logger para este módulo.
logger = logging.getLogger("SmartMule.main")

PID_FILE = BASE_DIR / "smartmule.pid" # Archivo PID para el daemon

# Función para obtener el PID del daemon
def get_active_pid() -> Optional[int]:

    """Lee el PID del daemon si está activo."""

    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        if psutil.pid_exists(pid):
            return pid
        else:
            PID_FILE.unlink() # Proceso huérfano
            return None
    except Exception:
        return None

# Función para escribir el PID actual en el fichero
def write_pid():
    """Guarda el PID actual en el fichero."""
    PID_FILE.write_text(str(os.getpid()))

# Función para borrar el archivo PID si existe
def remove_pid():
    """Borra el archivo PID si existe."""
    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
        except:
            pass

# Función para detener el daemon
def stop_daemon():
    """Detiene el servicio en segundo plano leyendo el PID."""
    pid = get_active_pid()
    if not pid:
        print("ℹ️  SmartMule no está corriendo en segundo plano.")
        return
        
    print(f"🛑 Deteniendo SmartMule (PID: {pid})...")
    try:
        p = psutil.Process(pid)
        p.terminate() # Equivalente a SIGTERM
        p.wait(timeout=5)
        print("✅  SmartMule se ha detenido limpiamente.")
    except psutil.NoSuchProcess:
        print("ℹ️  El proceso ya no existe.")
    except psutil.TimeoutExpired:
        print("⚠️  El proceso está tardando en cerrar. Forzando cierre (kill)...")
        p.kill()
    except Exception as e:
        print(f"❌  Error al detener: {e}")
    finally:
        remove_pid()

def setup_io_priority() -> None:
    """Establezco la prioridad de I/O del proceso a 'Very Low' en Windows."""
    try:
        process = psutil.Process(os.getpid())
        process.ionice(psutil.IOPRIO_VERYLOW)
        logger.info("✅  Prioridad de I/O [VERY_LOW] establecida exitosamente.")
    except Exception as e:
        logger.warning(f"⚠️  No pude establecer la prioridad de I/O: {e}")


def main() -> None:
    """Función principal de SmartMule."""
    parser = argparse.ArgumentParser(description="SmartMule - El Bibliotecario Inteligente P2P")
    parser.add_argument("action", nargs="?", default="start", choices=["start", "stop"], help="Acción a realizar: start (por defecto) o stop")
    parser.add_argument("--debug", action="store_true", help="Habilita los logs de nivel DEBUG")
    args = parser.parse_args()

    if args.action == "stop":
        stop_daemon()
        sys.exit(0)

    # === Singleton ===
    active_pid = get_active_pid()
    if active_pid:
        print(f"⚠️  SmartMule ya está corriendo en 2º plano (PID: {active_pid}).")
        print("Ejecuta 'python main.py stop' para detenerlo antes de iniciar otro.")
        sys.exit(1)

    write_pid()

    # === 1. Logging ===
    log_level = "DEBUG" if args.debug else None
    setup_logging(level=log_level)

    banner = r"""+===================================+
|  SmartMule 🫏                    |
|  El Demonio Inteligente P2P       |
+===================================+"""
    print(f"\033[94m{banner}\033[0m\n")
 
    # === 2. Validación de rutas ===
    if not validate_paths():
        logger.error("❌  Error en la configuración de rutas. Abortando.")
        remove_pid()
        sys.exit(1)
 
    logger.info(f"🔹  Carpeta Incoming:   {INCOMING_PATH}")
    logger.info(f"🔹  Carpeta Library:    {LIBRARY_PATH}")
    logger.info(f"🔹  Debounce:           {DEBOUNCE_SECONDS}s")
    logger.info(f"🔹  Timeout bloqueo:    {FILE_LOCK_TIMEOUT}s")

    # === 3. Prioridad de I/O ===
    setup_io_priority()

    # === 4. QueueManager ===
    queue_manager = QueueManager(auto_start=False)

    # === 5. Watcher ===
    watcher = SmartMuleWatcher(queue_manager)

    # === Manejo de Señales de Terminación ===
    def handle_shutdown(signum, frame):
        logger.warning(f"\n⚠️  Señal de apagado ({signum}) recibida. Apagando motor...")
        watcher.stop()
        queue_manager.stop()
        remove_pid()
        logger.info("ℹ️  SmartMule detenido. ¡HASTA LA PRÓXIMA! 🫏")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown) # Ctrl+C
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, handle_shutdown)
    else:
        try:
            signal.signal(signal.SIGBREAK, handle_shutdown)
        except AttributeError:
            pass

    # === 6. Scan inicial ===

    # Busco archivos que ya estuvieran en Incoming antes de arrancar SmartMule. 
    # Los meto en la cola directamente sin pasar por el debounce.
    watcher.scan_existing()

    # === 7. Procesamiento inicial ===

    # Ahora que todo está encolado (con sus logs agrupados en bloque), soltamos al worker.
    queue_manager.start_worker()

    # Antes de seguir, espero a que el trabajador termine de procesar los archivos encontrados en el scan inicial.
    # De esta forma los logs de procesamiento no se mezclan con el mensaje de "SmartMule está corriendo".
    if not queue_manager._queue.empty():
        logger.info("🔹  Procesando archivos del escaneo inicial...")
        queue_manager._queue.join() # Bloquea hasta que task_done() se llame para todos los elementos.

    # === 8. Inicio de monitorización ===

    # Arranco el Observer para detectar archivos nuevos en tiempo real. 
    watcher.start()

    # Mensaje de operatividad (lanzado como un bloque único para evitar que se mezcle con otros logs)
    banner_final = (
        "\n=========================================================================\n"
        f"🚀 SmartMule está operativo (PID: {os.getpid()}).\n"
        "   Vigilando 'Incoming' en silencio. Usa 'python main.py stop' para detenerme.\n"
        "========================================================================="
    )
    logger.info(banner_final)

    # === 9. Bucle principal ===
    try:
        while watcher._observer.is_alive():
            watcher._observer.join(timeout=1.0) 
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        queue_manager.stop()
        remove_pid()

if __name__ == "__main__":
    main()
