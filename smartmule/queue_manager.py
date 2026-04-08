"""
Cola de prioridad con trabajador único (Single Worker) para SmartMule.

Implemento el patrón Producer-Consumer para evitar que múltiples descargas completadas simultáneamente saturen el disco duro.

1. El Watcher (Producer) detecta archivos nuevos y los mete en una cola de prioridad (PriorityQueue).
2. La cola de prioridad ordena los archivos por orden de importancia*.
3. Un único hilo trabajador (Consumer) saca los archivos de la cola y los procesa uno por uno.

*Uso una PriorityQueue para que los archivos pequeños (PDFs, ebooks...) se procesen antes que las películas de 20 GB.
Esto da la sensación de que SmartMule es rápido, porque los archivos pequeños se organizan en milisegundos mientras los grandes esperan su turno sin molestar.
"""

import os
import time
import logging
from datetime import datetime
import threading
from queue import PriorityQueue
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from smartmule.hasher import calculate_ed2k, format_ed2k_link, calculate_fingerprint
from smartmule.database import HashDatabase
from smartmule.config import DB_PATH
from smartmule.metadata_engine import MetadataEngine
from smartmule.organizer import LibraryOrganizer

# Creo un logger específico para este módulo.
logger = logging.getLogger("SmartMule.queue_manager")

# === Umbrales de tamaño para asignar prioridades ===
SIZE_SMALL = 50 * 1024 * 1024       # 50 MB — archivos "instantáneos"
SIZE_MEDIUM = 1024 * 1024 * 1024    # 1 GB — archivos medianos
SIZE_LARGE = 5 * 1024 * 1024 * 1024  # 5 GB — archivos grandes

# Conjunto de extensiones que considero ejecutables y que necesitan triaje de seguridad urgente
# Les doy prioridad alta independientemente de su tamaño
EXECUTABLE_EXTENSIONS: set = {".exe", ".msi", ".bat", ".cmd", ".com", ".scr"}

@dataclass(order=True) # @dataclass es una herramienta que permite crear clases de forma rápida y sencilla 
class FileTask: 

    """
    Represento una tarea de procesamiento de archivo en la cola de prioridad.

    Dataclass compuesto por:
    - Prioridad numérica
    - Ruta completa al archivo
    - Tamaño del archivo en bytes
    - Timestamp de cuando puse el archivo en la cola

    Uso @dataclass(order=True) para que Python compare las instancias automáticamente. 
    Con compare=False en todos los campos excepto 'priority', me aseguro de que la PriorityQueue ordene SOLO por prioridad numérica.
    """

    # La prioridad numérica (del 1 al 5): menor número = se procesa primero
    priority: int

    # Ruta completa al archivo. No participa en la comparación de orden
    file_path: str = field(compare=False)

    # Tamaño del archivo en bytes. Lo guardo para logging y para la lógica de implementaciones posteriores (ej: buffer de lectura para hashing)
    file_size: int = field(compare=False)

    # Timestamp de cuando puse el archivo en la cola
    # Me sirve para medir latencias y detectar archivos que llevan mucho tiempo esperando
    enqueued_at: float = field(compare=False, default_factory=time.time)

# Clase que gestiona la PriorityQueue y el Worker Thread que procesa archivos.
class QueueManager:

    """
    Gestiona la cola de prioridad y el Worker Thread que procesa archivos.

    La clase garantiza que:
    1. Los archivos se procesen UNO POR UNO (nunca en paralelo).
    2. Los archivos pequeños tengan prioridad sobre los grandes.
    3. Los ejecutables se procesen con urgencia (medida de seguridad).
    4. El Worker Thread se pueda detener limpiamente con stop().
    """

    # Constructor de la clase QueueManager
    def __init__(self, process_callback: Optional[Callable] = None, auto_start: bool = True):

        """
        Inicializo la cola de prioridad, la base de datos SQLite y arranco el Worker Thread.

        process_callback: Función opcional para procesar cada archivo.
        Si es None, uso el pipeline real (hasher ED2K + caché SQLite).
        """

        # La PriorityQueue de Python es thread-safe por defecto (no necesito locks adicionales para put() y get()).
        self._queue: PriorityQueue = PriorityQueue() # Instancio la clase PriorityQueue

        # Lock para proteger el acceso al conjunto de rutas activas.
        self._lock = threading.Lock() # Instancio la clase Lock

        # Conjunto de archivos que ya están en la cola o siendo procesados actualmente.
        # Lo uso para evitar duplicados si el Watcher y el Scan Inicial detectan lo mismo.
        self._active_paths: set[str] = set()

        # Abro la BBDD SQLite de caché con la ruta preconfigurada en config.py. 
        # Se crea automáticamente si no existe.
        self._db = HashDatabase(DB_PATH) # Instancio la clase HashDatabase

        # Guardo el callback de procesamiento.
        # Si se pasa un callback externo (útil para tests), lo uso. Si no, uso el pipeline real.
        self._process_callback = process_callback or self._process_file

        # Flag para señalar al Worker que debe detenerse. Uso un Event en vez de un bool simple porque es thread-safe.
        self._stop_event = threading.Event() # Instancio la clase Event

        # Creo el Worker Thread como daemon (hilo secundario) para que no impida que el programa principal termine si algo sale mal.
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="SmartMule-Worker",
            daemon=True,
        )

        if auto_start:
            self.start_worker()

    def start_worker(self) -> None:
        """Arranca el Worker Thread si no está ya en ejecución."""
        if not self._worker_thread.is_alive():
            self._worker_thread.start() 
            logger.info("Worker iniciado. Atendiendo archivos en la cola...")


    # Método para meter archivos en la cola
    def enqueue(self, file_path: Path) -> None:
        """
        Encolo un archivo para su procesamiento. 
        Calculo su prioridad  basándome en el tamaño y la extensión, creo un FileTask y lo meto en la PriorityQueue.

        Args:
            file_path: Ruta completa al archivo que quiero procesar.
        """

        # Normalizo la ruta para que el chequeo de duplicados sea exacto.
        abs_path = str(file_path.resolve())

        with self._lock:
            # Si el archivo ya está en la cola o siendo procesado, lo ignoro silenciosamente.
            if abs_path in self._active_paths:
                return
            
            # Registro el archivo como "activo".
            self._active_paths.add(abs_path)

        try:
            # Obtengo el tamaño. Si es carpeta, sumo el tamaño de todo el contenido.
            if file_path.is_dir():
                file_size = sum(f.stat().st_size for f in file_path.rglob('*') if f.is_file())
            else:
                file_size = file_path.stat().st_size

        except OSError as e:
            # Si no puedo obtener el tamaño (por lo que sea), lo registro y aborto. 
            logger.error(
                f"❌  No pude obtener información de '{file_path.name}': {e}. "
                f"Abortando encolado..."  # No tiene sentido meter en la cola algo que no puedo leer.
            )
            return

        # Calculo la prioridad basándome en las reglas definidas en _calculate_priority().
        priority = self._calculate_priority(file_path, file_size)

        # Creo la tarea con toda la información necesaria.
        task = FileTask(
            priority=priority,
            file_path=str(file_path),
            file_size=file_size,
        )

        # Meto la tarea en la cola, put() es thread-safe (usa Lock interno) y tiene en cuenta la prioridad de la tarea.
        self._queue.put(task)

        # Formateo el tamaño para que sea legible en los logs.
        size_str = self._format_size(file_size)

        logger.info(
            f"✅ Encolado [P{priority}]: {file_path.name} ({size_str}) "
            f"— {self.pending_count} tarea(s) en cola"
        )


    # Método para calcular la prioridad del archivo (retorna un número entre 1 y 5)
    def _calculate_priority(self, file_path: Path, file_size: int) -> int:

        """
        Asigno una prioridad numérica al archivo. Menor número = más urgente.

        Mi lógica de priorización es la siguiente:

        - P1: Archivos pequeños (< 50 MB) — PDFs, ebooks, imágenes, vídeos cortos, música, subtítulos...
            Se hashean en milisegundos, el usuario los ve organizados al instante.

        - P2: Ejecutables de cualquier tamaño — necesitan auditoría de seguridad urgente.

        - P3: Archivos medianos (50 MB a 1 GB) — episodios de series, vídeos largos...

        - P4: Archivos grandes (1 GB a 5 GB) — películas 720p/1080p...

        - P5: Archivos muy grandes (> 5 GB) — películas 4K, ISOs...

        Args:
            file_path: Ruta al archivo (necesito la extensión).
            file_size: Tamaño en bytes del archivo.

        Returns:
            Prioridad numérica (1-5).
        """

        extension = file_path.suffix.lower() # Obtengo la extensión del archivo y la convierto a minúsculas.

        # Los ejecutables siempre van con prioridad 2, sin importar su tamaño.
        if extension in EXECUTABLE_EXTENSIONS:
            return 2 # Prioridad alta

        # Para el resto, la prioridad depende del tamaño.
        if file_size < SIZE_SMALL:
            return 1   # Prioridad máxima
        elif file_size < SIZE_MEDIUM:
            return 3   # Prioridad media
        elif file_size < SIZE_LARGE:
            return 4   # Prioridad baja
        else:
            return 5   # Prioridad mínima


    # Bucle principal del Worker Thread
    def _worker_loop(self) -> None:

        """
        Bucle principal del Worker Thread. 
        Saco tareas de la PriorityQueue una por una y las proceso secuencialmente (una a la vez). 
        Uso get() con timeout (1s) para poder comprobar periódicamente si debo detenerme.

        Este hilo es el ÚNICO que procesará archivos. 
        Nunca hay dos archivos procesándose en paralelo, lo cual es más respetuoso con el HDD/SSD.
        """

        logger.debug("ℹ️  Worker loop arrancado")

        # Mientras no se reciba la señal de parada, el Worker intentará sacar tareas de la cola.
        while not self._stop_event.is_set():

            try:
                # Intento sacar una tarea de la cola con un timeout de 1 segundo.
                task = self._queue.get(timeout=1.0)
                # Si la cola está vacía, get() se bloquea durante 1s y luego vuelvo a comprobar stop_event. 
                # Así puedo detenerme limpiamente.

            except Exception:
                # Si la cola está vacía y se agotó el timeout, simplemente vuelvo al principio del bucle.
                continue

            # Si recibo None (el centinela) como tarea, es la señal de parada.
            # Esto me permite hacer un shutdown limpio.

            if task is None:
                logger.debug("ℹ️  Worker recibió señal de parada (centinela)")
                self._queue.task_done() # Marco la tarea como completada
                break # Salgo del bucle


            # Proceso la tarea:

            # Capturo cualquier excepción para que un error en un archivo no mate al worker y deje de procesar el resto.
            try:
                self._process_callback(task)

            except Exception as e:

                logger.error(
                    f"❌  Error procesando '{Path(task.file_path).name}': {e}",
                    exc_info=True, # Muestro el traceback completo
                )

            # Bloque finally: se ejecuta SIEMPRE, tanto si hubo error como si no.
            finally: 
                # Pase lo que pase, libero la ruta del registro de activos.
                with self._lock:
                    # task puede ser None si falló el get(), pero aquí ya sabemos que es un FileTask
                    if task is not None:
                        abs_path = str(Path(task.file_path).resolve())
                        self._active_paths.discard(abs_path)

                self._queue.task_done() # Marco la tarea como completada (necesario para que join() funcione correctamente)

        # Cuando el bucle termina (porque stop_event está activo), salgo del método.
        logger.info("ℹ️  Worker detenido limpiamente")


    # Método que procesa el archivo
    def _process_file(self, task: FileTask) -> None:

        """
        Pipeline de procesamiento del archivo. De momento lo que hace es:
        1. Comprueba la caché por Huella Digital (Fingerprint) para evitar hashing completo.
        2. Si no está en caché, calcula el hash ED2K completo.
        3. Guarda el hash en la BBDD y la huella en la caché (entrada de SQLite).

        En implementaciones posteriores se añadirán aquí las fases de IA y APIs de metadatos.

        Args:
            task: La tarea (FileTask) de archivo a procesar.
        """

        # Obtengo los atributos del archivo
        file_path = Path(task.file_path)
        file_name = file_path.name
        size_str = self._format_size(task.file_size)

        # Calculo el tiempo que el archivo ha estado en cola
        wait_time = time.time() - task.enqueued_at 

        logger.info(
            f"ℹ️  Procesando [P{task.priority}]: {file_name} ({size_str}) "
            f"— esperó {wait_time:.2f}s en cola"
        )


        # === FASE 1: Comprobación de Caché por Fingerprint ===
        
        # Calculo la Fast-Fingerprint (primeros 256KB y últimos 256KB).
        fingerprint = calculate_fingerprint(file_path, task.file_size)

        if not fingerprint:
            logger.error(f"❌ No se pudo generar la huella digital de {file_name}. Abortando...")
            return

        # Consulto a la BBDD si ya conocemos este contenido exactamente (por su huella).
        existing = self._db.get_by_fingerprint(fingerprint, task.file_size)

        # Guardamos si estamos forzando el re-análisis por mtime
        force_rehash = False

        if existing: # Si existe contenido conocido por Fingerprint
            
            # Verificamos si realmente se completó el enriquecimiento y la organización
            actual_mtime = int(file_path.stat().st_mtime)
            cached_mtime = existing.get('file_mtime', 0)

            if existing.get('is_organized', 0) == 1 and existing.get('security_verdict') != '':
                
                # Si el mtime NO coincide, el archivo fue manipulado desde la última vez.
                # Lo marcamos para recalcular el hash pero intentando ahorrar APIs si el hash es el mismo.
                if actual_mtime != cached_mtime:
                    logger.info(f"⚠️  Detectado cambio en la fecha de modificación de {file_name}. Verificando integridad del hash...")
                    force_rehash = True # Vamos a la Fase 2, pero con cautela.
                
                else:
                    ed2k_hash = existing['ed2k_hash']
                    ed2k_link = existing['ed2k_link']
                    processed_at_raw = existing['processed_at']

                    # Formateo la fecha
                    try:
                        dt = datetime.fromisoformat(processed_at_raw)
                        processed_at = dt.strftime("%d/%m/%Y %H:%M:%S")
                    except Exception:
                        processed_at = processed_at_raw 

                    logger.info(f"✅  Contenido reconocido (Fingerprint + MTime) y completamente organizado.")
                    logger.info(f"🔹  Hash ED2K: {ed2k_hash}")
                    logger.info(f"🔹  Link: {ed2k_link}")
                    logger.info(f"ℹ️  Archivo en su ruta final: {existing.get('final_path')}")
                    return 

            else:
                logger.info(f"ℹ️  El archivo con fingerprint [{fingerprint[:8]}] ya existe, pero faltan metadatos o no fue organizado. Forzando re-análisis completo...")
                # Continuamos a la Fase 2 sin optimización (re-proceso total).


        # === FASE 2: Hashing ED2K ===

        # Calculamos el hash ED2K completo (necesario siempre que no estemos en la ruta de retorno rápido del principio).

        logger.info(f"🔹  Calculando hash ED2K de: {file_name}...")
        hash_start = time.time() 

        # Calculo el hash ED2K completo.
        ed2k_hash = calculate_ed2k(file_path)

        # Lógica de tiempo transcurrido
        elapsed = time.time() - hash_start
        mins, secs = divmod(int(elapsed), 60)
        elapsed_str = f"{mins}min {secs}s" if mins > 0 else f"{secs}s"

        logger.info(f"✅  Hash ED2K calculado en {elapsed_str}: {ed2k_hash}")

        # Genero el enlace ED2K estándar.
        ed2k_link = format_ed2k_link(file_path, task.file_size, ed2k_hash)
        logger.info(f"🔹  Link: {ed2k_link}")

        # --- OPTIMIZACIÓN POR MTIME (Ahorro de APIs) ---

        # Si se detectó cambio de mtime (timestamp de modificación del archivo), pero su hash ED2K es el mismo y existe un registro previo:
        if force_rehash and existing and ed2k_hash == existing['ed2k_hash']:

            logger.info("✅  Integridad confirmada: El contenido no ha variado a pesar de la modificación del archivo.")
            logger.info("ℹ️  Reutilizando metadatos existentes...")
            
            # Actualizamos la BBDD solo con el nuevo mtime y timestamp de procesado del archivo
            self._db.save(file_path, task.file_size, fingerprint, ed2k_hash, ed2k_link)

            logger.info(f"ℹ️  Fecha de registro actualizada para {file_name}. Proceso optimizado finalizado.")

            return 

        # === FASE 3: Persistencia Inicial en Caché ===

        self._db.save(file_path, task.file_size, fingerprint, ed2k_hash, ed2k_link)
        logger.info(f"✅  Hash guardado inicialmente en BBDD.")

        # === FASE 4: IA + APIs ===

        logger.info(f"🔹  Iniciando orquestación de metadatos (Regex -> IA -> API -> Antimalware)...")

        engine = MetadataEngine() # Instancio el motor de metadatos
        metadata_dict = engine.identify_file(file_name, str(file_path))  # Pipeline completo de metadatos
        
        # === FASE 5: Organización en Disco (Reto 5) ===
        
        organizer = LibraryOrganizer() # Instancio el organizador
        final_path = organizer.organize(str(file_path), metadata_dict) # Organizo el archivo
        
        # === FASE 6: Persistencia Final (Metadatos) ===

        self._db.update_metadata(fingerprint, task.file_size, metadata_dict, final_path)
        
        if final_path == "<DELETED_MALICIOUS>":
            logger.info(f"✅  Archivo purgado de la cola y del sistema.")
        else:
            logger.info(f"✅  Procesamiento y organización superados para: {file_name}")


    # Método para detener el Worker Thread
    def stop(self) -> None:

        """
        Detengo el worker limpiamente.
        Envío un centinela (None) a la cola, espero a que el hilo se cierre y cierro la BD SQLite.
        """

        logger.info("Deteniendo worker...")
        self._stop_event.set()

        # El centinela 'None' hará que el Worker Thread salga del Worker Loop en el próximo get().
        self._queue.put(None)

        # Espero a que el hilo termine, pero con un timeout de 10 segundos por si algo se queda colgado.
        self._worker_thread.join(timeout=10)

        if self._worker_thread.is_alive(): # Si el hilo sigue vivo después del timeout
            logger.warning("⚠️  El worker no se detuvo en 10 segundos. Forzando cierre...")

        # Cierro la conexión a la base de datos SQLite limpiamente.
        self._db.close()


    # Método para obtener el número de tareas pendientes en la cola
    @property # @property permite acceder a un método como si fuera un atributo.
    def pending_count(self) -> int:
        """
        Devuelvo el número de tareas pendientes en la cola.
        Útil para monitorización y logging.
        """
        return self._queue.qsize()


    # Método estático para formatear el tamaño del archivo
    @staticmethod
    def _format_size(size_bytes: int) -> str:

        """
        Convierto bytes a una representación legible (KB, MB, GB).
        Así los logs son comprensibles para los usuarios.

        Args:
            size_bytes: Tamaño en bytes.

        Returns:
            String formateado como "1.5 GB", "340 MB", etc.
        """

        # Si el tamaño es menor a 1KB, lo devuelvo en bytes.
        if size_bytes < 1024:
            return f"{size_bytes} B"
        # Si el tamaño es menor a 1MB, lo devuelvo en KB.
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        # Si el tamaño es menor a 1GB, lo devuelvo en MB.
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        # Si el tamaño es mayor o igual a 1GB, lo devuelvo en GB.
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
