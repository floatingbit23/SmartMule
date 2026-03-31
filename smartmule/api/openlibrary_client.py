import logging
import requests
import time
from typing import Optional

from smartmule.config import OPENLIBRARY_BASE_URL, CONTACT_EMAIL_USER_AGENT, API_TIMEOUT

logger = logging.getLogger("SmartMule.api.openlibrary")

class OpenLibraryClient:

    """
    Cliente para la API de búsqueda de OpenLibrary.
    Se rige por el User-Agent para conseguir hasta 3 peticiones por segundo (req/s).
    """

    def __init__(self):
        self.headers = {
            "User-Agent": CONTACT_EMAIL_USER_AGENT,
            "accept": "application/json"
        }
        self.last_request_time = 0.0
        self.min_delay = 0.35  # Tiempo mínimo entre peticiones (ligeramente > 1/3s)

    def _wait_for_rate_limit(self):
        """Bloqueo síncrono para respetar los límites de la API de OpenLibrary."""
        now = time.time()
        time_since_last = now - self.last_request_time
        if time_since_last < self.min_delay:
            time.sleep(self.min_delay - time_since_last)
        self.last_request_time = time.time()

    def search_book(self, title: str) -> Optional[dict]:
        """
        Busca un libro en OpenLibrary usando el título limpio.
        Implementa reintentos para mayor resiliencia ante fallos de red.
        """
        endpoint = "/search.json"
        url = f"{OPENLIBRARY_BASE_URL}{endpoint}"
        params = {
            "q": title,
            "limit": 1,
            "fields": "title,author_name,first_publish_year,cover_i,key,subject,ratings_average"
        }

        max_retries = 3
        retry_delays = [2, 5, 10]

        for attempt in range(max_retries):
            self._wait_for_rate_limit()

            try:
                response = requests.get(
                    url, headers=self.headers, params=params, timeout=API_TIMEOUT
                )
                response.raise_for_status()
                data = response.json()
                
                if data and "docs" in data and len(data["docs"]) > 0:
                    book = data["docs"][0]
                    
                # Transformamos la key de arreglo a string seguro si es necesario
                # (OpenLibrary devuelve a veces author_name como array)
                    if isinstance(book.get("author_name"), list) and len(book["author_name"]) > 0:
                        book["author_name_str"] = book["author_name"][0]
                    else:
                        book["author_name_str"] = "Autor Desconocido"
                    
                    return book
                    
                return None
                
            except requests.exceptions.RequestException as e:

                if attempt < max_retries - 1: # Si no es el último intento

                    wait_time = retry_delays[attempt] # Espera exponencial
                    logger.warning(f"⚠️ Error conectando a OpenLibrary ({e}). Reintentando en {wait_time}s... ({attempt + 1}/{max_retries})")
                    time.sleep(wait_time) # Espera antes de reintentar

                else:
                    logger.error(f"❌ Error definitivo conectando a OpenLibrary tras {max_retries} intentos: {e}")
                    return None
        
        return None
