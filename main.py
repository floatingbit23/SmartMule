"""
Punto de entrada de SmartMule.

Este módulo orquesta todos los componentes del sistema:
1. Gestión de Ciclo de Vida: Implementa un Singleton (1 única instancia activa) a nivel de Sistema Operativo mediante archivos PID ('smartmule.pid').
    De esta forma SmartMule se comporta como un daemon (servicio en segundo plano).
2. Comandos CLI: Soporta 'start' (arrancar el motor), 'stop' (apagado controlado) y '--purge' (limpieza de archivos).
3. Configuración: Carga rutas y secretos desde el archivo '.env' y valida el entorno.
4. Motor de Organización: Inicia el QueueManager (procesamiento) y el Watcher (vigilancia).
5. Optimización: Establece prioridad de I/O baja (IOPRIO_VERYLOW) para no interferir con el uso normal del PC.

Arquitectura (orden de ejecución):
1. main(): El punto de entrada que orquesta el arranque y lee los comandos.
2. get_active_pid(): La primera comprobación para asegurar que no haya otra instancia activa.
3. write_pid(): El registro de identidad que crea el archivo 'smartmule.pid' al iniciar.
4. setup_io_priority(): Optimización que reduce el impacto de disco del proceso.
5. purge_files(): Herramienta de mantenimiento para limpieza de archivos y base de datos.
6. stop_daemon(): Comando para detener de forma segura la instancia en ejecución.
7. handle_shutdown(): Protocolo de cierre limpio ante señales de interrupción (Ctrl+C).
8. remove_pid(): El paso final que elimina el rastro del proceso al terminar.
"""

import sys # Interacción con el intérprete
import os  # Operaciones de sistema
import signal # Captura de señales (Ctrl+C, apagado de sistema)
import psutil # Monitorización avanzada de procesos y recursos
import logging 
import argparse
from typing import Optional 
from pathlib import Path # Gestión de rutas de archivos

# Importaciones locales del motor SmartMule
from smartmule.config import (
    BASE_DIR, # Raíz del proyecto
    INCOMING_PATH, # Carpeta de descarga (eMule/Torrent)
    LIBRARY_PATH, # Carpeta de destino organizado
    PROJECT_PATH, # Ruta raíz del proyecto (.env)
    DB_PATH, # Ruta de la base de datos SQLite
    DEBOUNCE_SECONDS, # Tiempo de espera para estabilización de archivos
    FILE_LOCK_TIMEOUT, # Tiempo máximo de espera por bloqueos de I/O
    setup_logging, # Inicializador de logs
    validate_paths, # Verificador de estructura de carpetas
)
from smartmule.database import HashDatabase # Gestor de la caché de metadatos
from smartmule.queue_manager import QueueManager # Gestor de la cola de procesamiento
from smartmule.watcher import SmartMuleWatcher # Observador del sistema de archivos

# Logger central para el módulo principal
logger = logging.getLogger("SmartMule.main")

# Ruta del archivo que indica que el proceso está activo
PID_FILE = BASE_DIR / "smartmule.pid" 

def get_active_pid() -> Optional[int]:
    """
    Recupera el PID de la instancia activa de SmartMule.
    Si el archivo 'smartmule.pid' existe, pero el proceso ya no, limpia el archivo huérfano.
    """
    if not PID_FILE.exists():
        return None

    try:
        pid = int(PID_FILE.read_text().strip())
        if psutil.pid_exists(pid):
            return pid
        else:
            # El proceso murió inesperadamente, limpiamos el rastro
            PID_FILE.unlink() 
            return None

    except Exception:
        return None

def write_pid():
    """Registra el PID del proceso actual para prevenir ejecuciones duplicadas."""
    PID_FILE.write_text(str(os.getpid()))

def remove_pid():
    """Elimina el archivo PID durante el apagado limpio."""
    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
        except:
            pass

def stop_daemon():
    """
    Busca la instancia activa de SmartMule y le envía una señal de terminación.
    Permite detener el servicio invisible de forma segura desde la consola.
    """
    pid = get_active_pid()
    if not pid:
        print("ℹ️  SmartMule no está corriendo en segundo plano.")
        return
        
    print(f"🛑 Deteniendo SmartMule (PID: {pid})...")
    try:
        p = psutil.Process(pid)
        p.terminate() # Envía SIGTERM (permite guardado de datos y cierre limpio)
        p.wait(timeout=5) # Esperamos a que el proceso termine
        print("✅  SmartMule se ha detenido limpiamente.")
    except psutil.NoSuchProcess:
        print("ℹ️  El proceso ya no existe.")
    except psutil.TimeoutExpired:
        print("⚠️  El proceso está tardando en cerrar. Forzando cierre (kill)...")
        p.kill() # Cierre forzoso si no responde al terminate
    except Exception as e:
        print(f"❌  Error al detener SmartMule: {e}")
    finally:
        remove_pid()

def setup_io_priority() -> None:
    """
    Configura el proceso para que sea 'invisible':
    1. Prioridad de I/O mínima (para no ralentizar el disco).
    2. Prioridad de CPU mínima (para no ralentizar otras aplicaciones).
    """
    try:
        process = psutil.Process(os.getpid())
        
        # 1. Prioridad de DISCO (I/O) -> IOPRIO_VERYLOW: Prioridad mínima, el proceso solo accederá al disco cuando sea estrictamente necesario
        if sys.platform == "win32":
            process.ionice(psutil.IOPRIO_VERYLOW)
        else:
            # En Linux se usa el valor 3 (Idle) para ionice
            process.ionice(psutil.IOPRIO_CLASS_IDLE)
        
        # 2. Prioridad de CPU -> IDLE_PRIORITY_CLASS: El proceso corre cuando el sistema está inactivo
        if sys.platform == "win32":
            process.nice(psutil.IDLE_PRIORITY_CLASS)
        else:
            # En Linux/Unix, "nice 19" es la prioridad más baja
            process.nice(19)

        logger.info("✅  Cortesía de sistema establecida: Prioridad de I/O y CPU establecidas al mínimo.")
    except Exception as e:
        logger.warning(f"⚠️  No pude establecer la cortesía total de recursos: {e}")


def purge_files(query: str, select_all: bool = False, no_preserve: bool = False) -> None:

    """
    Lógica de los flags "--purge" y "--all": Ejecuta el protocolo de limpieza sincronizada de archivos y base de datos.
    
    Args:
        query: Patrón de búsqueda (Soporta Regex y Wildcards).
        select_all: Si es True, selecciona automáticamente todos los resultados.
        no_preserve: Si es True, borra sin pedir confirmación individual (Modo Destructivo).
    """

    search_term = query if query else "" 
    
    # --- PROTOCOLO DE SEGURIDAD (Destrucción Total) ---

    if not search_term and select_all and no_preserve:
        print("\n!!! ATENCION: Has activado el modo 'DESTRUCCIÓN TOTAL' (--all --no-preserve) !!!")
        print("Ejecutar este comando borrará ABSOLUTAMENTE TODOS los archivos registrados en tu BBDD.")
        confirm_total = input("\n¿Estas COMPLETAMENTE SEGURO de querer vaciar tu biblioteca SmartMule y la carpeta Incoming? (ESCRIBE 'BORRAR TODO' para continuar): ")
        if confirm_total != "BORRAR TODO":
            print("Operacion cancelada por seguridad.")
            return
        search_term = "" # Busqueda vacía en SQLite (trae todo)

    # Si no hay término de búsqueda (y no estamos en modo destrucción total)
    elif not search_term and not select_all:
        # Se permite listar todo para que el usuario elija manualmente.
        print("\n[i] No se especificó un término de busqueda. Mostrando lista completa de archivos...")
        search_term = "" # La busqueda vacia en REGEXP trae todo.

    print(f"\n[SEARCH] Buscando archivos para purgar...")
    
    db = HashDatabase(DB_PATH)
    # Nuestra BBDD soporta Regex nativo inyectado desde Python
    results = db.search_by_name(search_term)
    
    if not results:
        if not search_term:
            print(f"\n[i] No tienes archivos registrados en la base de datos de SmartMule!\n")
        else:
            print(f"\n[-] No se encontraron archivos que coincidan con '{search_term}'.\n")
        db.close()
        return

    print(f"\n[OK] Se han encontrado {len(results)} coincidencia(s):\n")
    
    # Mostramos la lista de candidatos si no estamos en modo automático
    if not no_preserve:
        for i, res in enumerate(results, 1):
            title = res['official_title'] if res['official_title'] else res['file_name']
            print(f"  [{i}] {title}")
            print(f"      - Origen:  {res['file_path']}")
            print(f"      - Destino: {res['final_path'] or 'No organizado'}")
            print("-" * 40)

    try:
        to_delete = []
        # Selección de archivos a eliminar
        if select_all:
            to_delete = results
        else:
            choice = input(f"\nSelección [ej: 1, 3-5] (o 'all'/'quit'): ").strip().lower()
            
            # Si presiona salir
            if choice == 'quit':
                db.close() # Cierra la conexion con la base de datos
                return

            # Si presiona todos
            if choice == 'all':
                to_delete = results # Selecciona todos los resultados para borrarlos

            # Si presiona numeros
            else:
                # Intentamos procesar la entrada del usuario (puede fallar si no son números)
                try:
                    # Dividimos la entrada por comas, eliminamos espacios y descartamos elementos vacíos
                    parts = [p.strip() for p in choice.split(",") if p.strip()]

                    # Si no queda nada después del filtrado, lanzamos un error para ir al bloque except
                    if not parts:
                        raise ValueError("Entrada vacía")
                    
                    # Lista temporal para acumular los índices de los archivos a borrar
                    indices = []

                    # Iteramos sobre cada fragmento separado por comas
                    for p in parts:

                        # Si el fragmento detecta un guion, lo tratamos como un rango numérico
                        if '-' in p:
                            # Dividimos el rango en valor inicial y valor final
                            start, end = p.split('-')
                            # Convertimos a entero y restamos 1 para ajustar al índice 0 de Python
                            start = int(start) - 1
                            # Hacemos lo mismo con el valor final del rango
                            end = int(end) - 1

                            # Validamos que el rango sea lógico, positivo y no se salga de la lista
                            if 0 <= start <= end < len(results):

                                # Añadimos todos los números del rango a nuestra lista de índices
                                indices.extend(range(start, end + 1))

                            # Si el rango es incoherente o se sale de los límites...
                            else:
                                # Informamos del error específico al usuario
                                print(f"\n[!] El rango '{p}' no es válido.")

                                # Cerramos la conexión a la BBDD por seguridad antes de salir
                                db.close()

                                # Abortamos la función de purga
                                return

                        # Si no hay guion (no es rango), tratamos el fragmento como un número único
                        else:

                            # Convertimos a entero y restamos 1 para el índice de la lista
                            idx = int(p) - 1

                            # Verificamos que el número esté dentro del rango de resultados disponibles
                            if 0 <= idx < len(results):

                                # Añadimos el índice único a nuestra lista
                                indices.append(idx)

                            # Si el número no corresponde a ningún archivo de la lista...

                            else:

                                # Informamos del error de índice inexistente
                                print(f"\n[!] El número '{p}' no existe en la lista.")

                                # Cerramos la conexión a la base de datos
                                db.close()

                                # Salimos de la función
                                return
                    
                    # Convertimos la lista a set (para borrar duplicados), volvemos a lista y ordenamos
                    indices = sorted(list(set(indices)))

                    # Creamos la lista final de objetos a borrar usando los índices validados
                    to_delete = [results[i] for i in indices]
                    
                # Si en algún punto falla la conversión int() o hay un error de formato...
                except ValueError:

                    # Informamos al usuario del formato correcto esperado
                    print("\n[!] Entrada no válida. Usa números separados por comas (ej: 1, 3) o rangos (ej: 1-3).")

                    # Cerramos la base de datos para no dejar conexiones abiertas
                    db.close()

                    # Terminamos la ejecución
                    return

        # Confirmación física final
        if not no_preserve:
            confirm = input(f"\n!!! ¿Estas SEGURO de que quieres borrar fisicamente estos {len(to_delete)} archivo(s)? (s/n): ").strip().lower()
            if confirm != 's':
                print("Operacion cancelada.")
                db.close()
                return
        else:
            print(f"[!] Iniciando borrado automatico de {len(to_delete)} archivos...")

        # --- CICLO DE ELIMINACIÓN ---
        for i, item in enumerate(to_delete, 1):
            file_name = item['file_name']
            print(f"\n[{i}/{len(to_delete)}] Procesando: {file_name}")

            # 1. Borrar archivo original (Incoming)
            src = Path(item['file_path'])
            if src.exists():
                try:
                    if src.is_dir():
                        import shutil
                        shutil.rmtree(src) # Borrado recursivo de carpetas
                    else:
                        os.remove(src) # Borrado de archivo simple
                    print(f"  [-] Eliminado de Incoming: {src.name}")
                except Exception as e:
                    print(f"  [!] Error borrando origen {src.name}: {e}")
            else:
                print(f"  [i] El archivo ya no existe en Incoming (saltando).")
            
            # 2. Borrar archivo organizado (Library)
            if item['final_path']:
                dest = Path(item['final_path'])
                if dest.exists():
                    try:
                        if dest.is_dir():
                            import shutil
                            shutil.rmtree(dest)
                        else:
                            os.remove(dest)
                        print(f"  [-] Eliminado de Library:  {dest.name}")
                    except Exception as e:
                        print(f"  [!] Error borrando destino {dest.name}: {e}")
                else:
                    print(f"  [i] El archivo ya no existe en Library (saltando).")

            # 3. Borrar de la base de datos (Sincronización total)
            db.delete_by_id(item['id'])
            print(f"  [OK] Registro eliminado de la base de datos.")

        print(f"\n[DONE] ¡Purga completada con éxito!\n")

    except ValueError:
        print("[!] Entrada no valida.")
    except Exception as e:
        print(f"[ERROR] Error durante la purga: {e}")
    finally:
        db.close() # Siempre cerramos la conexión a la BBDD


def list_files() -> None:
    """
    Lista todos los archivos registrados en la base de datos y muestra estadísticas.
    """
    db = HashDatabase(DB_PATH)
    try:
        stats = db.get_stats()
        files = db.get_all_files()

        print("\n===================================================")
        print("          SmartMule: Inventario de Biblioteca")
        print("===================================================")
        
        CATEGORY_ICONS = {
            "video": "🎬",
            "tv series": "📺",
            "audio": "🎵",
            "book": "📚",
            "software": "💾",
            "image": "🖼️",
            "compressed": "🗜️",
            "unknown": "❓"
        }

        if not files:
            print("\n[i] La biblioteca está vacía.")
        else:
            for f in files:
                m_type = f.get("media_type", "unknown")
                icon = CATEGORY_ICONS.get(m_type, "❓")
                title = f.get("official_title") or f.get("file_name")
                
                # Truncamos títulos largos para que no rompan la consola
                if len(title) > 60:
                    title = title[:57] + "..."
                
                print(f" {icon} {title}")

        print("\n---------------------------------------------------")
        print(f"  📊 Total de archivos: {stats['total']}")
        
        if stats["categories"]:
            print("  📂 Desglose por categorías:")
            for cat, count in stats["categories"].items():
                icon = CATEGORY_ICONS.get(cat, "❓")
                print(f"     {icon} {cat.capitalize()}: {count}")
        
        print("===================================================\n")

    except Exception as e:
        print(f"[ERROR] Error al listar archivos: {e}")
    finally:
        db.close()


def main() -> None:
    """Orquestación principal de SmartMule."""
    
    # Forzamos UTF-8 en la consola CMD/PowerShell para evitar errores con Emojis en Windows
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass # Para versiones de Python muy antiguas (poco probable)

    # --- CONFIGURACIÓN DE LA INTERFAZ DE COMANDOS (CLI) ---
    parser = argparse.ArgumentParser(
        description="""
+===========================================================+
|  SmartMule - El Bibliotecario Inteligente P2P             |
+===========================================================+

COMANDOS DE SERVICIO:
  start             Arranca el motor de vigilancia y organización (por defecto).
  stop              Detiene la instancia activa de SmartMule de forma segura.

HERRAMIENTAS ADMINISTRATIVAS:
  --list            Muestra un resumen detallado de la biblioteca.
  --purge [query]   Busca y elimina archivos de la BBDD y del disco físico.
  --all             (Purga) Selecciona automáticamente todos los resultados.
  --no-preserve     (Purga) Borra archivos físicos sin pedir confirmación.
  --debug           Habilita logs detallados (DEBUG) para diagnóstico.
  -h, --help        Muestra este manual de usuario.
""",
        formatter_class=argparse.RawTextHelpFormatter,
        usage="python main.py [start|stop] [opciones]",
        epilog="""
EJEMPLOS DE USO:
  > python main.py start              # Iniciar SmartMule
  > python main.py stop               # Detener SmartMule
  > python main.py --list             # Ver inventario
  > python main.py --purge "Matrix"   # Limpiar archivos por búsqueda
"""
    )
    
    # Personalizamos el mensaje de error para que sugiera el uso de --help
    def custom_error(message):
        print(f"\n\033[91m[ERROR]\033[0m {message}")
        print("[INFO] Usa --help para mas informacion.\n")
        sys.exit(2)
        
    parser.error = custom_error
    
    # Soporte para argumentos posicionales (Solo ciclo de vida del proceso)
    parser.add_argument("action", nargs="?", default="start", choices=["start", "stop"], 
                        help=argparse.SUPPRESS)
    parser.add_argument("query_pos", nargs="?", help=argparse.SUPPRESS)

    # Interfaz de Flags modernas
    parser.add_argument("--purge", nargs="?", const=True, help=argparse.SUPPRESS)
    parser.add_argument("--list", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--all", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-preserve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--debug", action="store_true", help=argparse.SUPPRESS)
    
    args = parser.parse_args()

    # 1. Acción STOP: Se puede ejecutar incluso si el Singleton está bloqueado
    if args.action == "stop":
        stop_daemon()
        sys.exit(0)

    # 2. Acción LIST: Inventario de la biblioteca
    if args.list:
        list_files()
        sys.exit(0)

    # 3. Acción PURGE: Herramienta administrativa
    if args.purge is not None:
        query = args.purge if isinstance(args.purge, str) else (args.query_pos or "")
        purge_files(query, select_all=args.all, no_preserve=args.no_preserve)
        sys.exit(0)

    # 3. Acción START: El motor principal. Requiere exclusividad (patrón de diseño Singleton)
    active_pid = get_active_pid()

    # Si ya hay un PID activo, significa que SmartMule ya se está ejecutando en segundo plano.
    if active_pid:
        print(f"\n[!] [CRITICAL] SmartMule ya esta corriendo en 2º plano (PID: {active_pid}).")
        print("\n[i] Para detenerlo antes de iniciar otra instancia, ejecuta:")
        print("> Si estás trabajando desde el proyecto: python main.py stop")
        print(f"> Si estás trabajando desde Powershell/CMD: taskkill /PID {active_pid} /F")
        print(f"> Si estás trabajando desde Linux: kill {active_pid}")
        sys.exit(1)

    # --- AUTO-INSTALACIÓN DE HERRAMIENTAS (Self-Provisioning) ---
    try:
        launcher_src = Path("Purga_Interactiva.bat")
        lib_path = Path(LIBRARY_PATH)
        if launcher_src.exists() and lib_path.exists():
            launcher_dest = lib_path / "Purga_Interactiva.bat"
            
            # Leemos la plantilla, reemplazamos la ruta y guardamos en el destino
            # Esto evita tener rutas hardcodeadas en el archivo .bat original.
            bat_content = launcher_src.read_text(encoding="utf-8")
            if "TEMPLATE_PROJECT_PATH" in bat_content:
                new_content = bat_content.replace("TEMPLATE_PROJECT_PATH", str(PROJECT_PATH))
                launcher_dest.write_text(new_content, encoding="utf-8")
                # print(f"[i] Herramienta de purga desplegada dinamicamente en: {launcher_dest}")
    except Exception as e:
        print(f"[!] No se pudo desplegar el lanzador en la biblioteca: {e}")

    # Registramos que esta instancia es la oficial
    write_pid()

    # Configuración de Logs (Nivel DEBUG si se solicita vía flag)
    log_level = "DEBUG" if args.debug else None
    setup_logging(level=log_level)

    banner = r"""+===================================+
|  SmartMule                        |
|  El Daemon Inteligente P2P        |
+===================================+"""
    print(f"\033[94m{banner}\033[0m\n")
 
    # Validación crítica de entorno (permisos, existencia de carpetas)
    if not validate_paths():
        logger.error("[ERROR] Error en la configuracion de rutas. Abortando.")
        remove_pid()
        sys.exit(1)
 
    # Info de arranque
    logger.info(f"Carpeta Incoming:   {INCOMING_PATH}")
    logger.info(f"Carpeta Library:    {LIBRARY_PATH}")
    logger.info(f"Debounce:           {DEBOUNCE_SECONDS}s")
    logger.info(f"Timeout bloqueo:    {FILE_LOCK_TIMEOUT}s")

    # Establecemos prioridad baja para que el usuario no note el proceso en su día a día
    setup_io_priority()

    # Inicialización de componentes internos
    queue_manager = QueueManager(auto_start=False) # Motor de procesamiento de cola
    watcher = SmartMuleWatcher(queue_manager) # Observador de eventos de disco

    # --- GESTIÓN DE APAGADO (Graceful Shutdown) ---
    def handle_shutdown(signum, frame):
        """Captura señales de cierre y detiene todos los hilos de forma segura."""
        logger.warning(f"\n[!] Senal de apagado ({signum}) recibida. Apagando motor...")
        watcher.stop() # Detiene el Observer de watchdog
        queue_manager.stop() # Vacía la cola y detiene el Worker thread
        remove_pid() # Limpia el archivo PID
        sys.exit(0)

    # Registramos el manejador de señales para diversos sistemas y contextos
    signal.signal(signal.SIGINT, handle_shutdown) # Ctrl+C
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, handle_shutdown) # Kill estándar Linux/Docker
    else:
        try:
            signal.signal(signal.SIGBREAK, handle_shutdown) # Ctrl+Break en Windows
        except AttributeError:
            pass

    # === 6. Escaneo de archivos existentes ===
    # Antes de empezar a vigilar en tiempo real, procesamos lo que ya hay en Incoming.
    watcher.scan_existing()

    # === 7. Procesamiento inicial ===
    # Soltamos al trabajador para que empiece a procesar la cola.
    queue_manager.start_worker()

    # Bloqueamos el hilo principal hasta que se procese lo encontrado en el scan inicial.
    # Esto asegura que los logs iniciales sean ordenados antes de entrar en modo "Vigilante".
    if not queue_manager._queue.empty():
        logger.info("🔹  Procesando archivos del escaneo inicial...")
        queue_manager._queue.join() 

    # === 8. Inicio de monitorización en tiempo real ===
    watcher.start()

    banner_final = (
        "\n=========================================================================\n"
        f"🚀 SmartMule está operativo (PID: {os.getpid()}).\n"
        "   Vigilando 'Incoming' en silencio. Usa 'python main.py stop' para detenerme.\n"
        "========================================================================="
    )
    logger.info(banner_final)

    # === 9. Bucle de vida principal ===
    # Mantenemos el hilo principal vivo mientras el observador esté activo.
    try:
        while watcher._observer.is_alive():
            watcher._observer.join(timeout=1.0) 
    except KeyboardInterrupt:
        pass
    finally:
        # Aseguramos el cierre en caso de cualquier escape del bucle
        watcher.stop()
        queue_manager.stop()
        remove_pid()

# Punto de ejecución estándar de Python
if __name__ == "__main__":
    main()
