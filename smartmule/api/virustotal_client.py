import logging
import requests
import hashlib
import time
from typing import Optional

from smartmule.config import VIRUSTOTAL_BASE_URL, VIRUSTOTAL_API_KEY, API_TIMEOUT

logger = logging.getLogger("SmartMule.api.virustotal")

class VirusTotalClient:

    """
    Cliente para la API v3 de VirusTotal.
    Se requiere API Key para cualquier operación.
    """

    # Constructor de la clase VirusTotalClient
    def __init__(self):

        self.headers = {
            "x-apikey": VIRUSTOTAL_API_KEY,
            "accept": "application/json" # Formato de respuesta de la API
        }
        
        self.last_request_time = 0.0 # Tiempo desde la última petición a VirusTotal
        self.min_delay = 15.1  # VirusTotal Free API permite 4 req/minuto (1 cada 15 segs)


    # Método para esperar el tiempo necesario para no sobrepasar la tasa de peticiones
    def _wait_for_rate_limit(self):

        """Bloqueo síncrono para respetar los límites de la API (En caso de usar Free tier)"""

        now = time.time()
        time_since_last = now - self.last_request_time

        # Si ha pasado menos de 15.1 segundos desde la última petición, espera el tiempo necesario
        if time_since_last < self.min_delay: 
            time.sleep(self.min_delay - time_since_last)
            
        self.last_request_time = time.time() # Actualiza el tiempo de la última petición


    # Método para calcular el hash SHA-256 de un archivo
    def _calculate_sha256(self, filepath: str) -> Optional[str]:
        """
        Calcula el hash SHA-256 de un archivo físico por chunks para no colapsar la RAM.
        Devuelve el hash en formato hexadecimal o None si ocurre un error de lectura.
        """
        
        # Inicializa el objeto hash de la librería estándar hashlib
        sha256_hash = hashlib.sha256()

        try:
            # Abrimos el archivo en modo lectura binaria (rb) para procesar sus bytes
            with open(filepath, "rb") as f:

                # Leemos el archivo en bloques de 4K (4096 bytes) para no saturar la memoria RAM.
                # iter(lambda: f.read(4096), b"") lee bloques hasta encontrar el final del archivo (b"").
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)

            # Retornamos el hash calculado en formato hexadecimal legible
            return sha256_hash.hexdigest()

        except OSError as e:
            # Capturamos errores de sistema (archivo no encontrado, permisos, etc.)
            logger.error(f"[ERR] Error leyendo archivo para calcular SHA-256: {e}")
            # Retornamos None para señalizar que el cálculo no fue posible
            return None


    def scan_software(self, filepath: str) -> Optional[dict]:

        """
        Calcula el hash de un archivo y lo busca en VirusTotal.
        Devuelve el bloque last_analysis_stats.
        """

        if not VIRUSTOTAL_API_KEY:
            logger.error("[ERR] VIRUSTOTAL_API_KEY no encontrada. No se puede realizar el triaje de seguridad.")
            return None
            
        file_hash = self._calculate_sha256(filepath) # Calcula el hash SHA-256 del archivo

        if not file_hash:
            return None
            
        logger.info(f"[WAIT] Hash SHA-256 calculado: {file_hash}")
        logger.info("[INFO] Consultando base mundial...")

        self._wait_for_rate_limit()

        endpoint = f"/files/{file_hash}" # Endpoint para buscar el hash en VirusTotal
        url = f"{VIRUSTOTAL_BASE_URL}{endpoint}" # URL completa de la petición

        try:
            response = requests.get(url, headers=self.headers, timeout=API_TIMEOUT)
            
            # Si VT no lo tiene en su BD (archivo desconocido nunca subido) devuelve 404
            if response.status_code == 404:
                logger.warning("[WARN] [VT] Archivo desconocido en VirusTotal. Nadie lo ha analizado aún!")
                return {
                    "stats": {"malicious": 0, "suspicious": -1, "undetected": 100},
                    "results": {}, # No hay resultados por motor si no existe el archivo
                    "hash": file_hash
                }

            response.raise_for_status() # Lanza excepción si hay error HTTP
            data = response.json() # Convierte la respuesta JSON a diccionario
            
            if data and "data" in data and "attributes" in data["data"]: # Comprueba si la respuesta contiene los datos esperados
                
                # Obtenemos los bloques de estadísticas (resumen) y resultados (detallado)
                attributes = data["data"]["attributes"]
                stats = attributes.get("last_analysis_stats")
                results = attributes.get("last_analysis_results", {})

                return {
                    "stats": stats, 
                    "results": results, # Diccionario con el detalle de cada motor
                    "hash": file_hash
                }
                
            return None # Devuelve None si la respuesta no contiene los datos esperados
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[ERR] Error conectando a VirusTotal: {e}")
            return None
