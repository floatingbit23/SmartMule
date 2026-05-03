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
import shutil # Operaciones con archivos y directorios
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
        except OSError:
            pass

def stop_daemon():

    """
    Busca la instancia activa de SmartMule (su PID) y le envía una señal de terminación.
    Permite detener el servicio invisible de forma segura desde la consola.
    """

    pid = get_active_pid()

    if not pid:
        print("[WARN] SmartMule no está corriendo en segundo plano.")
        return

    print(f"[INFO] Deteniendo SmartMule (PID: {pid})...")

    try:
        p = psutil.Process(pid)
        p.terminate() # Envía SIGTERM (permite guardado de datos y cierre limpio)
        p.wait(timeout=5) # Esperamos a que el proceso termine
        print("[OK] SmartMule se ha detenido limpiamente.")

    except psutil.NoSuchProcess:
        print("[WARN] El proceso ya no existe.")

    except psutil.TimeoutExpired:
        print("[WARN] El proceso está tardando en cerrar. Forzando cierre (kill)...")
        p.kill() # Cierre forzoso si no responde al terminate

    except Exception as e:
        print(f"❌  Error al detener SmartMule: {e}")

    finally:
        remove_pid() # Limpia el archivo PID

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

# Función que evalúa los flags --all --no-preserve e interactúa si se pide la "DESTRUCCIÓN TOTAL".
def _check_destruction_protocol(query: str, select_all: bool, no_preserve: bool) -> tuple[bool, str]:

    # Procesamos el término de búsqueda.
    search_term = query if query else ""

    # Si no hay query, hay select_all y modo destructivo, entonces avisamos al usuario del modo DESTRUCCIÓN TOTAL.
    if not search_term and select_all and no_preserve:

        print("\n!!! ATENCION: Has activado el modo 'DESTRUCCIÓN TOTAL' (--all --no-preserve) !!!")
        print("Ejecutar este comando borrará ABSOLUTAMENTE TODOS los archivos registrados en tu BBDD.")

        # Preguntamos al usuario si está seguro de querer continuar.
        confirm_total = input("\n¿Estas COMPLETAMENTE SEGURO de querer vaciar tu biblioteca SmartMule y la carpeta Incoming? (ESCRIBE 'BORRAR TODO' para continuar): ")
        
        # Si el usuario no confirma, cancelamos la operación.
        if confirm_total != "BORRAR TODO":
            print("Operacion cancelada por seguridad.")
            return False, ""
    
        # Si confirma, devolvemos True para que el bucle principal sepa que debe borrar todo.
        return True, ""

    # Si no hay query y no hay select_all, entonces es una lista normal (sin "purga").
    elif not search_term and not select_all:

        print("\n[i] No se especificó un término de busqueda. Mostrando lista completa de archivos...")
        # Devolvemos True para que el bucle principal sepa que debe mostrar todos los archivos.
        return True, ""

    return True, search_term


# Función que muestra los resultados de la búsqueda.
def _display_candidates(results: list, no_preserve: bool) -> None:

    # Si no estamos en modo destructivo, mostramos los resultados.
    if not no_preserve:

        # Recorremos los resultados y los mostramos.
        for i, res in enumerate(results, 1):

            title = res['official_title'] if res['official_title'] else res['file_name']

            print(f"  [{i}] {title}")
            print(f"      - Origen:  {res['file_path']}")
            print(f"      - Destino: {res['final_path'] or 'No organizado'}")
            print("-" * 40) # Separador de resultados

            """
            Ejemplo: 

            [1] The Matrix
            - Origen:  /media/incoming/The.Matrix.1999.1080p.BluRay.x264.YTS.MX/the.matrix.1999.1080p.bluray.x264.yts.mx.mp4
            - Destino: /media/SmartMule/The Matrix (1999)/The Matrix (1999).mkv
            ----------------------------------------
            [2] The Matrix Reloaded
            - Origen:  /media/incoming/The.Matrix.Reloaded.2003.1080p.BluRay.x264.YTS.MX/the.matrix.reloaded.2003.1080p.bluray.x264.yts.mx.mp4
            - Destino: /media/SmartMule/The Matrix Reloaded (2003)/The Matrix Reloaded (2003).mkv
            ----------------------------------------
            """


def _parse_user_selection(choice: str, results_len: int) -> list[int]:
    choice = choice.strip().lower()
    if choice == 'all':
        return list(range(results_len))
    
    parts = [p.strip() for p in choice.split(",") if p.strip()]
    if not parts:
        raise ValueError("Entrada vacía")
        
    indices = []
    for p in parts:
        if '-' in p:
            start, end = p.split('-')
            start = int(start) - 1
            end = int(end) - 1
            if 0 <= start <= end < results_len:
                indices.extend(range(start, end + 1))
            else:
                print(f"\n[!] El rango '{p}' no es válido.")
                raise ValueError("Rango inválido")
        else:
            idx = int(p) - 1
            if 0 <= idx < results_len:
                indices.append(idx)
            else:
                print(f"\n[!] El número '{p}' no existe en la lista.")
                raise ValueError("Número inválido")
                
    return sorted(set(indices))

# Función que procesa las eliminaciones de archivos
def _process_deletions(to_delete: list, db: HashDatabase, no_preserve: bool) -> None:

    """
    Elimina físicamente los archivos seleccionados y actualiza la base de datos.

    Args:
        to_delete: Lista de archivos a eliminar.
        db: Instancia de la base de datos.
        no_preserve: Si es True, elimina sin pedir confirmación individual.
    """

    # Verificacion de seguridad
    if not no_preserve:

        confirm = input(f"\n!!! ¿Estas SEGURO de que quieres borrar fisicamente estos {len(to_delete)} archivo(s)? (s/n): ").strip().lower()
       
        if confirm != 's': # Si el usuario no confirma la eliminacion (no escribe 's')
            print("Operacion cancelada.")
            return

    # Si se ejecuta el flag --no-preserve, se salta la verificacion de seguridad
    else:
        print(f"[!] Iniciando borrado automatico de {len(to_delete)} archivos...")


    from smartmule.organizer import LibraryOrganizer
    organizer = LibraryOrganizer()

    # Bucle que procesa cada archivo seleccionado
    for i, item in enumerate(to_delete, 1):

        # Obtenemos el nombre del archivo
        file_name = item['file_name']

        print(f"\n[{i}/{len(to_delete)}] Procesando: {file_name}")

        # 1. Intentamos borrar origen
        ok_inc = organizer.purge_item(Path(item['file_path']), "Incoming")
        
        # 2. Intentamos borrar en biblioteca
        ok_lib = True
        if item.get('final_path'):
            ok_lib = organizer.purge_item(Path(item['final_path']), "Library")

        # 3. Solo borramos de la BBDD si pudimos borrar previamente de disco (o si ya no existía el archivo)
        if ok_inc and ok_lib:
            db.delete_by_ed2k(item['ed2k_hash'])
            print("  [OK] Registro eliminado de la base de datos.")
        else:
            print("  [!] El registro se mantiene en la base de datos para evitar inconsistencias.")

    print("\n [DONE] ¡Purga completada con éxito!\n")


# Función principal para buscar archivos y mostrar resultados
def search_files(query: str) -> None:

    """
    Usa el motor de búsqueda inteligente (FTS5) para mostrar resultados en consola.
    """

    print(f"\n[SEARCH] Buscando: '{query}'...")
    
    # Me conecto a la base de datos
    db = HashDatabase(DB_PATH)
    
    try:
        # Buscamos archivos usando el término de búsqueda.
        results = db.search_by_name(query)
        
        if not results:
            if not query:
                print("\n[i] No tienes archivos registrados en la base de datos de SmartMule!\n")
            else:
                print("\n[!] No se encontraron archivos que cumplan esos criterios.\n")
            return

        print(f"\n[OK] Se han encontrado {len(results)} coincidencia(s):\n")

        # Cabecera de la tabla de resultados (Ajustada para incluir resolución en TIPO)
        print(f"{'ID':<4} | {'TIPO':<18} | {'TÍTULO / NOMBRE DE ARCHIVO':<47} | {'SCORE':<6} | {'ESTADO'}")
        
        # Separador
        print("-" * 100)

        for item in results:

            media_type = item.get('media_type', 'unknown').upper()
            
            # Mostramos la resolución solo para los tipos de vídeo ("MOVIE", "SERIES", "VIDEO")
            res = item.get('resolution')

            if media_type in ["MOVIE", "SERIES", "VIDEO"] and res:
                media_type = f"{media_type} ({res})"

            title = item.get('official_title') or item.get('file_name', 'Unknown')

            # Visualización de puntuación con 2 decimales para evitar discrepancias con los filtros
            val = item.get('score', 0.0)
            score = f"{val:.2f}" if item.get('score') is not None else "N/A"

            status = "ORG" if item.get('is_organized') else "PEN"
            
            # Truncamos el título si es muy largo
            if len(title) > 44:
                title = title[:41] + "..."
                
            print(f"{item['id']:<4} | {media_type:<18} | {title:<47} | {score:<6} | {status}")
            
        print(f"\n[DONE] Total: {len(results)} archivos encontrados.\n")

    except Exception as e:
        print(f"\n[ERR] Error durante la búsqueda: {e}\n")
        
    finally:
        db.close()


# Función principal para purgar archivos
def purge_files(query: str, select_all: bool = False, no_preserve: bool = False) -> None:

    """
    Lógica de los flags "--purge" y "--all": Ejecuta el protocolo de limpieza sincronizada de archivos y base de datos.
    
    Args:
        query: Patrón de búsqueda (Soporta Regex y Wildcards).
        select_all: Si es True, selecciona automáticamente todos los resultados.
        no_preserve: Si es True, borra sin pedir confirmación individual (Modo Destructivo).
    """

    # Verificacion de seguridad
    success, search_term = _check_destruction_protocol(query, select_all, no_preserve)

    if not success:
        return

    print("\n[SEARCH] Buscando archivos para purgar...")

    # Me conecto a la base de datos
    db = HashDatabase(DB_PATH)

    try:

        # Buscamos archivos usando el término de búsqueda (puede ser vacío para buscar todos).
        results = db.search_by_name(search_term)
        
        # Si la BBDD no devuelve resultados
        if not results:

            if not search_term:
                print("\n[i] No tienes archivos registrados en la base de datos de SmartMule!\n")
            else:
                print(f"\n[-] No se encontraron archivos que coincidan con '{search_term}'.\n")
            return

        print(f"\n[OK] Se han encontrado {len(results)} coincidencia(s):\n")

        _display_candidates(results, no_preserve)

        to_delete = [] # Lista para almacenar los archivos seleccionados por el usuario para ser eliminados.

        # Si estamos en modo destructivo, seleccionamos todos los resultados.
        if select_all:
            to_delete = results

        # Si no estamos en modo destructivo, pedimos al usuario que seleccione los archivos a eliminar.
        else:
            choice = input("\nSelección [ej: 1, 3-5] (o 'all'/'quit'): ").strip().lower()
            if choice == 'quit':
                return
            
            try:
                indices = _parse_user_selection(choice, len(results))
                to_delete = [results[i] for i in indices]
            except ValueError:
                print("\n[!] Entrada no válida. Usa números separados por comas (ej: 1, 3) o rangos (ej: 1-3).")
                return

        # Procesamos las eliminaciones.
        _process_deletions(to_delete, db, no_preserve)

    except Exception as e:
        print(f"[ERROR] Error durante la purga: {e}")
        
    finally:
        db.close() # Siempre cerramos la conexión a la BBDD

# Función para forzar un nuevo escaneo completo.
def reprocess_files(query: str, select_all: bool = False) -> None:

    """
    Invalida los metadatos de archivos para forzar un nuevo escaneo completo.
    Borra el registro de la BBDD y el hardlink en la biblioteca, permitiendo
    que el Watcher vuelva a encontrar el archivo en Incoming/ como nuevo.
    """

    db = HashDatabase(DB_PATH)
    try:
        # Buscamos archivos usando el término de búsqueda
        results = db.search_by_name(query) if query else db.get_all_files()
        
        if not results:
            if not query:
                print("\n[i] No hay archivos registrados para re-procesar.\n")
            else:
                print(f"\n[-] No se encontraron archivos que coincidan con '{query}'.\n")
            return

        print(f"\n[SEARCH] Se han encontrado {len(results)} coincidencia(s) para re-procesar:\n")
        
        # Mostramos los resultados en una tabla
        _display_candidates(results, select_all)

        # Lista para almacenar los archivos seleccionados por el usuario para ser re-procesados.
        to_reprocess = []

        if select_all:
            to_reprocess = results

        else:
            choice = input("\nSelección para RE-PROCESAR [ej: 1, 3-5] (o 'all'/'quit'): ").strip().lower()

            if choice == 'quit':
                return

            if choice == 'all':
                to_reprocess = results

            else:

                try:
                    indices = _parse_user_selection(choice, len(results))
                    to_reprocess = [results[i] for i in indices]

                except ValueError:
                    print("\n[!] Entrada no válida.")
                    return


        if not to_reprocess:
            return


        print(f"\n[*] Iniciando re-procesamiento de {len(to_reprocess)} archivos...")
        
        for row in to_reprocess:

            # Obtenemos los datos del archivo.
            ed2k = row['ed2k_hash']
            clean_name = row['official_title'] or row['file_name']
            lib_path = row['final_path']
            
            # Mostramos los archivos que se van a re-procesar.
            # Ejemplo: 🔄 [sf3dg01] Matrix
            print(f"  🔄 [{ed2k[:8]}] {clean_name}")
            
            # Eliminamos el archivo de la BBDD y Caché (usando el Hash Completo)
            db.delete_by_ed2k(ed2k)
            
            # 2. Eliminar el archivo en Library si existe (rompemos el Hard Link)
            physical_ok = True

            if lib_path:
                from smartmule.organizer import LibraryOrganizer
                organizer = LibraryOrganizer()
                physical_ok = organizer.purge_item(Path(lib_path), "Library")
            
            if not physical_ok:
                logger.warning(f"[REPROCESS] Registro eliminado, pero el archivo en Library sigue bloqueado: {clean_name}")
                print("  [!] Nota: El registro se borró, pero no se pudo eliminar el archivo físico de la Library (posiblemente esté en uso / Seeding).")


        print(f"\n✅ {len(to_reprocess)} archivos invalidados correctamente.")
        print("ℹ️  SmartMule los identificará de nuevo al detectarlos en 'Incoming'.")
        print("💡 Importante!!! -> Ejecuta 'smartmule restart' para forzar el re-escaneo.")


    except Exception as e:
        print(f"[ERROR] Error durante el re-procesamiento: {e}")
    finally:
        db.close()



def show_stats() -> None:
    """
    Muestra el inventario de la biblioteca y estadísticas de almacenamiento.
    """
    db = HashDatabase(DB_PATH)
    try:
        stats = db.get_stats()
        files = db.get_all_files()

        print("\n===================================================")
        print("          SmartMule: Inventario de Biblioteca")
        print("===================================================")
        
        CATEGORY_ICONS = {
            "movie": "🎬",
            "video": "🎥",
            "series": "📺",
            "audio": "🎵",
            "book": "📚",
            "document": "📄",
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
        
        # Calculamos el tamaño total en GB (Bytes / 1024^3)
        total_gb = stats.get("total_size", 0) / (1024**3)
        print(f"  💾 Espacio total organizado: {total_gb:.2f} GB")
        
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


def show_config() -> None:
    """
    Muestra la configuración actual cargada en SmartMule de forma legible.
    """
    from smartmule import config
    
    print("\n===================================================")
    print("          SmartMule: Configuración Activa")
    print("===================================================")
    
    print("\n📂  RUTAS DEL SISTEMA:")
    print(f"   - Proyecto: {config.PROJECT_PATH}")
    print(f"   - Incoming: {config.INCOMING_PATH}")
    print(f"   - Library:  {config.LIBRARY_PATH}")
    print(f"   - Database: {config.DB_PATH}")
    
    print("\n📊  PARAMETROS DE OPERACION:")
    print(f"   - Modo Organizador: {config.ORGANIZER_MODE.upper()}")
    print(f"   - Debounce (FS):   {config.DEBOUNCE_SECONDS}s")
    print(f"   - Log Level:       {config.LOG_LEVEL}")
    
    print("\n🤖 INTELIGENCIA ARTIFICIAL:")

    # Si se usa el LLM local, se muestra su URL. Si no, se muestra que se está usando Gemini.
   
    status_llm = "✅  ACTIVO (Local)" if config.USE_LOCAL_LLM else "☁️  CLOUD (Gemini)"
    
    print(f"   - Modo IA: {status_llm}")

    if config.USE_LOCAL_LLM:
        print(f"   - URL Local:  {config.LOCAL_LLM_URL}")
    
    print("\n🔑  API KEYS (Estado):")
    
    # Método para enmascarar claves (por seguridad)
    def mask(key):
        if not key: return "❌  No configurada"

        # Si es una clave corta (como la de Hugging Face en modo local) se muestra entera.
        if len(key) < 10: return "✅  Configurada (Oculta)"
        
        return f"✅  Configurada ({key[:4]}...{key[-4:]})"
    
    # Imprime las claves enmascaradas.
    print(f"   - TMDB Token:    {mask(config.TMDB_BEARER_TOKEN)}")
    print(f"   - Gemini Key:    {mask(config.GEMINI_API_KEY)}")
    print(f"   - VirusTotal:    {mask(config.VIRUSTOTAL_API_KEY)}")
    
    print("\n===================================================\n")


def show_status() -> None:
    """
    Muestra un estado detallado del servicio y herramientas de SmartMule.
    """

    import subprocess
    from smartmule import config
    
    print("\n===================================================")
    print("          SmartMule: Estado del Sistema")
    print("===================================================")
    
    # 1. Estado del Servicio
    pid = get_active_pid()
    if pid:
        print(f"\n[i] SERVICIO: Activo (PID: {pid})")
    else:
        print("\n[!] SERVICIO: Inactivo")
        
    # 2. Verificación de Herramientas Externas
    print("\n[i] DEPENDENCIAS:")
    
    # Función para verificar si una herramienta está instalada
    def check_tool(name, cmd):

        path = shutil.which(cmd) # Busca la herramienta en el PATH del sistema
        
        # Muestra el estado de la herramienta
        status = f"✅  Encontrado ({path})" if path else "❌  NO ENCONTRADO (Instalalo para soporte completo)"
        print(f"   - {name:10}: {status}")
        
    check_tool("FFmpeg", "ffprobe")
    check_tool("7-Zip", "7z")
    
    # 3. Verificación de Rutas y Permisos
    print("\n📂  ESTADO DE RUTAS:")
    def check_path(name, path):
        if not path.exists():
            status = "❌  NO EXISTE"
        else:
            readable = os.access(path, os.R_OK)
            writable = os.access(path, os.W_OK)
            if readable and writable:
                status = "✅  OK (Lectura/Escritura)"
            elif readable:
                status = "⚠️  Solo Lectura"
            else:
                status = "❌  SIN ACCESO"
        
        print(f"   - {name:10}: {status}")
        
    check_path("Incoming", config.INCOMING_PATH)
    check_path("Library", config.LIBRARY_PATH)
    check_path("Database", config.DB_PATH.parent) # Comprobamos la carpeta oculta de la DB
    
    print("\n===================================================\n")


def show_last_logs(lines: int = 30) -> None:
    """
    Muestra las últimas N líneas del archivo de log de forma eficiente.
    """
    from smartmule.config import BASE_DIR
    import collections
    
    log_file = BASE_DIR / "smartmule.log"
    
    if not log_file.exists():
        print("\n[!] Aun no se ha generado el archivo 'smartmule.log'.")
        return

    print(f"\n[i] Mostrando las ultimas {lines} lineas del log:\n")
    print("-" * 70)
    
    try:
        # Usamos deque con maxlen para leer solo las últimas líneas sin cargar el archivo entero en RAM
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:

            # Leemos las ultimas N lineas.
            last_lines = collections.deque(f, maxlen=lines)

            for line in last_lines:
                # Quitamos el salto de línea doble que pueda venir del log
                print(line.strip())

    except Exception as e:
        print(f"❌ Error al leer el log: {e}")
    
    print("-" * 70 + "\n")


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
  restart           Reinicia el servicio SmartMule (Stop + Start).

HERRAMIENTAS DE BÚSQUEDA:
  --search [query]  Realiza una búsqueda inteligente (FTS5) y filtrada en la biblioteca.
  --purge [query]   Busca y elimina archivos de la BBDD y del disco físico.
  --reprocess [q]   Invalida metadatos para forzar un nuevo análisis (Regex/IA/API).
    --all                 (Purga/Reprocess) Selecciona automáticamente todos los resultados.
    --no-preserve         (Purga) Borra archivos físicos sin pedir confirmación.

HERRAMIENTAS ADMINISTRATIVAS:
  --stats           Muestra un resumen detallado e inventario de la biblioteca.
  --config          Muestra la configuración activa (rutas, APIs, etc.).
  --status          Realiza un chequeo de salud y dependencias del sistema.
  --log [N]         Muestra las ultimas N lineas del log (por defecto 30).
  --pid             Muestra el PID del proceso activo de SmartMule.
  --debug           Habilita logs detallados (DEBUG) para diagnóstico.
  -h, --help        Muestra este manual de usuario.
""",
        formatter_class=argparse.RawTextHelpFormatter,
        usage="smartmule [start|stop] [opciones]",
        epilog="""
EJEMPLOS DE USO:
  > smartmule start              # Iniciar SmartMule
  > smartmule stop               # Detener SmartMule
  > smartmule --search "Matrix"  # Buscar archivos por título o nombre
  > smartmule --search "type:movie score>8" # Búsqueda avanzada con filtros
  > smartmule --stats            # Ver inventario y estadísticas
  > smartmule --status           # Chequear salud del sistema
  > smartmule --config           # Ver configuración activa
  > smartmule --log 50           # Ver ultimas 50 lineas del log
  > smartmule --pid              # Ver PID activo
  > smartmule --purge "Matrix"   # Limpiar archivos por búsqueda
  > smartmule --reprocess "Titanic" # Forzar re-análisis del archivo de la película Titanic
\n"""
    )
    
    # Personalizamos el mensaje de error para que sugiera el uso de --help
    def custom_error(message):
        print(f"\n\033[91m[ERROR]\033[0m {message}")
        print("[INFO] Usa --help para mas informacion.\n")
        sys.exit(2)
        
    parser.error = custom_error
    
    # Soporte para argumentos posicionales (Solo ciclo de vida del proceso)
    parser.add_argument("action", nargs="?", default="start", choices=["start", "stop", "restart"], 
                        help=argparse.SUPPRESS)
    parser.add_argument("query_pos", nargs="?", help=argparse.SUPPRESS)

    # Interfaz de Flags modernas
    parser.add_argument("--search", nargs="?", const=True, help=argparse.SUPPRESS)
    parser.add_argument("--purge", nargs="?", const=True, help=argparse.SUPPRESS)
    parser.add_argument("--reprocess", nargs="?", const=True, help=argparse.SUPPRESS)
    parser.add_argument("--stats", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--config", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--status", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--log", nargs="?", type=int, const=30, help=argparse.SUPPRESS)
    parser.add_argument("--pid", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--all", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-preserve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--debug", action="store_true", help=argparse.SUPPRESS)
    
    args = parser.parse_args()

    # 1. Acción STOP / RESTART (Fase de parada)
    if args.action in ["stop", "restart"]:

        stop_daemon()

        # Si es "stop", salimos
        if args.action == "stop":
            sys.exit(0)
        
        # Si es "restart", damos un pequeño respiro antes de continuar al arranque
        import time
        time.sleep(2)

    # 2. Acción STATS: Inventario y estadísticas
    if args.stats:
        show_stats()
        sys.exit(0)

    # 2.2 Acción CONFIG: Mostrar configuración
    if args.config:
        show_config()
        sys.exit(0)

    # 2.3 Acción STATUS: Chequeo de salud
    if args.status:
        show_status()
        sys.exit(0)
    
    # 2.4 Acción LOG: Últimas N líneas del Log
    if args.log is not None:
        num_lines = args.log if isinstance(args.log, int) else 30
        show_last_logs(num_lines)
        sys.exit(0)

    # 2.5 Acción PID: Mostrar PID activo
    if args.pid:
        pid = get_active_pid()
        if pid:
            print(f"\n[i] SmartMule está activo (PID: {pid})\n")
        else:
            print("\n[!] SmartMule no está en ejecución.\n")
        sys.exit(0)

    # 2.6 Acción SEARCH: Motor de búsqueda inteligente
    if args.search is not None:
        query = args.search if isinstance(args.search, str) else (args.query_pos or "")
        search_files(query)
        sys.exit(0)

    # 3. Acción PURGE: Herramienta administrativa
    if args.purge is not None:

        # Si no se proporciona una consulta, se intenta usar la posición
        query = args.purge if isinstance(args.purge, str) else (args.query_pos or "")

        purge_files(query, select_all=args.all, no_preserve=args.no_preserve)
        sys.exit(0)

    # 4. Acción REPROCESS: Invalidad metadatos y caché
    if args.reprocess is not None:
        query = args.reprocess if isinstance(args.reprocess, str) else (args.query_pos or "")
        reprocess_files(query, select_all=args.all)
        sys.exit(0)

    # 3. Acción START: El motor principal. Requiere exclusividad (patrón de diseño Singleton)
    active_pid = get_active_pid()

    # Si ya hay un PID activo, significa que SmartMule ya se está ejecutando en segundo plano.
    if active_pid:
        print(f"\n[!] [CRITICAL] SmartMule ya esta corriendo en 2º plano (PID: {active_pid}).")
        print("\n[i] Para detenerlo antes de iniciar otra instancia, ejecuta:")
        print("> Si estás en el proyecto: python3 main.py stop")
        print("> Si usas el alias: smartmule stop")
        print(f"> Si estás trabajando desde Powershell/CMD: taskkill /PID {active_pid} /F")
        print(f"> Si estás trabajando desde Linux: kill {active_pid}")
        sys.exit(1)

    # Validación crítica de entorno (permisos, existencia de carpetas)
    if not validate_paths():
        logger.error("[ERROR] Error en la configuracion de rutas. Abortando.")
        remove_pid()
        sys.exit(1)

    # --- AUTO-INSTALACIÓN DE HERRAMIENTAS (Self-Provisioning) ---
    try:
        # Detectamos el SO para desplegar solo el lanzador adecuado
        if sys.platform == "win32":
            launchers = [
                ("Purga_Interactiva.bat", "Purga_Interactiva.bat"),
                ("smartmule_launcher.vbs", "smartmule_launcher.vbs")
            ]
        else:
            launchers = [
                ("purga_interactiva.sh", "purga_interactiva.sh"),
                ("smartmule_launcher.sh", "smartmule_launcher.sh")
            ]
        lib_path = Path(LIBRARY_PATH)
        if lib_path.exists():
            for src_name, dest_name in launchers:
                src_file = BASE_DIR / src_name
                if src_file.exists():
                    dest_file = lib_path / dest_name
                    
                    # Leemos la plantilla, reemplazamos la ruta y guardamos en el destino
                    content = src_file.read_text(encoding="utf-8")
                    if "TEMPLATE_PROJECT_PATH" in content:
                        new_content = content.replace("TEMPLATE_PROJECT_PATH", str(PROJECT_PATH))
                        dest_file.write_text(new_content, encoding="utf-8")
                        
                        # Si es un script de Linux y no estamos en Windows, damos permisos de ejecución
                        if dest_name.endswith(".sh") and sys.platform != "win32":
                            try:
                                dest_file.chmod(0o755)
                            except Exception:
                                pass

    except Exception as e:
        print(f"[!] No se pudo desplegar los lanzadores en la biblioteca: {e}")

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
    def handle_shutdown(signum, _frame):
        """Captura señales de cierre y detiene todos los hilos de forma segura."""
        logger.warning(f"\n[!] Señal de apagado ({signum}) recibida. Apagando motor...")
        watcher.stop() # Detiene el Observer de watchdog
        queue_manager.stop() # Vacía la cola y detiene el Worker thread
        remove_pid() # Limpia el archivo PID
        sys.exit(0)

    # Registramos el manejador de señales para diversos sistemas y contextos
    signal.signal(signal.SIGINT, handle_shutdown) # Ctrl+C

    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, handle_shutdown) # Kill estándar Linux/Docker

    else:
        # En Windows, Ctrl+C no es suficiente para detener el programa, por lo que usamos Ctrl+Break
        try:
            signal.signal(signal.SIGBREAK, handle_shutdown)
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
