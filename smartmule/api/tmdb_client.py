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

    # Inicializamos el cliente
    def __init__(self):

        self.headers = {
            "Authorization": f"Bearer {TMDB_BEARER_TOKEN}",
            "accept": "application/json"
        }

    # Método privado para realizar peticiones GET a la API
    def _get(self, endpoint: str, params: dict) -> Optional[dict]:

        """Realiza la petición HTTP GET base gestionando timeouts y errores de red."""
        
        if not TMDB_BEARER_TOKEN or TMDB_BEARER_TOKEN == "tu_bearer_token_aqui":
            logger.error("❌ Token de TMDB no configurado en .env")
            return None

        # Construimos la URL
        url = f"{TMDB_BASE_URL}{endpoint}"

        # Realizamos la petición HTTP GET
        try:
            response = requests.get(
                url, headers=self.headers, params=params, timeout=API_TIMEOUT
            )
            
            # Rate Limiting de TMDB v3
            if response.status_code == 429: # HTTP 429: Too Many Requests
                logger.warning("⚠️  Rate Limit de TMDB alcanzado. Abortando consulta temporalmente...")
                return None
                
            response.raise_for_status() # Lanza una excepción para códigos de error HTTP (4xx o 5xx)

            return response.json() # Devuelve la respuesta en formato JSON
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error conectando a TMDB: {e}")
            return None

    # Método para buscar películas
    def search_movie(self, title: str, year: Optional[int] = None) -> list:

        """
        Busca una película por título y opcionalmente año en TMDB.
        Devuelve una lista con los mejores resultados (máximo 5).
        """

        # Parámetros de búsqueda
        params = {
            "query": title,
            "language": "es-ES", 
            "page": 1, 
            "include_adult": "true" # Incluye contenido para adultos
        }

        # Filtramos por año si se proporciona
        if year:
            params["primary_release_year"] = year

        # Realizamos la búsqueda
        data = self._get("/search/movie", params)

        # Devolvemos los primeros 5 resultados si existen
        if data and "results" in data:
            return data["results"][:5]
        
        return []


    # Método para buscar series
    def search_tv(self, title: str, year: Optional[int] = None) -> list:

        """
        Busca una serie por título y opcionalmente año de primera emisión en TMDB.
        Devuelve una lista con los mejores resultados (máximo 5).
        """

        # Parámetros de búsqueda
        params = {
            "query": title,
            "language": "es-ES", 
            "page": 1, 
            "include_adult": "true" # Incluye contenido para adultos
        }

        # Filtramos por año si se proporciona
        if year:
            params["first_air_date_year"] = year

        # Realizamos la búsqueda
        data = self._get("/search/tv", params)

        # Devolvemos los primeros 5 resultados si existen
        if data and "results" in data:
            return data["results"][:5]
        
        return []
