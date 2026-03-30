"""
hasher.py — Implementación del algoritmo de hashing ED2K para SmartMule.

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
import logging
import time
import threading
from pathlib import Path

from Crypto.Hash import MD4  # pycryptodome: implementación del algoritmo MD4

from smartmule.config import ED2K_CHUNK_SIZE # 9,728,000 bytes (9.28 MB)

# Creo un logger específico para este módulo.
logger = logging.getLogger("SmartMule.hasher")

# Función que calcula el hash ED2K de un archivo
def calculate_ed2k(file_path: Path) -> str:

    """
    Calculo el hash ED2K de un archivo leyéndolo por búferes de ED2K_CHUNK_SIZE bytes.
    Durante el cálculo, inicio un timer que loguea el tiempo transcurrido cada 2 segundos.

    Args:
        file_path: Ruta al archivo cuyo hash quiero calcular.

    Returns:
        Hash ED2K como string hexadecimal de 32 caracteres (128 bits).

    Raises:
        FileNotFoundError: Si el archivo no existe.
        OSError: Si no puedo leer el archivo.
    """

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
        output = f"\r{now}  INFO     [\033[97mSmartMule.hasher\033[0m]  🔹  Calculando hash ED2K... ({elapsed_str} transcurrido(s))"
        
        sys.stdout.write(output)
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

        chunk_hashes: list[bytes] = [] # Lista para guardar los hashes de cada bloque

        with open(file_path, "rb") as f: # Abro el archivo en modo lectura binaria

            while True: # Bucle infinito

                # Leo exactamente un bloque (chunk) de ED2K_CHUNK_SIZE bytes.
                # La lectura por búfer garantiza que nunca cargo más de ~9.28 MB en RAM.
                chunk = f.read(ED2K_CHUNK_SIZE)

                # Si el chunk está vacío, he llegado al final del archivo.
                if not chunk:
                    break # Rompo el bucle

                # Calculo el MD4 de este bloque y guardo el digest en bytes (no en formato hexadecimal) 
                # porque necesito concatenarlos para calcular el hash final.

                chunk_hashes.append(MD4.new(chunk).digest())  # 16 bytes (en binario) por cada chunk, añadidos a la lista

        # Calculo el hash final según el estándar ED2K:
        if len(chunk_hashes) == 0:
            # Caso especial: archivo vacío.
            # El MD4 de una cadena vacía es un valor conocido.
            return MD4.new(b"").hexdigest().upper()

        elif len(chunk_hashes) == 1:
            # Caso especial: archivo pequeño (un solo bloque).
            # El hash ED2K es directamente el MD4 del bloque único.
            return chunk_hashes[0].hex().upper()

        else:
            # Caso general: múltiples bloques.
            # Concateno todos los MD4s en binario y calculo el MD4 de esa concatenación.
            all_hashes_concatenated = b"".join(chunk_hashes) # Concateno todos los MD4s en binario
            return MD4.new(all_hashes_concatenated).hexdigest().upper() # Calculo el MD4 de esa concatenación

    finally:
        # Me aseguro de cancelar el timer de progreso pase lo que pase (éxito o error).
        for t in timer_ref:
            t.cancel() # Cancelo el timer
        
        # Al terminar, imprimo un salto de línea para que el siguiente log no escriba encima.
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
