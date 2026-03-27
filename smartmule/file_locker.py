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
def is_file_locked(file_path: Path) -> bool:

    """
    Compruebo si un archivo está bloqueado por otro proceso intentando abrirlo en modo lectura binaria (rb). 
    Es una verificación puntual (no espera).

    Abro y cierro inmediatamente — solo me interesa saber si Windows me deja acceder al archivo o no. 
    Si obtengo PermissionError, significa que otro proceso (probablemente eMule) lo tiene abierto con un bloqueo exclusivo.

    Args:
        file_path: Ruta completa al archivo que quiero verificar.

    Returns:
        True -> si el archivo está bloqueado
        False -> si el archivo está libre.
    """

    try:
        # Intento abrir el archivo en modo lectura binaria. 
        # Si otro proceso lo tiene bloqueado, Windows lanzará PermissionError.
        with open(file_path, "rb") as f:
            pass

        return False # Si abre, el archivo está libre y se devuelve False

    except PermissionError:
        # El archivo está bloqueado por otro proceso (Sharing Violation).
        return True

    except OSError as e:
        # Otro tipo de error del sistema operativo (archivo no encontrado...)
        # Lo trato como "bloqueado" por precaución
        logger.warning(f"⚠️  Error de OS al verificar bloqueo de '{file_path.name}': {e}")
        return True


# Método para esperar a que el archivo se desbloquee
def wait_for_unlock(
    file_path: Path,
    timeout: int = FILE_LOCK_TIMEOUT,
    initial_delay: float = FILE_LOCK_INITIAL_DELAY,
    max_delay: float = FILE_LOCK_MAX_DELAY,
) -> bool:

    """
    Espero a que un archivo sea accesible, usando reintentos con backoff exponencial.

    Proceso:
    1. Intento abrir el archivo en modo lectura binaria (rb).
    2. Si falla con PermissionError, espero 'initial_delay' segundos.
    3. En cada reintento, duplico el tiempo de espera (backoff exponencial), pero nunca supero 'max_delay' segundos entre intentos.
    4. Si el tiempo total acumulado supera 'timeout', me rindo y retorno False.
    5. Si el archivo desaparece durante la espera (fue eliminado por el usuario o por eMule), también retorno False.

    El backoff exponencial (1s, 2s, 4s, 8s, 16s...) es crucial para no saturar el disco con operaciones open() constantes.

    Args:
        file_path:     Ruta al archivo que espero que se desbloquee.
        timeout:       Tiempo máximo total de espera en segundos (default: 120).
        initial_delay: Espera inicial entre reintentos en segundos (default: 1.0).
        max_delay:     Espera máxima entre reintentos en segundos (default: 15.0).

    Returns:
        True -> si el archivo se desbloqueó dentro del timeout.
        False -> si se agotó el tiempo (timeout) o el archivo ya no existe.
    """

    # Registro el momento de inicio para controlar el timeout total.
    start_time = time.monotonic()

    # El delay actual comienza en initial_delay y se duplica en cada intento.
    current_delay = initial_delay # 1.0s

    # Llevo la cuenta de intentos para el logging.
    attempt = 0

    while True:

        attempt += 1

        # Primero verifico que el archivo siga existiendo
        if not file_path.exists():
            logger.warning(
                f"⚠️  El archivo '{file_path.name}' desapareció durante la espera de desbloqueo (intento #{attempt}). Cancelando..."
            )
            return False

        try:

            # Intento abrir el archivo en modo lectura binaria. Si eMule ya lo liberó, esto funcionará sin problemas.
            with open(file_path, "rb") as f:
                pass

            # ¡Éxito! El archivo está desbloqueado y listo para procesar.
            if attempt > 1:

                elapsed = time.monotonic() - start_time # Tiempo total transcurrido desde el primer intento

                logger.info(
                    f"✅ Archivo '{file_path.name}' desbloqueado tras {attempt} intento(s) ({elapsed:.1f}s)"
                )
            else:
                logger.debug(
                    f"✅ Archivo '{file_path.name}' accesible inmediatamente"
                )
            return True

        except PermissionError:

            # El archivo sigue bloqueado. Calculo cuánto tiempo ha pasado.
            elapsed = time.monotonic() - start_time

            # Verifico si he agotado el tiempo máximo de espera.
            if elapsed + current_delay >= timeout:
                logger.error(
                    f"❌  TIMEOUT: No pude acceder a '{file_path.name}' tras {timeout}s ({attempt} intentos)."
                    f"ℹ️  Posiblemente eMule siga usando el archivo."
                )
                return False

            # Informo del reintento. 
            # Uso DEBUG para los primeros intentos y WARNING si ya llevo más de 5, porque algo raro puede estar pasando
            log_level = logging.WARNING if attempt > 5 else logging.DEBUG

            logger.log(
                log_level,
                f"⚠️  Archivo '{file_path.name}' bloqueado (intento #{attempt}). "
                f"ℹ️  Reintentando en {current_delay:.1f}s..."
            )

            # Espero antes del siguiente intento.
            time.sleep(current_delay)

            # Actualizo el backoff exponencial
            current_delay = min(current_delay * 2, max_delay)

        except OSError as e:

            # Error inesperado del SO. Lo registro y sigo intentando, ya que podría ser un error transitorio.
            logger.warning(
                f"⚠️  Error de OS al intentar acceder a '{file_path.name}' en el intento #{attempt}: {e}"
            )

            elapsed = time.monotonic() - start_time

            if elapsed >= timeout:
                logger.error(
                    f"❌  TIMEOUT con errores: No pude acceder a '{file_path.name}' tras {timeout}s." 
                    f"Último error: {e}"
                )
                return False

            time.sleep(current_delay) # Espero antes del siguiente intento.
            current_delay = min(current_delay * 2, max_delay) # Actualizo el backoff exponencial
