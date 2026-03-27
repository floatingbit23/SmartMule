"""
queue_manager.py — Cola de prioridad con trabajador único (Single Worker) para SmartMule.

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
import threading
from queue import PriorityQueue
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Creo un logger específico para este módulo.
logger = logging.getLogger("SmartMule.queue_manager")


# === Umbrales de tamaño para asignar prioridades ===
# Defino estos umbrales como constantes para que sean fáciles de ajustar. Los archivos más pequeños tienen prioridad más alta (número más bajo).

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
    def __init__(self, process_callback: Optional[Callable] = None):

        """
        Inicializo la cola de prioridad y arranco el Worker Thread.

     process_callback: Función que se llamará para procesar cada archivo.
        Recibe un FileTask como argumento. Si es None, uso un placeholder que solo loguea el archivo
        (útil para la implementación inicial, donde aún no tengo el pipeline completo de hashing/IA).
        """

        # La PriorityQueue de Python es thread-safe por defecto (no necesito locks adicionales para put() y get()).
        self._queue: PriorityQueue = PriorityQueue()

        # Guardo el callback de procesamiento. En esta implementación será un placeholder, y en implementaciones posteriores se sustituirá por el pipeline completo.
        self._process_callback = process_callback or self._default_process

        # Flag para señalar al Worker que debe detenerse. Uso un Event en vez de un bool simple porque es thread-safe.
        self._stop_event = threading.Event()

        # Creo el Worker Thread como daemon (hilo secundario) para que no impida que el programa principal termine si algo sale mal.
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="SmartMule-Worker",
            daemon=True,
        )

        # Arranco el worker inmediatamente. Se quedará bloqueado en get() esperando a que llegue la primera tarea.
        self._worker_thread.start()
        logger.info("Worker iniciado. Esperando archivos en la cola...")

    # Método para meter archivos en la cola
    def enqueue(self, file_path: Path) -> None:
        """
        Encolo un archivo para su procesamiento. 
        Calculo su prioridad  basándome en el tamaño y la extensión, creo un FileTask y lo meto en la PriorityQueue.

        Args:
            file_path: Ruta completa al archivo que quiero procesar.
        """

        try:
            # Obtengo el tamaño del archivo para calcular la prioridad.
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
            f"ℹ️  Encolado [P{priority}]: {file_path.name} ({size_str}) "
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
                self._queue.task_done() # Marco la tarea como completada (necesario para que join() funcione correctamente)

        # Cuando el bucle termina (porque stop_event está activo), salgo del método.
        logger.info("ℹ️  Worker detenido limpiamente")


    # Placeholder de procesamiento para la implementación inicial
    def _default_process(self, task: FileTask) -> None:

        """
        Placeholder de procesamiento para la implementación inicial. 
        Simplemente logueo la información del archivo. 
        En implementaciones posteriores, este callback será reemplazado por el pipeline completo:
        hash ED2K → IA → API → mover/renombrar.

        Args:
            task: La tarea de archivo a procesar.
        """

        file_name = Path(task.file_path).name
        size_str = self._format_size(task.file_size)
        wait_time = time.time() - task.enqueued_at

        logger.info(
            f"ℹ️  Procesando [P{task.priority}]: {file_name} ({size_str}) "
            f"— esperó {wait_time:.1f}s en cola"
        )

        logger.info(
            f"  [PLACEHOLDER] Aquí se ejecutará: "
            f"hash ED2K → IA → API → mover/renombrar"
        )


    # Método para detener el Worker Thread
    def stop(self) -> None:

        """
        Detengo el worker limpiamente. 
        Envío un centinela (None) a la cola para que el worker sepa que debe terminar, y espero a que el hilo se cierre con join().
        Llamo a _stop_event.set() primero, por si el worker está bloqueado en el timeout de get() y no ve el centinela inmediatamente.
        """

        logger.info("Deteniendo worker...")
        self._stop_event.set()

        # El centinela 'None' hará que el Worker Thread salga del Worker Loop en el próximo get().
        self._queue.put(None)

        # Espero a que el hilo termine, pero con un timeout de 10 segundos por si algo se queda colgado. 
        # No quiero bloquear el shutdown indefinidamente.
        self._worker_thread.join(timeout=10)

        if self._worker_thread.is_alive(): # Si el hilo sigue vivo después del timeout
            logger.warning("⚠️  El worker no se detuvo en 10 segundos. Forzando cierre...")


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
