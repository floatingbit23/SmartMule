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
            self._wait_for_rate_limit() # Siempre respetamos el límite de 1 req/s de MB

            try:
                response = requests.get(
                    url, headers=self.headers, params=params, timeout=API_TIMEOUT
                )
                response.raise_for_status()
                data = response.json()
                
                if data and "recordings" in data and len(data["recordings"]) > 0:
                    recording = data["recordings"][0]
                    
                    audio_data = {
                        "title": recording.get("title"),
                        "score": recording.get("score") 
                    }
                    
                    if "artist-credit" in recording and len(recording["artist-credit"]) > 0:
                        artist = recording["artist-credit"][0].get("name")
                        audio_data["artist"] = artist
                    else:
                        audio_data["artist"] = "Desconocido"
                    
                    if "releases" in recording and len(recording["releases"]) > 0:
                        first_release = recording["releases"][0]
                        audio_data["album"] = first_release.get("title", "Sencillo/Desconocido")
                        audio_data["date"] = first_release.get("date")
                    else:
                        audio_data["album"] = "Sencillo/Desconocido"
                        audio_data["date"] = None
                        
                    return audio_data
                    
                return None
                
            except requests.exceptions.RequestException as e:

                if attempt < max_retries - 1: # Si no es el último intento

                    wait_time = retry_delays[attempt] # Espera exponencial
                    logger.warning(f"⚠️ Error conectando a MusicBrainz ({e}). Reintentando en {wait_time}s... ({attempt + 1}/{max_retries})")
                    time.sleep(wait_time) # Espera antes de reintentar

                else:
                    logger.error(f"❌ Error definitivo conectando a MusicBrainz tras {max_retries} intentos: {e}")
                    return None
        
        return None
