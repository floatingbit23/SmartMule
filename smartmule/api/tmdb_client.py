import logging
import requests
from typing import Optional

from smartmule.config import TMDB_BASE_URL, TMDB_BEARER_TOKEN, API_TIMEOUT

logger = logging.getLogger("SmartMule.api.tmdb")

class TMDBClient:
    """
    Cliente para la API v3 de The Movie Database.
    Usa el Bearer Token para autenticar las peticiones y busca películas y series.
    """

    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {TMDB_BEARER_TOKEN}",
            "accept": "application/json"
        }

    def _get(self, endpoint: str, params: dict) -> Optional[dict]:
        """Realiza la petición HTTP GET base gestionando timeouts y errores de red."""
        
        if not TMDB_BEARER_TOKEN or TMDB_BEARER_TOKEN == "tu_bearer_token_aqui":
            logger.error("❌ Token de TMDB no configurado en .env")
            return None

        url = f"{TMDB_BASE_URL}{endpoint}"
        try:
            response = requests.get(
                url, headers=self.headers, params=params, timeout=API_TIMEOUT
            )
            
            # Rate Limiting de TMDB v3 (aunque retiraron el límite escrito, pueden devolver 429).
            if response.status_code == 429:
                logger.warning("⚠️  Rate Limit de TMDB alcanzado (429). Abortando consulta temporalmente.")
                return None
                
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error conectando a TMDB: {e}")
            return None

    def search_movie(self, title: str, year: Optional[int] = None) -> Optional[dict]:
        """
        Busca una película por título y opcionalmente año en TMDB.
        Devuelve el primer mejor resultado.
        """
        params = {
            "query": title,
            "language": "es-ES",
            "page": 1,
            "include_adult": "true" # Podemos tener contenido variado.
        }
        if year:
            params["primary_release_year"] = year

        data = self._get("/search/movie", params)
        if data and "results" in data and len(data["results"]) > 0:
            return data["results"][0]
        
        return None

    def search_tv(self, title: str, year: Optional[int] = None) -> Optional[dict]:
        """
        Busca una serie por título y opcionalmente año de primera emisión en TMDB.
        Devuelve el primer mejor resultado.
        """
        params = {
            "query": title,
            "language": "es-ES",
            "page": 1,
            "include_adult": "true"
        }
        if year:
            params["first_air_date_year"] = year

        data = self._get("/search/tv", params)
        if data and "results" in data and len(data["results"]) > 0:
            return data["results"][0]
        
        return None
