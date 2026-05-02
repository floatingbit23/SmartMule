import logging
import requests
import time
from typing import Optional

from smartmule.config import MUSICBRAINZ_BASE_URL, CONTACT_EMAIL_USER_AGENT, API_TIMEOUT

logger = logging.getLogger("SmartMule.api.musicbrainz")

class MusicBrainzClient:
    """
    Cliente para la API de búsqueda de MusicBrainz.
    MusicBrainz exige un User-Agent identificativo y limita a 1 petición por segundo (req/s)
    para uso anónimo (sin auth).
    """

    def __init__(self):
        self.headers = {
            "User-Agent": f"SmartMule/1.0 ( {CONTACT_EMAIL_USER_AGENT} )",
            "Accept": "application/json"
        }
        self.last_request_time = 0.0
        self.min_delay = 1.05  # Tiempo mínimo entre peticiones (ligeramente > 1s)

    def _wait_for_rate_limit(self):
        """Bloqueo síncrono para respetar los límites de la API de MusicBrainz."""
        now = time.time()
        time_since_last = now - self.last_request_time
        if time_since_last < self.min_delay:
            time.sleep(self.min_delay - time_since_last)
        self.last_request_time = time.time()

    def _extract_audio_metadata(self, recording: dict) -> dict:
        """Extrae y limpia metadatos de un objeto 'recording' de MusicBrainz."""
        
        # Inicializamos el diccionario de metadatos con la info básica
        audio_data = {
            "title": recording.get("title"),
            "score": recording.get("score")
        }

        # Artista: MusicBrainz usa artist-credit. Tomamos el nombre del primer artista acreditado.
        artist_credit = recording.get("artist-credit", [])
        audio_data["artist"] = artist_credit[0].get("name") if artist_credit else "Desconocido"

        # Lanzamiento: Buscamos en la lista de releases para obtener el álbum y la fecha de salida.
        releases = recording.get("releases", [])
        if releases:
            first = releases[0]
            # Si el release no tiene título, marcamos como Sencillo o Desconocido
            audio_data["album"] = first.get("title", "Sencillo/Desconocido")
            audio_data["date"] = first.get("date")
        else:
            # Si no hay releases asociados, devolvemos valores por defecto
            audio_data["album"] = "Sencillo/Desconocido"
            audio_data["date"] = None
        
        return audio_data

    def search_audio(self, title: str) -> Optional[dict]:
        """
        Busca un track/canción en MusicBrainz usando el título limpio.
        Implementa reintentos para mayor resiliencia ante fallos de red.
        """

        endpoint = "/recording"

        url = f"{MUSICBRAINZ_BASE_URL}{endpoint}"

        params = {
            "query": title,
            "fmt": "json",
            "limit": 1
        }

        max_retries = 3
        retry_delays = [2, 5, 10]

        for attempt in range(max_retries):

            # Respetamos el límite de tasa (rate limit) de 1 req/s exigido por MusicBrainz
            self._wait_for_rate_limit()

            try:
                # Realizamos la petición GET a la API
                response = requests.get(
                    url, headers=self.headers, params=params, timeout=API_TIMEOUT
                )
                response.raise_for_status()
                data = response.json()
                
                # Buscamos si la respuesta contiene grabaciones (recordings)
                recordings = data.get("recordings", [])

                if recordings:

                    # Si hay resultados, extraemos los metadatos del primer registro
                    return self._extract_audio_metadata(recordings[0])
                    
                # Si no hay grabaciones, devolvemos None
                return None
                
            except requests.exceptions.RequestException as e:
                
                # Si hemos agotado los reintentos, registramos el error y salimos
                if attempt >= max_retries - 1:
                    logger.error(f"[ERR] Error definitivo conectando a MusicBrainz tras {max_retries} intentos: {e}")
                    return None

                # Si quedan intentos, esperamos el tiempo definido antes de volver a probar
                wait_time = retry_delays[attempt]
                logger.warning(f"[WARN] Error conectando a MusicBrainz ({e}). Reintentando en {wait_time}s... ({attempt + 1}/{max_retries})")
                time.sleep(wait_time)
        
        return None
