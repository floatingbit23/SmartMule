"""
file_locker.py — Gestión de bloqueos de archivos en Windows.

Cuando eMule termina una descarga, mueve el archivo a la carpeta Incoming,
pero lo mantiene abierto durante unos segundos mientras actualiza su base de datos interna ('known.met'). 
Si intentara leer o mover el archivo en ese momento, Windows me devolvería un PermissionError (Error 32: Sharing Violation).

Por ello implementaré un mecanismo de espera inteligente con backoff exponencial.
De esta forma no saturo el sistema con reintentos constantes y doy tiempo a eMule para que termine su trabajo.
"""

import time
import logging
from pathlib import Path

# Importo las constantes de configuración.
from smartmule.config import (
    FILE_LOCK_TIMEOUT,
    FILE_LOCK_INITIAL_DELAY,
    FILE_LOCK_MAX_DELAY,
)

# Logger específico para el módulo del FileLocker.
logger = logging.getLogger("SmartMule.file_locker")


# Método para verificar si el archivo está bloqueado
def is_file_locked(path: Path) -> bool:

    """
    Compruebo si un ítem (archivo o carpeta) está bloqueado por otro proceso.
    
    - Si es un archivo: Intento abrirlo en modo lectura binaria (rb).
    - Si es una carpeta: Verifico recursivamente si alguno de los archivos que contiene está bloqueado.

    Args:
        path: Ruta completa al ítem que quiero verificar.

    Returns:
        True -> si el ítem (o algo dentro de él) está bloqueado.
        False -> si todo está libre.
    """

    if path.is_dir():
        # Para carpetas, comprobamos todos los archivos internos (recursivo).
        # Si un solo archivo de la carpeta está bloqueado, la carpeta entera se considera bloqueada.
        try:
            for item in path.rglob('*'):
                if item.is_file() and _is_single_file_locked(item):
                    return True
            return False
        except OSError as e:
            logger.warning(f"⚠️  Error detectando archivos en carpeta '{path.name}': {e}")
            return True
    else:
        return _is_single_file_locked(path)


def _is_single_file_locked(file_path: Path) -> bool:

    """Implementación interna para un solo archivo físico."""
    
    try:
        # Intento abrir el archivo en modo lectura binaria. 
        # Si otro proceso lo tiene bloqueado, Windows lanzará PermissionError.
        with open(file_path, "rb") as f:
            pass
        return False

    except PermissionError:
        # El archivo está bloqueado por otro proceso (Sharing Violation).
        return True

    except OSError:
        # Errores de red o de sistema se tratan como bloqueado por precaución.
        return True


# Método para esperar a que el archivo se desbloquee
def wait_for_unlock(
    path: Path,
    timeout: int = FILE_LOCK_TIMEOUT,
    initial_delay: float = FILE_LOCK_INITIAL_DELAY,
    max_delay: float = FILE_LOCK_MAX_DELAY,
) -> bool:

    """
    Espero a que un ítem (archivo o carpeta) sea accesible, usando reintentos con backoff exponencial.

    Proceso:
    1. Intento abrir el archivo en modo lectura binaria (rb).
    2. Si falla con PermissionError, espero 'initial_delay' segundos.
    3. En cada reintento, duplico el tiempo de espera (backoff exponencial), pero nunca supero 'max_delay' segundos entre intentos.
    4. Si el tiempo total acumulado supera 'timeout', me rindo y retorno False.
    5. Si el archivo desaparece durante la espera (fue eliminado por el usuario o por eMule), también retorno False.

    El backoff exponencial (1s, 2s, 4s, 8s, 16s...) es crucial para no saturar el disco con operaciones open() constantes.

    Args:
        path:     Ruta al archivo o carpeta que espero que se desbloquee.
        timeout:       Tiempo máximo total de espera en segundos (default: 120).
        initial_delay: Espera inicial entre reintentos en segundos (default: 1.0).
        max_delay:     Espera máxima entre reintentos en segundos (default: 15.0).

    Returns:
        True -> si el archivo se desbloqueó dentro del timeout.
        False -> si se agotó el tiempo (timeout) o el archivo ya no existe.

    Si es una carpeta, se considera desbloqueada cuando TODOS sus archivos internos son accesibles.
    """

    # Registro el momento de inicio para controlar el timeout total.
    start_time = time.monotonic()
    current_delay = initial_delay
    attempt = 0

    # Determinamos el tipo de ítem (Item Type) para los logs
    item_type = "Carpeta" if path.is_dir() else "Archivo"

    while True:
        attempt += 1

        # Primero verifico que el ítem siga existiendo
        if not path.exists():
            logger.warning(
                f"⚠️  {item_type} '{path.name}' desapareció durante la espera (intento #{attempt})."
            )
            return False

        # Verificamos si está bloqueado usando la lógica inteligente que distingue entre archivo/carpeta
        if not is_file_locked(path):
            # ¡Éxito!
            
            if attempt > 1: # Si ha habido reintentos, informo del tiempo total transcurrido
                elapsed = time.monotonic() - start_time

                logger.info(
                    f"✅ {item_type} '{path.name}' desbloqueado tras {attempt} intento(s) ({elapsed:.1f}s)"
                )
            
            else: # Si no ha habido reintentos, informo de que el archivo está accesible inmediatamente
                logger.debug(f"✅ {item_type} '{path.name}' accesible inmediatamente!")
            return True

        # Sigue bloqueado...
        elapsed = time.monotonic() - start_time

            # Verifico si he agotado el tiempo máximo de espera.
        if elapsed + current_delay >= timeout:
            logger.error(
                f"❌  TIMEOUT: No pude acceder a {item_type.lower()} '{path.name}' tras {timeout}s ({attempt} intentos)."
            )
            return False

        # Informo del reintento.
        # Uso DEBUG para los primeros intentos y WARNING si ya llevo más de 5, porque algo raro puede estar pasando
        log_level = logging.WARNING if attempt > 5 else logging.DEBUG

        logger.log(
            log_level,
            f"⚠️  {item_type} '{path.name}' bloqueado (intento #{attempt}). "
            f"ℹ️  Reintentando en {current_delay:.1f}s..."
        )

            # Espero antes del siguiente intento.
        time.sleep(current_delay)

            # Actualizo el backoff exponencial
        current_delay = min(current_delay * 2, max_delay)
