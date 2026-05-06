import logging
import requests
import time # Para las esperas de reintento
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
            logger.error("[ERR] Token de TMDB no configurado en .env")
            return None

        # Construimos la URL
        url = f"{TMDB_BASE_URL}{endpoint}"

        # Configuración de reintentos
        max_retries = 3
        retry_delays = [2, 5, 10] # Esperas entre intentos en segundos (backoff exponencial)
        
        # Realizamos la petición HTTP GET con reintentos
        for attempt in range(max_retries):

            try:
                response = requests.get(
                    url, headers=self.headers, params=params, timeout=API_TIMEOUT
                )
                
                # Gestión del Rate Limiting de TMDB v3
                if response.status_code == 429: # HTTP 429: Too Many Requests
                    wait_time = retry_delays[attempt]
                    logger.warning(f"[WARN]  Rate Limit de TMDB alcanzado. Reintentando en {wait_time}s... (Intento {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue # Siguiente intento del bucle
                    
                response.raise_for_status() # Lanza una excepción para errores persistentes
                return response.json() # Devuelve la respuesta en formato JSON si todo está OK
                
            except requests.exceptions.RequestException as e:
                # Si fallamos por red, esperamos antes de reintentar
                if attempt < max_retries - 1:
                    wait_time = retry_delays[attempt]
                    logger.warning(f"[WARN]  Error de red con TMDB ({e}). Reintentando en {wait_time}s... (Intento {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    logger.error(f"[ERR]  Error definitivo conectando a TMDB tras {max_retries} intentos: {e}")
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

    # Función para obtener los detalles completos de una película
    def get_movie_details(self, movie_id: int, language: str = "es-ES") -> Optional[dict]:

        """Obtiene los detalles completos de una película, incluyendo runtime."""

        params = {"language": language}
        return self._get(f"/movie/{movie_id}", params)

    # Función para obtener los detalles completos de una serie
    def get_tv_details(self, tv_id: int, language: str = "es-ES") -> Optional[dict]:

        """Obtiene los detalles completos de una serie, incluyendo episode_run_time."""

        params = {"language": language}
        return self._get(f"/tv/{tv_id}", params)

    # Función para obtener los créditos de una película (Directores, Actores...)
    def get_movie_credits(self, movie_id: int) -> Optional[dict]:
        """Obtiene los créditos (cast y crew) de una película."""
        return self._get(f"/movie/{movie_id}/credits", {})

    # Función para obtener los créditos de una serie (Creadores, Directores...)
    def get_tv_credits(self, tv_id: int) -> Optional[dict]:
        """Obtiene los créditos (cast y crew) de una serie."""
        return self._get(f"/tv/{tv_id}/credits", {})

    # Función para obtener las palabras clave (Keywords) de una película
    def get_movie_keywords(self, movie_id: int) -> Optional[dict]:
        """Obtiene las palabras clave de una película."""
        return self._get(f"/movie/{movie_id}/keywords", {})

    # Función para obtener las palabras clave (Keywords) de una serie
    def get_tv_keywords(self, tv_id: int) -> Optional[dict]:
        """Obtiene las palabras clave de una serie."""
        return self._get(f"/tv/{tv_id}/keywords", {})

    # Mapeo de géneros de TMDB (IDs a nombres bilingües ES | EN)
    _GENRE_MAP = {
        12: "Aventura | Adventure", 
        14: "Fantasía | Fantasy", 
        16: "Animación | Animation",
        18: "Drama | Drama", 
        27: "Terror | Horror", 
        28: "Acción | Action",
        35: "Comedia | Comedy", 
        36: "Historia | History", 
        37: "Western | Western",
        53: "Suspense | Thriller", 
        80: "Crimen | Crime", 
        99: "Documental | Documentary",
        878: "Ciencia ficción | Science Fiction", 
        9648: "Misterio | Mystery",
        10402: "Música | Music", 
        10749: "Romance | Romance", 
        10751: "Familia | Family",
        10752: "Bélica | War", 
        10759: "Acción y Aventura | Action & Adventure",
        10762: "Infantil | Kids", 
        10763: "Noticias | News", 
        10764: "Reality | Reality",
        10765: "Ciencia ficción y Fantasía | Sci-Fi & Fantasy", 
        10766: "Culebrón | Soap",
        10767: "Entrevista | Talk", 
        10768: "Guerra y Política | War & Politics",
        10770: "Película de TV | TV Movie"
    }

    def get_genre_names(self, genre_ids: list) -> str:
        """Mapea IDs de género a nombres bilingües de forma instantánea."""
        names = [self._GENRE_MAP.get(gid) for gid in genre_ids if self._GENRE_MAP.get(gid)]
        return ", ".join(names)
