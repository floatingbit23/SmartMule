"""
Punto de entrada de SmartMule.

Aquí orquesto todos los componentes de la implementación inicial:
1. Cargo la configuración desde .env
2. Configuro el logging
3. Establezco la prioridad de I/O baja para no competir con otros programas
4. Creo el QueueManager (PriorityQueue + Worker Thread)
5. Creo el SmartMuleWatcher (FileSystemObserver + debouncer)
6. Hago un scan inicial de archivos existentes en Incoming
7. Mantengo el programa corriendo hasta que el usuario pulse Ctrl+C

El programa es un script que se ejecuta en primer plano. 
No es un servicio Windows, se detiene con Ctrl+C (KeyboardInterrupt).
"""

import sys
import logging

from smartmule.config import (
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


def setup_io_priority() -> None:

    """
    Establezco la prioridad de I/O del proceso a "Very Low" en Windows.

    Esto le dice al planificador de disco de Windows que SmartMule es un proceso de fondo que puede esperar. 
    Así SmartMule no compite por el ancho de banda del disco duro.

    Uso psutil (Process and System Utilities) porque la API de Windows para establecer la prioridad de I/O no está expuesta directamente en el módulo os de Python.
    """

    try:
        import psutil
        import os

        process = psutil.Process(os.getpid()) # Obtengo el PID del proceso actual
        process.ionice(psutil.IOPRIO_VERYLOW) # Establezco la prioridad de I/O a VERY_LOW
        logger.info("✅ Prioridad de I/O [VERY_LOW] establecida exitosamente.")

    except ImportError:
        # Si psutil no está instalado, sigo adelante sin prioridad baja. No es un error fatal, solo una optimización que me pierdo.
        logger.warning(
            "❌ psutil no está instalado. La prioridad de I/O no se ha podido ajustar."
        )
    except Exception as e:
        # En sistemas Linux, psutil.IOPRIO_VERYLOW podría no existir.
        logger.warning(f"⚠ No pude establecer la prioridad de I/O: {e}")


def main() -> None:

    """
    Función principal de SmartMule. Arranco todo, hago el scan inicial y mantengo el programa corriendo hasta que el usuario pulse Ctrl+C.
    """

    # === 0. Argumentos de Línea de Comandos ===
    import argparse
    parser = argparse.ArgumentParser(description="SmartMule - El Bibliotecario Inteligente P2P")
    parser.add_argument("--debug", action="store_true", help="Habilita los logs de nivel DEBUG (más detallados)")
    args = parser.parse_args()

    # === 1. Logging ===

    # Configuro el logging lo antes posible para que cualquier error posterior se registre correctamente.
    # Si se pasa --debug por comando, forzamos el nivel DEBUG.
    log_level = "DEBUG" if args.debug else None
    setup_logging(level=log_level)

    # Muestro el banner de inicio en color azul (color de main).
    # Lo imprimo directamente sin el logger para que no se vea el prefijo de tiempo ni [SmartMule.main],
    # haciendo que luzca como una cabecera limpia y centrada.
    banner = r"""+===================================+
|  SmartMule 🫏                    |
|  El Bibliotecario Inteligente P2P |
+===================================+"""
    print(f"\033[94m{banner}\033[0m\n")
 
    # === 2. Validación de rutas ===
 
    # Verifico que la carpeta Incoming exista y creo Library si no existe.
    if not validate_paths():
        logger.error("❌  Error en la configuración de rutas. Abortando.")
        sys.exit(1)
 
    # Muestro la configuración actual para que el usuario sepa qué estoy haciendo.
    logger.info(f"🔹  Carpeta Incoming:   {INCOMING_PATH}")
    logger.info(f"🔹  Carpeta Library:    {LIBRARY_PATH}")
    logger.info(f"🔹  Debounce:           {DEBOUNCE_SECONDS}s")
    logger.info(f"🔹  Timeout bloqueo:    {FILE_LOCK_TIMEOUT}s")

    # === 3. Prioridad de I/O ===

    # Bajo la prioridad de disco para no molestar al usuario.
    setup_io_priority()

    # === 4. QueueManager ===

    # Creo la PriorityQueue. 
    # El worker NO arranca inmediatamente para evitar que sus logs de procesamiento 
    # se mezclen con los logs de encolado del escaner inicial.
    queue_manager = QueueManager(auto_start=False)

    # === 5. Watcher ===

    # Creo el observador del sistema de archivos y lo apunto a Incoming.
    watcher = SmartMuleWatcher(queue_manager) # le paso la Queue como argumento

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

    print("\n")
    logger.info("ℹ️  SmartMule está corriendo. Pulsa Ctrl+C para detener.")

    # === 9. Bucle principal ===

    # Mantengo el programa vivo esperando la señal de interrupción.
    # El trabajo real lo hacen los hilos del Observer y del Worker Thread.
    try:

        # Uso un bucle con el join() del Observer en lugar de time.sleep()
        # De esta forma puedo detectar si el Observer se ha caído por algún error.
        while watcher._observer.is_alive():
            watcher._observer.join(timeout=1.0) 
        # join() es un método que bloquea la ejecución hasta que el hilo termine. En este caso, lo uso con timeout para que no bloquee indefinidamente.

    except KeyboardInterrupt: # Capturo la interrupción del teclado (Ctrl+C)
        
        #Hago un shutdown limpio.
        logger.info("")
        logger.warning("⚠️  Interrupción recibida (Ctrl+C). Deteniendo SmartMule...")

    # === 9. Shutdown ===

    # Detengo todo en orden: 

    # 1. Primero el Watcher (para que no meta más archivos en la cola)
    watcher.stop()

    # 2. Luego el QueueManager (para que termine lo que esté procesando)
    queue_manager.stop()

    logger.info("ℹ️  SmartMule detenido. ¡HASTA LA PRÓXIMA! 🫏")


# Función inicializadora
if __name__ == "__main__":
    main()
