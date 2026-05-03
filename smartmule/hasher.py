"""
Implementación del algoritmo de hashing ED2K para SmartMule.

El hash ED2K es el identificador único de un archivo en la red eDonkey/eMule.
A diferencia de los hashes lineales (SHA256, MD5), el ED2K es un hash jerárquico
basado en MD4 que opera por bloques de exactamente 9,728,000 bytes (9.28 MB).

Algoritmo implementado:

    - Si el archivo tiene <= 9.28 MB: ED2K hash = MD4 del archivo completo.

    - Si el archivo tiene > 9.28 MB:
        1. Divido el archivo en bloques de 9.28 MB.
        2. Calculo el hash MD4 de cada bloque.
        3. Concateno todos los hashes MD4s en binario.
        4. El hash ED2K final es el hash MD4 resultante de la concatenación del paso 3.

Implemento la lectura por búfer para no cargar archivos de varios GB en la RAM.
Esto es crítico para SmartMule, que puede necesitar procesar archivos de >20 GB.
"""

import sys
import hashlib
import logging
import time
import threading
import os
import concurrent.futures
import collections
from typing import Optional
from pathlib import Path

from Crypto.Hash import MD4  # pycryptodome: implementación del algoritmo MD4

from smartmule.config import ED2K_CHUNK_SIZE, IGNORED_EXTENSIONS # ED2K_CHUNK_SIZE: 9,728,000 bytes (9.28 MB)

# Creo un logger específico para este módulo.
logger = logging.getLogger("SmartMule.hasher")

# Función de ayuda para el pool de procesos (debe estar fuera de la clase/función principal)
def _calculate_md4_chunk(chunk: bytes) -> bytes:
    """Calcula el MD4 de un bloque. Se ejecuta en un hilo del pool."""
    from Crypto.Hash import MD4
    return MD4.new(chunk).digest()

# Función que calcula el hash ED2K de un archivo
def _get_file_to_hash(path: Path) -> Optional[Path]:

    """Determina qué archivo procesar (el propio archivo o el más grande de una carpeta)."""

    # Si no es una carpeta, es un archivo y salimos
    if not path.is_dir():
        return path

    # Si es una carpeta, busco el archivo principal. Si no existe, salimos.
    main_file = get_main_file_in_dir(path)
    if not main_file:
        return None
        
    logger.info(f"[i] Directorio detectado. Usando archivo principal {main_file.name} para cálculo de hash ED2K...")
    return main_file

def _process_file_in_parallel(file_path: Path) -> list[bytes]:

    """Lee el archivo y calcula los hashes MD4 de cada bloque de 9.28MB en paralelo."""

    from Crypto.Hash import MD4
    chunk_hashes: list[bytes] = [] # Lista para almacenar los hashes MD4 de cada bloque

    # Configuración de paralelismo conservador
    cpu_count = os.cpu_count() or 1 # Número de núcleos de la CPU
    max_workers = max(1, cpu_count // 2) # Número de hilos para el pool de procesos
    max_pending = max_workers * 2 # Número máximo de bloques pendientes

    # Ejemplo: si la CPU tiene 8 núcleos, se usarán 4 hilos para calcular hashes y se mantendrán 8 bloques de 9.28MB (aprox. 74MB) en memoria como máximo

    with open(file_path, "rb") as f:
        # Uso ThreadPoolExecutor para calcular hashes en paralelo, con un máximo de hilos y bloques pendientes
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:

            futures = collections.deque() # Cola eficiente para almacenar las tareas pendientes (O(1) en pop)

            while True:

                # Control de flujo para no saturar la RAM con bloques pendientes
                # Se procesa el resultado del bloque más antiguo si se alcanza el límite de bloques pendientes
                if len(futures) >= max_pending:
                    chunk_hashes.append(futures.popleft().result()) # Espera a que termine el primer bloque y lo añade a la lista
                    continue # Vuelve al inicio del bucle para procesar el siguiente bloque

                chunk = f.read(ED2K_CHUNK_SIZE) # Lee el siguiente bloque de 9.28MB

                # Si no hay más bloques para procesar, salimos del bucle
                if not chunk:
                    break
                
                futures.append(executor.submit(_calculate_md4_chunk, chunk)) # Envía el bloque a calcular al pool de hilos

            # Procesamos los resultados restantes
            for fut in futures:
                chunk_hashes.append(fut.result()) # Espera a que termine el bloque y lo añade a la lista
                
    return chunk_hashes # Lista de hashes MD4 de cada bloque de 9.28MB

def _finalize_ed2k_hash(chunk_hashes: list[bytes]) -> str:

    """Calcula el hash final concatenando los hashes de los bloques según el estándar ED2K."""

    from Crypto.Hash import MD4
    
    # Caso especial: Si no hay bloques (archivo vacío), se devuelve un hash vacío
    if not chunk_hashes:
        return MD4.new(b"").hexdigest().upper()

    # Caso especial: Si solo hay un bloque (archivo de <9.28MB), se devuelve su hash
    if len(chunk_hashes) == 1:
        return chunk_hashes[0].hex().upper()

    # Hash jerárquico: hash del MD4 de la concatenación de todos los hashes de bloque
    all_hashes_concatenated = b"".join(chunk_hashes) # Concatenación de todos los hashes MD4 de cada bloque
    return MD4.new(all_hashes_concatenated).hexdigest().upper() # Hash final del MD4 de la concatenación

def calculate_ed2k(path: Path) -> str:

    """
    Orquestador del cálculo de hash ED2K. Soporta archivos y carpetas (usa el archivo principal en este último caso).
    Implementa un log de progreso persistente en la terminal.
    """

    from Crypto.Hash import MD4
    
    file_to_hash = _get_file_to_hash(path) # Determina qué archivo procesar

    if not file_to_hash: # Si no hay archivo, devuelve un hash vacío
        return MD4.new(b"").hexdigest().upper()

    start_time = time.time() # Tiempo inicial para el cálculo del hash ED2K
    timer_ref: list[threading.Timer] = [] # Lista para almacenar los timers de progreso

    def _log_progress():

        """Función interna para informar del progreso cada 2 segundos en la misma línea."""

        elapsed = time.time() - start_time
        mins, secs = divmod(int(elapsed), 60)
        elapsed_str = f"{mins}min {secs}s" if mins > 0 else f"{secs}s"
        now = time.strftime("%H:%M:%S")
        
        # Formato ANSI para la terminal
        output = f"\r{now}  INFO     [\033[97mSmartMule.hasher\033[0m] [i] Calculando hash ED2K... ({elapsed_str} transcurrido(s))"

        
        # Imprime el progreso
        if sys.stdout:
            try:
                sys.stdout.write(output)
                sys.stdout.flush()
            except UnicodeEncodeError:
                sys.stdout.write(f"\r{now}  INFO     [SmartMule.hasher]  [i] Calculando hash ED2K... ({elapsed_str})")
                sys.stdout.flush()

        # Crea el siguiente timer (cada 2 segundos)
        t = threading.Timer(2.0, _log_progress)
        t.daemon = True 
        timer_ref.append(t)
        t.start()

    # Iniciamos el sistema de notificaciones de progreso
    first_timer = threading.Timer(2.0, _log_progress)
    first_timer.daemon = True
    timer_ref.append(first_timer)
    first_timer.start()

    try:

        # Paso 1: Procesamiento paralelo de bloques
        chunk_hashes = _process_file_in_parallel(file_to_hash)
        
        # Paso 2: Cálculo del hash final
        return _finalize_ed2k_hash(chunk_hashes)

    finally:

        # Limpieza de timers y consola
        for t in timer_ref:
            t.cancel()

        # Salto de línea para limpiar la consola
        if sys.stdout:
            sys.stdout.write("\n")
            sys.stdout.flush()


# Función que formatea el enlace ED2K
def format_ed2k_link(file_path: Path, file_size: int, hash_hex: str) -> str:

    """
    Genero el enlace ED2K estándar de la red eDonkey para un archivo.
    El formato estándar es: ed2k://|file|nombre_del_archivo.ext|tamaño_en_bytes|hash_hex|/
    Este enlace es compatible con eMule y permite compartir la referencia exacta al archivo en la red P2P.

    Args:
        file_path: Ruta al archivo (solo uso el nombre).
        file_size: Tamaño del archivo en bytes.
        hash_hex: Hash ED2K en formato hexadecimal (32 caracteres).

    Returns:
        String con el enlace ED2K completo.
    """
    
    # Ejemplo: ed2k://|file|El.último.duelo.(2021).(Spanish.English.Subs).WEB-DL.1080p.HEVC.10b-E-AC3.by.mDudikoff.mkv|3122845276|9F977D83E2DFAD6F213F59703BDC5146|/
    return f"ed2k://|file|{file_path.name}|{file_size}|{hash_hex}|/"

# Función que calcula la huella digital del archivo
def calculate_fingerprint(path: Path, file_size: int) -> str:

    """
    Calcula una 'huella digital' (fingerprint) rápida del archivo:
    - Si el archivo es menor de 512 KB: Lee y hashea el contenido completo.
    - Si el archivo es mayor o igual a 512 KB: lee y hashea los primeros 256 KB y los últimos 256 KB.

    Esta huella se utiliza para identificar el archivo en la BBDD de forma instantánea,
    sin necesidad de calcular el hash ED2K completo (que requiere leer todo el archivo).

    Si es carpeta, utiliza el archivo más grande para generar la huella.

    Args:
        path: Ruta al archivo o carpeta
        file_size: Tamaño en bytes

    Returns:
        String hexadecimal con el hash SHA256 de la huella (en MAYÚSCULAS)
    """

    # Si es una carpeta, buscamos el archivo más pesado para que sea el representante.
    if path.is_dir():
        main_file = get_main_file_in_dir(path)
        if not main_file:
            return ""
        target_path = main_file
        # El tamaño para la lógica de huella debe ser el del archivo real, no el total de la carpeta
        target_size = main_file.stat().st_size
    else:
        target_path = path
        target_size = file_size

    sha = hashlib.sha256() # Creo el objeto SHA256
    buffer_size = 256 * 1024  # 256 KB (tamaño del buffer)

    try:

        with open(target_path, "rb") as f: # Abro el archivo en modo lectura binaria

            if target_size < buffer_size * 2: # Si el archivo es menor de 512 KB
                sha.update(f.read()) # Leo y hashea el contenido completo

            else: # Si el archivo es mayor o igual a 512 KB
                
                sha.update(f.read(buffer_size)) # Leo los primeros 256 KB

                f.seek(-buffer_size, 2) # El 2 indica que busque desde el final del archivo
                sha.update(f.read(buffer_size)) # Leo los últimos 256 KB

        return sha.hexdigest().upper() # Devuelvo el hash en formato hexadecimal y en mayúsculas

    except OSError as e:
        logger.error(f"[!] Error al calcular fingerprint de {path.name}: {e}")
        return "" 


def get_main_file_in_dir(dir_path: Path) -> Optional[Path]:

    """
    Busca el archivo más grande dentro de un directorio (recursivo).
    Excluye archivos con extensiones ignoradas (temporales de eMule/Torrent).
    Esto nos permite identificar el vídeo principal en una carpeta de Release.
    """

    try:
        # Filtramos archivos que no sean temporales
        files = []
        for f in dir_path.rglob('*'):
            if f.is_file():
                # Comprobación de extensiones ignoradas (simple y compuesta)
                compound_ext = "".join(f.suffixes).lower()
                # Importante: IGNORED_EXTENSIONS ya está disponible por el import arriba
                if compound_ext in IGNORED_EXTENSIONS or f.suffix.lower() in IGNORED_EXTENSIONS:
                    continue
                files.append(f)

        if not files:
            return None

        # Retornamos el de mayor tamaño
        return max(files, key=lambda f: f.stat().st_size)

    except Exception as e:
        logger.warning(f"[WARN]  No se pudo determinar el archivo principal en {dir_path.name}: {e}")
        return None
