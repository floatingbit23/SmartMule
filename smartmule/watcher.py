"""
Observador del sistema de archivos de SmartMule.

Corazón de la implementación inicial del proyecto.

Uso la librería 'watchdog' para monitorizar la carpeta Incoming/ de eMule y detectar cuándo llega un archivo nuevo.

El desafío principal en Windows es que el sistema operativo genera múltiples eventos para una sola operación de archivo. 
Por ejemplo, cuando eMule mueve un archivo a Incoming, Windows puede generar los siguientes eventos:
  1. FileCreatedEvent("Pelicula.mkv")
  2. FileModifiedEvent("Pelicula.mkv")  (al empezar a escribir)
  3. FileModifiedEvent("Pelicula.mkv")  (otra vez, ahora al terminar de escribir)

Si procesara cada evento por separado, estaría intentando hashear y clasificar el mismo archivo 3 veces. 
La solución óptima es un mecanismo de DEBOUNCING:
1. Agrupo todos los eventos de un mismo archivo en una ventana de tiempo (3 segundos)
2. Solo proceso el archivo una vez, cuando la ventana de tiempo expire sin nuevos eventos.

watchdog usa la API nativa de Windows ReadDirectoryChangesW por debajo, lo que significa que NO hace polling (consultas repetidas a la carpeta). 
Por lo tanto, el consumo de CPU en reposo será < 1%.
"""

import logging
import threading # threading es una librería que permite ejecutar múltiples hilos de ejecución en un mismo programa.
from pathlib import Path
from typing import Optional

from watchdog.observers import Observer # Observer es una clase que permite monitorizar la carpeta que le indique
from watchdog.events import FileSystemEventHandler, FileSystemEvent  # Clases que permiten manejar los eventos del sistema de archivos

from smartmule.config import INCOMING_PATH, DEBOUNCE_SECONDS, IGNORED_EXTENSIONS
from smartmule.file_locker import wait_for_unlock 
from smartmule.queue_manager import QueueManager

# Logger específico para el módulo del Watcher.
logger = logging.getLogger("SmartMule.watcher")

# Clase que maneja los eventos del sistema de archivos para la carpeta Incoming.
class IncomingHandler(FileSystemEventHandler):

    """
    Manejo los eventos del sistema de archivos para la carpeta Incoming.

    Mi trabajo es filtrar el ruido de Windows (eventos duplicados, archivos
    temporales de eMule) y, cuando detecto un archivo legítimo y estable,
    pasárselo al QueueManager para su procesamiento.

    Uso un diccionario de threading.Timer para implementar el debouncing:
    cada vez que llega un evento para un archivo, cancelo el timer anterior
    y creo uno nuevo. Solo cuando pasan DEBOUNCE_SECONDS sin nuevos eventos,
    el timer se dispara y despacho el archivo.
    """

    # Constructor del IncomingHandler
    def __init__(self, queue_manager: QueueManager):

        """
        Inicializo el handler con una referencia al QueueManager.

        Args:
            queue_manager: La cola de prioridad donde encolaré los archivos
            una vez que pasen el debounce y el check de bloqueo.
        """

        super().__init__() # Inicializo el padre de IncomingHandler (FileSystemEventHandler)

        # Referencia al QueueManager para meter los archivos procesables en la cola.
        self._queue_manager = queue_manager

        # Diccionario de timers activos. 
        self._timers: dict[str, threading.Timer] = {}
        # La 'key' es la ruta normalizada del archivo y el 'value' es el threading.Timer que se disparará tras DEBOUNCE_SECONDS.
        # Por ejemplo: {"C:\Incoming\peli.mkv": <Timer Object>}

        # Cuando llega un nuevo evento para un archivo que ya tiene un timer activo,
        # cancelo el timer viejo y creo uno nuevo. Así agrupo eventos duplicados.

        # Lock para proteger el diccionario de timers. 
        self._lock = threading.Lock()

    # Método para manejar la creación de archivos
    def on_created(self, event: FileSystemEvent) -> None:
        """
        Reacciono cuando se crea un archivo o se mueve algo nuevo (externo)
        en la carpeta Incoming. Este es el evento principal que me interesa:
        eMule crea el archivo aquí cuando termina una descarga.

        Delego la lógica real a _handle_event() porque on_modified() hace
        exactamente lo mismo (ambos reinician el timer de debounce).

        Args:
            event: Evento del sistema de archivos con la ruta del archivo.
        """
        self._handle_event(event)


    def on_deleted(self, event: FileSystemEvent) -> None:

        """
        Reacciono cuando un archivo es eliminado de Incoming.
        Si había un temporizador de debounce activo para este archivo, lo cancelo
        para no procesar "fantasmas" y evitar logs innecesarios.
        """
        
        src_path = Path(event.src_path)
        top_level_item = self._get_top_level_item(src_path)
        
        if top_level_item:
            abs_path = str(top_level_item.resolve())
            with self._lock:
                if abs_path in self._timers:
                    self._timers[abs_path].cancel()
                    del self._timers[abs_path]
                    logger.debug(f"🗑️  Archivo eliminado: Timer cancelado para '{top_level_item.name}'")


    # Método para manejar la modificación de archivos
    def on_modified(self, event: FileSystemEvent) -> None:
        """
        Reacciono cuando Windows me notifica que un archivo fue modificado.
        
        En la práctica, Windows suele generar este evento justo después de
        un on_created. Al tratarlo igual (reiniciando el debounce timer),
        me aseguro de que solo proceso el archivo cuando Windows ha terminado
        de escribir todos los datos.

        Args:
            event: Evento del sistema de archivos con la ruta del archivo.
        """
        self._handle_event(event)


    # Método para manejar el movimiento de archivos
    def on_moved(self, event: FileSystemEvent) -> None:
        """
        Reacciono cuando un archivo es movido o renombrado dentro de Incoming.
        Podría pasar si eMule renombra un archivo al completar la descarga.
        Lo trato como un archivo nuevo usando la ruta de destino.

        Args:
            event: Evento de movimiento con src_path (origen) y dest_path (destino).
        """
        # Identificamos el ítem de nivel superior en Incoming
        top_level_item = self._get_top_level_item(dest_path)
        if top_level_item:
            logger.debug(f"Ítem movido/renombrado en Incoming: {top_level_item.name}")
            self._reset_timer(top_level_item)


    # Método para manejar eventos (creación y modificación)
    def _handle_event(self, event: FileSystemEvent) -> None:
        """
        Proceso un evento created o modified. Filtro directorios y extensiones
        no deseadas, y luego reinicio el timer de debounce para el archivo.

        Args:
            event: El evento del sistema de archivos.
        """
        src_path = Path(event.src_path)
        # Identificamos el ítem de nivel superior (la carpeta o el archivo en la raíz de Incoming)
        top_level_item = self._get_top_level_item(src_path)
        
        if not top_level_item:
            return

        file_path = Path(event.src_path)

        # Verifico si la extensión del archivo está en mi lista de ignorados.
        # Necesito comprobar tanto el sufijo simple (.part) como los compuestos
        # (.part.met, .part.met.bak) porque Path.suffix solo devuelve el último.
        if self._should_ignore(file_path):
            return

        logger.debug(f"Evento '{event.event_type}' para: {file_path.name}")

        # Reinicio el timer de debounce. Si ya había un timer para este ítem,
        # se cancela y se crea uno nuevo. Esto agrupa los eventos duplicados.
        self._reset_timer(top_level_item)

    def _get_top_level_item(self, path: Path) -> Optional[Path]:

        """
        Determina cuál es el ítem raíz dentro de la carpeta Incoming.
        Incoming/Peli/Sub/file.mp4 -> Incoming/Peli
        """

        try:
            incoming_abs = INCOMING_PATH.resolve()
            path_abs = path.resolve()
            relative = path_abs.relative_to(incoming_abs)
            top_name = relative.parts[0]
            
            return INCOMING_PATH / top_name

        except (ValueError, IndexError):
            return None


    # Método para ignorar archivos
    def _should_ignore(self, file_path: Path) -> bool:

        """
        Decido si debo ignorar un archivo o carpeta basándome en su extensión.

        1. Compruebo si el propio ítem tiene una extensión ignorada (.part, .!ut, etc).
        2. Si no, y es una carpeta, compruebo si contiene algún archivo con extensión ignorada.

        Args:
            file_path: Ruta del ítem a evaluar.

        Returns:
            True si debo ignorar el ítem.
        """
        
        # Primero: ¿el propio archivo/carpeta tiene una extensión prohibitiva?
        # Esto cubre archivos individuales y casuísticas de test con rutas virtuales.
        if self._is_extension_ignored(file_path):
            return True

        # Segundo: Si es un directorio que EXISTE, miramos su contenido.
        if file_path.is_dir():
            try:
                # rglob('*') es recursivo.
                for sub_item in file_path.rglob('*'):
                    if sub_item.is_file() and self._is_extension_ignored(sub_item):
                        logger.debug(f"📁  Directorio '{file_path.name}' ignorado (contiene archivos temporales: {sub_item.name})")
                        return True
            except Exception as e:
                logger.warning(f"⚠️  Error al inspeccionar contenido de carpeta {file_path.name}: {e}")
            
            return False

        return False

    def _is_extension_ignored(self, file_path: Path) -> bool:

        """Helper para comprobar extensiones simples y compuestas.
        Devuelve True si la extensión está en IGNORED_EXTENSIONS.
        """

        # Compruebo extensiones compuestas concatenando los sufijos.
        compound_ext = "".join(file_path.suffixes).lower()
        if compound_ext in IGNORED_EXTENSIONS:
            return True

        # También verifico la extensión simple
        if file_path.suffix.lower() in IGNORED_EXTENSIONS:
            return True

        return False


    # Método para reiniciar el timer
    def _reset_timer(self, file_path: Path) -> None:
        """
        Reinicio el timer de debounce para un archivo. Si ya existía un timer
        activo para este archivo, lo cancelo antes de crear uno nuevo.

        La idea es que cada vez que Windows genera un evento para el mismo
        archivo, "reinicio el reloj". Solo cuando pasan DEBOUNCE_SECONDS
        sin ningún evento nuevo, el timer se dispara y despacho el archivo.

        Args:
            file_path: Ruta del archivo para el que reinicio el timer.
        """
        # Normalizo la ruta para usarla como clave del diccionario.
        # resolve() elimina componentes relativos y normaliza separadores.
        key = str(file_path.resolve())

        with self._lock:
            # Si ya hay un timer activo para este archivo, lo cancelo.
            # cancel() es seguro de llamar incluso si el timer ya se disparó.
            if key in self._timers:
                self._timers[key].cancel()

            # Creo un nuevo timer que se disparará tras DEBOUNCE_SECONDS.
            # Cuando expire, llamará a _dispatch_file con la ruta del archivo.
            timer = threading.Timer(
                DEBOUNCE_SECONDS,
                self._dispatch_file,
                args=[file_path],
            )
            # Lo nombro para facilitar la depuración con threading.enumerate().
            timer.name = f"Debounce-{file_path.name}"
            timer.daemon = True
            timer.start()

            # Guardo el timer en mi diccionario para poder cancelarlo si
            # llega otro evento para el mismo archivo.
            self._timers[key] = timer


    # Método para despachar (enviar a la cola) archivos
    def _dispatch_file(self, file_path: Path) -> None:

        """
        Despacho un archivo tras completar el periodo de debounce.

        Este método se ejecuta cuando el timer de debounce expira, lo cual
        significa que no han llegado más eventos para este archivo durante
        DEBOUNCE_SECONDS. En este punto:

        1. Verifico que el archivo siga existiendo (podría haber sido eliminado).
        2. Espero a que eMule libere el bloqueo del archivo (file_locker).
        3. Si todo va bien, encolo el archivo en el QueueManager.

        Args:
            file_path: Ruta del archivo a despachar.
        """

        # Limpio el timer del diccionario porque ya se ejecutó.
        key = str(file_path.resolve())
        with self._lock:
            self._timers.pop(key, None)

        logger.info(f"Debounce completado para: {file_path.name}")

        # Verifico que el archivo siga existiendo. Podría haber sido eliminado
        # o movido durante los segundos de debounce.
        if not file_path.exists():
            logger.warning(
                f"⚠️  Archivo '{file_path.name}' ya no existe tras el debounce. "
                f"Posiblemente fue eliminado o movido."
            )
            return

        # Espero a que eMule libere el bloqueo del archivo.
        # wait_for_unlock() implementa el retry con backoff exponencial.
        if not wait_for_unlock(file_path):
            logger.error(
                f"❌    No pude acceder a '{file_path.name}'. "
                f"Saltando este archivo..."
            )
            return

        # El archivo está desbloqueado y listo. Lo encolo para procesamiento.
        self._queue_manager.enqueue(file_path)


    # Método para cancelar todos los timers activos (SOLO PARA EL SHUTDOWN)
    def cleanup(self) -> None:

        """
        Cancelo todos los timers activos. 
        Lo invoco durante el shutdown para asegurarme de que no quedan hilos de timer colgados.
        """

        # Protejo el diccionario de timers
        with self._lock: 

            for key, timer in self._timers.items(): # Recorro todos los elementos del diccionario
                timer.cancel() # Cancelo cada timer de forma individual

            count = len(self._timers) # Cuento cuántos timers cancelé

            self._timers.clear() # Ahora sí, limpio el diccionario

        if count > 0: # Si cancelé algún timer, lo registro en un log
            logger.debug(f"ℹ️  Cancelados {count} timer(s) de debounce pendientes")

# Clase que orquesta el Observer de watchdog y el Handler.
class SmartMuleWatcher:

    """
    Wrapper de alto nivel que orquesta el Observer de watchdog y el handler.
    Expongo start(), stop() y scan_existing() para que main.py tenga una interfaz limpia y sencilla.
    """

    # Constructor del SmartMuleWatcher
    def __init__(self, queue_manager: QueueManager):

        """
        Inicializo el Watcher con el QueueManager donde encolaré los archivos.

        Args:
            queue_manager: Cola de prioridad donde se encolarán los archivos detectados.
        """

        # Creo el Handler que procesará los eventos del sistema de archivos.
        self._handler = IncomingHandler(queue_manager) # Instancio el IncomingHandler

        # Creo el Observer de watchdog. 
        # Este es el componente que realmente se comunica con la API ReadDirectoryChangesW de Windows.
        self._observer = Observer() # Instancio el Observer

        # Registro la carpeta Incoming para monitorización recursiva.
        self._observer.schedule(
            self._handler,
            str(INCOMING_PATH),
            recursive=True,
        )

        # Guardo referencia al QueueManager para el scan inicial.
        self._queue_manager = queue_manager

        logger.info(f"Watcher configurado para: {INCOMING_PATH}")

    # Método para arrancar el Observer
    def start(self) -> None:

        """
        Inicio la monitorización de la carpeta Incoming.
        El Observer corre en su propio hilo, así que start() retorna inmediatamente.
        """

        self._observer.start() # Arranco el Observer
        logger.info("ℹ️  Monitorización activa. Esperando archivos nuevos...")

    # Método para detener el Observer
    def stop(self) -> None:

        logger.info("ℹ️  Deteniendo Watcher...")

        self._handler.cleanup() # Cancelo los timers de debounce pendientes
        self._observer.stop() # Detengo el Observer
        self._observer.join(timeout=10) # Espero a que el hilo del Observer termine (llamando a join())

        if self._observer.is_alive():
            logger.warning("⚠️  El Observer no se detuvo en 10 segundos. Me rindo.")
        else:
            logger.info("ℹ️  Watcher detenido limpiamente")

    # Método para escanear archivos existentes ( wait_for_unlock() -> enqueue() )
    def scan_existing(self) -> int:

        """
        Hago un barrido inicial de la carpeta Incoming para detectar archivos
        que llegaron mientras SmartMule no estaba corriendo.

        Itero sobre todos los archivos en Incoming y los encolo directamente en el QueueManager 
        (sin pasar por el Debouncer, porque ya son archivos estables que llevan ahí desde antes de arrancar).

        Returns:
            Número de archivos encontrados y encolados.
        """

        logger.info(f"🔹  Escaneando archivos existentes en {INCOMING_PATH}...")

        count = 0 # Inicializo el contador de archivos encontrados

        for item in INCOMING_PATH.iterdir(): # Recorro todos los elementos en la carpeta Incoming

            # Procesamos tanto archivos como carpetas que estén en la raíz de Incoming
            if self._handler._should_ignore(item):
                continue

            # Verifico que el archivo sea accesible (no bloqueado)

            # Para el escaneo inicial uso 'wait_for_unlock' con un timeout (FILE_LOCK_TIMEOUT) corto 
            # porque si un archivo lleva bloqueado desde antes de arrancar, probablemente hay un problema mayor.

            if wait_for_unlock(item, timeout=10): # Si el archivo está desbloqueado (wait_for_unlock == True) 

                self._queue_manager.enqueue(item) # Lo encolo directamente
                count += 1 # Incremento el contador

            else: # Si el archivo está bloqueado

                # Lanzo el Warning
                logger.warning( 
                    f"⚠️ Archivo existente '{item.name}' bloqueado. "
                    f"⚠️ Se procesará cuando se desbloquee (si el Watcher lo detecta)."
                )

        if count > 0: # Si se encontraron archivos

            logger.info( 
                f"✅ Escaneo inicial completado: {count} archivo(s) existente(s) encolado(s)"
            )

        else: # Si no se encontraron archivos
            logger.info("✅ Escaneo inicial completado: no se encontraron archivos pendientes")

        return count # Devuelvo el contador de archivos encontrados.
