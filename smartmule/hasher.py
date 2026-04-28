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
def calculate_ed2k(path: Path) -> str:

    """
    Calculo el hash ED2K de un ítem (archivo o carpeta).
    
    - Si es archivo: lectura por búferes de ED2K_CHUNK_SIZE bytes.
    - Si es carpeta: busco el archivo más grande en su interior (el 'main file') y lo hasheo.

    Args:
        path: Ruta al archivo o carpeta cuyo hash quiero calcular.

    Returns:
        Hash ED2K como string hexadecimal de 32 caracteres (128 bits).
    """

    # Si es una carpeta, delegamos en el archivo más grande que contenga
    if path.is_dir():

        main_file = get_main_file_in_dir(path)
        
        if not main_file:
            return MD4.new(b"").hexdigest().upper() # Carpeta vacía o sin archivos legibles
        logger.info(f"[i] Directorio detectado. Usando archivo principal {main_file.name} para cálculo de hash ED2K...")
        file_to_hash = main_file

    else:
        file_to_hash = path # Si no es una carpeta, es un archivo

    # Inicio el timer de progreso que informará cada 2s si el cálculo tarda
    start_time = time.time()

    # Lista para poder cancelar el timer desde el closure
    timer_ref: list[threading.Timer] = []

    # Función interna que se ejecutará cada 2 segundos para informar del progreso
    def _log_progress():

        """Actualizo el tiempo transcurrido en la misma línea de la terminal para no saturar los logs."""

        elapsed = time.time() - start_time
        mins, secs = divmod(int(elapsed), 60)
        elapsed_str = f"{mins}min {secs}s" if mins > 0 else f"{secs}s"

        # Reconstruyo el formato del log manualmente para poder usar '\r' (retorno de carro)
        # y que el tiempo se actualice en la misma línea sin saltar a la siguiente.
        # \033[97m es el blanco para hasher. \033[0m es el reset.
        now = time.strftime("%H:%M:%S")
        output = f"\r{now}  INFO     [\033[97mSmartMule.hasher\033[0m] [i] Calculando hash ED2K... ({elapsed_str} transcurrido(s))"
        
        if sys.stdout:
            try:
                sys.stdout.write(output)
                sys.stdout.flush()
            except UnicodeEncodeError:
                # Si el terminal no soporta Unicode, enviamos una versión simplificada
                sys.stdout.write(f"\r{now}  INFO     [SmartMule.hasher]  [i] Calculando hash ED2K... ({elapsed_str})")
                sys.stdout.flush()

        # Me reprogramo para el siguiente log en 2 segundos
        t = threading.Timer(2.0, _log_progress)
        t.daemon = True 
        timer_ref.clear()
        timer_ref.append(t)
        t.start()

    # Inicio el primer timer (se disparará a los 2s si el cálculo no ha terminado)
    first_timer = threading.Timer(2.0, _log_progress)

    first_timer.daemon = True # El timer se detendrá automáticamente cuando el programa principal termine

    timer_ref.append(first_timer) 

    first_timer.start() # Inicio el primer timer

    try:
        chunk_hashes: list[bytes] = []
        
        # Usamos la mitad de los núcleos para ser verdaderamente "poco invasivos"
        cpu_count = os.cpu_count() or 1
        max_workers = max(1, cpu_count // 2)
        
        # Limitamos cuántos bloques de 9.28MB pueden estar en memoria esperando a ser procesados.
        # Un valor de max_workers * 2 es un buen compromiso entre velocidad y RAM.
        max_pending = max_workers * 2

        with open(file_to_hash, "rb") as f:

            """
            Usamos ThreadPoolExecutor. Es mucho más rápido que procesos para bloques grandes
            porque evita el coste de copiar/serializar datos entre procesos -> IPC (Inter-Process Communication) Overhead.
            """

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                
                futures = []
                
                while True:
                    # Si ya tenemos demasiados bloques en memoria esperando, pausamos la lectura
                    if len(futures) >= max_pending:
                        # Esperamos a que el primer bloque enviado termine para liberar espacio en el buffer
                        chunk_hashes.append(futures.pop(0).result())
                        continue

                    chunk = f.read(ED2K_CHUNK_SIZE)
                    
                    if not chunk:
                        break # Fin del archivo
                    
                    # Enviamos el bloque al pool de hilos
                    futures.append(executor.submit(_calculate_md4_chunk, chunk))

                # Esperamos a que terminen los últimos bloques
                for fut in futures:
                    chunk_hashes.append(fut.result())

        # Cálculo final según el estándar ED2K
        if not chunk_hashes:
            return MD4.new(b"").hexdigest().upper()

        if len(chunk_hashes) == 1:
            return chunk_hashes[0].hex().upper()

        # Concatenación y hash final (paso jerárquico)
        all_hashes_concatenated = b"".join(chunk_hashes)
        return MD4.new(all_hashes_concatenated).hexdigest().upper()

    finally:
        # Me aseguro de cancelar el timer de progreso pase lo que pase (éxito o error).
        for t in timer_ref:
            t.cancel() # Cancelo el timer
        
        # Al terminar, imprimo un salto de línea para que el siguiente log no escriba encima (solo si hay consola).
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

    except (OSError, IOError) as e:
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
        logger.warning(f"⚠️  No se pudo determinar el archivo principal en {dir_path.name}: {e}")
        return None
