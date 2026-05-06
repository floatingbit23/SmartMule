import logging
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from smartmule.parsers.regex_parser import parse_filename, EXTENSION_MAPPING
from smartmule.parsers.llm_parser import parse_with_llm, analyze_media_content
from smartmule.parsers.media_inspector import inspect_media_file
from smartmule.api.tmdb_client import TMDBClient
from smartmule.api.openlibrary_client import OpenLibraryClient
from smartmule.api.musicbrainz_client import MusicBrainzClient
from smartmule.api.virustotal_client import VirusTotalClient
from smartmule.config import TMDB_BEARER_TOKEN, TMDB_BASE_URL, IGNORED_EXTENSIONS

logger = logging.getLogger("SmartMule.engine")

class MetadataEngine:

    """
    Cerebro de SmartMule: Orquestador Multicanal del Pipeline de Enriquecimiento.
    
    Implementa una arquitectura de cascada inteligente para la identificación y clasificación 
    de medios, optimizando recursos mediante cuatro capas de resolución:

    1. Capa de Triaje (Regex): Extracción determinista de patrones estándar. 
    Si la confianza es alta, se optimiza el flujo evitando el coste de la IA.
   
    2. Capa Semántica (LLM): Análisis heurístico mediante IA (Gemini/LM Studio) para resolver 
       nombres de archivos altamente ofuscados o con estructuras no convencionales.
    
    3. Capa de Inspección Técnica (FFmpeg): Extracción de metadatos físicos (duración, 
       resolución) utilizada como factor de desempate (tie-breaking) en homónimos.
    
    4. Capa de Enriquecimiento y Seguridad: Consolidación de datos vía APIs oficiales 
       (TMDB, MusicBrainz, OpenLibrary) y triaje de seguridad preventivo con VirusTotal.
    """
    
    # Constructor de la clase MetadataEngine
    def __init__(self, db=None):

        self.db = db # Instancia de HashDatabase (opcional, inyectada por QueueManager)
        self.tmdb = TMDBClient() # Instancio la clase TMDBClient
        self.openlibrary = OpenLibraryClient() # Instancio la clase OpenLibraryClient
        self.musicbrainz = MusicBrainzClient() # Instancio la clase MusicBrainzClient
        self.virustotal = VirusTotalClient() # Instancio la clase VirusTotalClient


    # Método para identificar el archivo o carpeta
    def identify_file(self, filename: str, filepath: str = None, ed2k_hash: str = None) -> dict:
        """
        Orquestación de la identificación: Regex -> Análisis IA -> API.
        Ahora soporta carpetas buscando un archivo representante.
        Si se proporciona ed2k_hash y BBDD, verifica la caché antes de gastar recursos de API.
        """
        filename, _, technical_target = self._resolve_target(filename, filepath)
        logger.info(f"[i] Identificando archivo [{filename}]...")

        # --- CACHE DE BÚSQUEDAS (API Optimization) ---
        if self.db and ed2k_hash:
            cached_data = self.db.get_metadata_cache(ed2k_hash)
            if cached_data:
                logger.info(f"[CACHE] Hit! Metadatos recuperados para {ed2k_hash[:8]}...")
                return cached_data

        # ================= CAPA 1 y 2: Regex Simple y Análisis IA =================
        data = self._apply_regex_and_ai(filename)

        titulo_limpio = data.get("title", "")
        orig_media = data.get("media_type", "unknown")
        orig_year = data.get("year")
        
        logger.info(f"[OK] Nombre limpio: '{titulo_limpio}' ({orig_media})")

        # ================= CAPA 2.5: Antimalware Semántico (Contenedores) =================
        if self._inspect_compressed(data, filename, technical_target):
            return data

        # ================= CAPA 2.7: Inspección Técnica (FFmpeg) =================

        # Solo para video, para permitir el desempate (Tie-Breaking) por duración.
        if orig_media in ["video", "movie", "series"] and technical_target:
            tech_data = inspect_media_file(technical_target)
            if tech_data.get("is_media"):
                data["technical"] = tech_data
                if tech_data.get("width") and not data.get("resolution"):
                    # Si el regex no encontró resolución pero ffprobe sí -> la actualizamos
                    h = tech_data["height"]
                    if h >= 2160: data["resolution"] = "2160p"
                    elif h >= 1080: data["resolution"] = "1080p"
                    elif h >= 720: data["resolution"] = "720p"

        # ================= CAPA 3: APIs Oficiales y Triaje VT =================
        self._enrich_with_apis(data, filename, technical_target)

        # ================= CAPA 4: Fallback Plan C (Usar IA si las APIs fallaron) =================

        # Si las APIs no devolvieron nada pero NO se usó la IA (porque Regex arrojó "high confidence"),
        # entonces le damos una última oportunidad a la IA para corregir el posible falso positivo del regex.
        if not data.get("api_data") and not data.get("_ai_used"):

            # Solo para tipos de medios que dependen de APIs (películas, series, libros, audio)
            if data.get("media_type") in ["video", "movie", "series", "book", "audio", "unknown"]:
                
                logger.info(f"[PLAN C] APIs sin resultados para '{titulo_limpio}'. Invocando IA como refuerzo...")
                data = self._apply_ai_layer(filename, data)
                
                # Si la IA nos ha dado datos distintos, reintentamos búsqueda en APIs
                if (data.get("title") != titulo_limpio or 
                    data.get("media_type") != orig_media or 
                    data.get("year") != orig_year):

                    logger.info(f"[RETRY] Reintentando búsqueda con datos corregidos por IA: '{data.get('title')}' ({data.get('media_type')})...")
                    self._enrich_with_apis(data, filename, technical_target)

        self._log_metadata_card(data)

        # Guardamos en caché
        if self.db and ed2k_hash:
            self.db.set_metadata_cache(ed2k_hash, data)

        return data


    # ==================== MÉTODOS PRIVADOS DE RESOLUCIÓN ====================


    # Función que gestiona la lógica de si es un directorio o archivo, y la selección del archivo representante.
    def _resolve_target(self, filename: str, filepath: str) -> tuple[str, str, str]:

        # Se inicializan los valores de nombre, display y target
        item_path = Path(filepath) if filepath else Path(filename)
        display_name = filename
        technical_target = filepath or filename

        # Si es un directorio, se busca el archivo representativo
        if item_path.is_dir():
            logger.info(f"[DIR] Procesando directorio: {display_name}")
            representative = self._find_representative_file(item_path)
            
            # Si se encuentra un archivo representativo, se actualizan los valores
            if representative:
                technical_target = str(representative)
                logger.info(f"[i] Archivo representante encontrado: {representative.name}")
                
                # Si el nombre del archivo es genérico (ej. movie, video, cd1, cd2), se usa el nombre de la carpeta
                if len(representative.stem) < 5 or representative.stem.lower() in ["movie", "video", "cd1", "cd2"]:
                    logger.info("[INFO] Usando nombre de carpeta para identificar (nombre de archivo genérico)")
                # En caso contario, se usa el nombre del archivo representante    
                else:
                    filename = representative.name

            # Si no se encuentra un archivo representativo, se usa el filepath
            else:
                technical_target = filepath
                logger.warning(f"[WARN] No se encontró un archivo multimedia claro en la carpeta {display_name}")

        return filename, display_name, technical_target


    # Función que aplica el análisis de Regex y IA.
    def _apply_regex_and_ai(self, filename: str) -> dict:

        data = parse_filename(filename)
        data["_ai_used"] = False
        
        # Capa 2: IA (Refuerzo si confianza es baja o si es un medio multilingüe (libro/audio))
        is_low_confidence = data.get("confidence") == "low"
        is_bilingual_media = data.get("media_type") in ["book", "audio"]

        if is_low_confidence or is_bilingual_media:
            data = self._apply_ai_layer(filename, data)
            
        return data

    # Función que aplica el análisis de IA.
    def _apply_ai_layer(self, filename: str, data: dict) -> dict:

        """Aplica la capa de inteligencia artificial para limpieza semántica."""

        logger.info("[AI] Iniciando análisis semántico con LLM...")
        
        context_data = {
            "languages": data.get("languages"),
            "subtitles": data.get("subtitles")
        }

        ai_data = parse_with_llm(filename, context=context_data)
        
        # Si el análisis de IA es exitoso, se actualizan los valores
        if ai_data.get("confidence") != "failed":

            ai_data["extension"] = data.get("extension")
            ai_data["resolution"] = data.get("resolution", "")
            ai_data["languages"] = data.get("languages", "")
            ai_data["subtitles"] = data.get("subtitles", "")
            
            # Blindaje de categoría: Si Regex detectó un tipo de medio fuerte (info (.emulecollections, .torrent), subs (.srt), software) o la IA falló, respetamos el media_type original
            strong_types = ["info", "subtitles", "software"]

            # Si el Regex detectó un "tipo de medio fuerte"
            if (data.get("media_type") in strong_types or 
                not ai_data.get("media_type") or  # O la IA no pudo determinar un tipo de medio
                ai_data.get("media_type") == "unknown"): # O la IA no pudo determinar un tipo de medio
                ai_data["media_type"] = data.get("media_type")
                
            ai_data["_ai_used"] = True
            return ai_data

        else:
            logger.warning("[ERROR] El análisis por IA falló. Volviendo al resultado de Regex...")
            return data


    # Función que inspecciona archivos comprimidos.
    # Devuelve un booleano para indicar si el proceso debe abortarse por seguridad.
    def _inspect_compressed(self, data: dict, filename: str, technical_target: str) -> bool:

        media_type = data.get("media_type")

        # Si el tipo de medio es "compressed" y se proporciona un target técnico, se inspecciona el archivo.
        if media_type == "compressed" and technical_target:

            from smartmule.parsers.archive_inspector import inspect_archive
                
            logger.info("[ZIP] Archivo comprimido detectado. Iniciando análisis...")
            inspection = inspect_archive(technical_target, expected_type=media_type)
            
            # Si el archivo es malicioso o sospechoso, se aborta el proceso por seguridad
            if inspection["status"] in ["MALICIOUS", "SUSPICIOUS"]:

                logger.warning("[BLOCK] Triaje de seguridad abortado por Inconsistencia Semántica o Cifrado.")
                
                veredicto = "\033[91mMALICIOUS !!!\033[0m" if inspection["status"] == "MALICIOUS" else "\033[93mSUSPICIOUS !\033[0m"
                
                data["api_data"] = {
                    "source": "Semantic Inspector",
                    "official_title": filename,
                    "veredicto": veredicto,
                    "malicious_count": 99 if inspection["status"] == "MALICIOUS" else 1, 
                    "suspicious_count": 0,
                    "url": "N/A (Semantic Malware)"
                }

                return True
                
            # Si el archivo es seguro y se detecta un tipo de medio, se reclasifica el media_type y se actualiza el archivo representante.
            if inspection["status"] == "SAFE" and inspection.get("detected_media"):
                
                logger.info(f"[RETRY] Reclasificando media_type: 'compressed' -> '{inspection['detected_media']}'")
                data["media_type"] = inspection["detected_media"]

                # Si se encuentra un archivo representante, se actualiza
                if inspection.get("representative"):
                    data["internal_representative"] = Path(inspection["representative"]).name

        return False


    # Función que enriquece los datos con información de APIs externas.
    def _enrich_with_apis(self, data: dict, filename: str, technical_target: str):

        """
        Delegador principal que, dependiendo del "media_type", redirige el tráfico a métodos ultra-específicos:
            - _query_tmdb: Lógica de scoring y desempate de películas/series.
            - _query_openlibrary: Lógica y filtros de similitud para libros.
            - _query_musicbrainz: Limpieza NFKD (Normalización Unicode) y filtros para audio.
            - _scan_software: Triaje exhaustivo con VirusTotal para ejecutables
        """

        titulo_limpio = data.get("title", "")
        media_type = data.get("media_type", "unknown")
        year = data.get("year")

        if media_type in ["video", "series", "movie"]: 
            self._query_tmdb(data, titulo_limpio, year)

        elif media_type == "book":
            self._query_openlibrary(data, titulo_limpio)

        elif media_type == "audio":
            self._query_musicbrainz(data, titulo_limpio, data.get("author"))

        elif media_type == "subtitles":
            logger.info("[SUBS] Subtítulos detectados.")

        elif media_type in ["software", "compressed"]:
            self._scan_software(data, filename, technical_target)

        else:
            logger.info("[!] Tipo de medio desconocido, omitiendo búsqueda en APIs.")


    # Función que realiza la búsqueda en TMDB y aplica scoring.
    def _query_tmdb(self, data: dict, titulo_limpio: str, year: str):

        if data.get("season"):
            logger.info("[TV] Buscando en TMDB como Serie...")
            results = self.tmdb.search_tv(titulo_limpio, year) 

        else:
            logger.info("[MOVIE] Buscando en TMDB como Película...")
            results = self.tmdb.search_movie(titulo_limpio, year)

        if not results:
            titulo_alternativo = self._get_plan_b_title(titulo_limpio)

            if titulo_alternativo:
                logger.info(f"[RETRY] Plan B: Reintentando búsqueda sin 'AKA' -> '{titulo_alternativo}'")

                if data.get("season"):
                    results = self.tmdb.search_tv(titulo_alternativo, year)

                else:
                    results = self.tmdb.search_movie(titulo_alternativo, year)

        """
        Sistema de Scoring Heurístico para Desempate (Tie-Breaking):
        
        Ante múltiples resultados de la API, aplicamos un sistema de puntos (scoring) para seleccionar la mejor coincidencia:
        
        1. Título Exacto (+50 pts): Si el nombre del archivo (limpio) coincide exactamente con el de la API.

        2. Año de Producción (+30 pts): Si el año extraído del archivo coincide con la fecha de lanzamiento.

        3. Validación Técnica (FFmpeg) (+40 pts): El factor más fiable. Comparamos la duración real del archivo con el 'runtime' oficial de TMDB:
            - Diferencia <= 5 min: +40 pts (Bonus de confianza máxima).
            - Diferencia <= 15 min: +15 pts (Cierta tolerancia por versiones extendidas/cortadas).
            
        Este sistema permite distinguir con precisión entre películas homónimas (ej. "Solaris" 1972 vs 2002).
        """

        if results:

            best_match = results[0]
            best_score = -1 

            for res in results:

                score = 0

                # Obtenemos el título y la fecha de la API
                res_title = res.get("title") or res.get("name")
                res_date = res.get("release_date") or res.get("first_air_date") or ""
                
                # 1. Título Exacto
                if res_title.lower() == titulo_limpio.lower():
                    score += 50

                # 2. Año de Producción
                if year and str(year) in res_date:
                    score += 30
                
                # --- TIE-BREAKING POR DURACIÓN (FFmpeg) ---
                # Si tenemos datos técnicos del archivo, comparamos con la duración de TMDB
                tech = data.get("technical")
                if tech and tech.get("duration_sec"):
                    file_dur_min = tech["duration_sec"] // 60
                    
                    # Para obtener la duración real (runtime), necesitamos pedir los detalles del ID
                    res_id = res.get("id")

                    if res_id:
                        # Pedimos el runtime para desempatar (solo necesitamos este dato aquí)
                        if data.get("season"):
                            # Pedimos detalles en inglés para obtener runtime y sinopsis original
                            details = self.tmdb.get_tv_details(res_id, language="en-US")
                            
                            durations = details.get("episode_run_time", []) if details else []

                            api_runtime = durations[0] if durations else 0
                        else:
                            # Pedimos detalles en inglés para obtener runtime y sinopsis original
                            details = self.tmdb.get_movie_details(res_id, language="en-US")
                            api_runtime = details.get("runtime", 0) if details else 0
                        
                        if api_runtime > 0:
                            diff = abs(file_dur_min - api_runtime)
                            if diff <= 5: # Margen de 5 minutos
                                score += 40
                                logger.info(f"[MATCH] Duración coincide ({api_runtime} min). Bonus +40.")
                            elif diff <= 15:
                                score += 15
                                logger.debug(f"[DIFF] Duración cercana ({api_runtime} min). Bonus +15.")

                if score > best_score:
                    best_score = score
                    best_match = res 

            # ================= ENRIQUECIMIENTO PROFUNDO DEL GANADOR =================
            # Ahora que tenemos el mejor resultado, nos aseguramos de que tenga TODOS los datos
            # aunque no hayamos entrado en el bloque de Tie-Breaking por duración.
            
            api_result = best_match
            res_id = api_result.get("id")

            if res_id:
                logger.info(f"[API] Enriqueciendo ficha completa para ID: {res_id}...")
                
                # 1. Detalles base (Runtime, Colección, Título Original, Sinopsis EN)
                if data.get("season"):
                    details = self.tmdb.get_tv_details(res_id, language="en-US")
                else:
                    details = self.tmdb.get_movie_details(res_id, language="en-US")
                
                if details:
                    api_result["overview_en"] = details.get("overview")
                    api_result["original_title"] = details.get("original_title") or details.get("original_name", "")
                    
                    if not data.get("season"):
                        collection = details.get("belongs_to_collection")
                        if collection and isinstance(collection, dict):
                            api_result["collection"] = collection.get("name", "")

                # 2. Créditos (Director y Reparto)
                media_credits = None
                if data.get("season"):
                    media_credits = self.tmdb.get_tv_credits(res_id)
                else:
                    media_credits = self.tmdb.get_movie_credits(res_id)
                
                if media_credits:
                    
                    # Buscamos Directores
                    directors = [m.get("name") for m in media_credits.get("crew", []) if m.get("job") == "Director"]
                    if directors:
                        api_result["director"] = ", ".join(directors)
                    elif data.get("season") and details:
                        # Fallback series: Creadores
                        creators = details.get("created_by", [])
                        if creators:
                            api_result["director"] = ", ".join([c.get("name") for c in creators])

                    # Actores
                    cast_list = media_credits.get("cast", [])
                    top_actors = [m.get("name") for m in cast_list[:10]]
                    if top_actors:
                        api_result["cast"] = ", ".join(top_actors)

                # 3. Keywords
                keywords_data = None
                if data.get("season"):
                    keywords_data = self.tmdb.get_tv_keywords(res_id)
                    if keywords_data:
                        k_list = [k.get("name") for k in keywords_data.get("results", [])]
                        api_result["keywords"] = ", ".join(k_list)
                else:
                    keywords_data = self.tmdb.get_movie_keywords(res_id)
                    if keywords_data:
                        k_list = [k.get("name") for k in keywords_data.get("keywords", [])]
                        api_result["keywords"] = ", ".join(k_list)
            poster = f"https://image.tmdb.org/t/p/w500{api_result.get('poster_path')}" if api_result.get("poster_path") else None
            
            # --- MEJORA: Actualizamos el tipo de medio oficial ---
            # Si venía como 'video' genérico pero TMDB lo ha encontrado, lo promovemos a su tipo real (movie/series)
            if data.get("season"):
                data["media_type"] = "series"
            else:
                data["media_type"] = "movie"

            # Extraemos géneros bilingües usando el cliente
            genres_str = self.tmdb.get_genre_names(api_result.get("genre_ids", []))

            # Guardamos los datos obtenidos de TMDB
            data["api_data"] = {
                "source": "TMDB",
                "official_title": api_result.get("name") or api_result.get("title"),
                "date": api_result.get("first_air_date") or api_result.get("release_date"),
                "score": api_result.get("vote_average"),
                "poster_url": poster,
                "overview": api_result.get("overview"),
                "overview_en": api_result.get("overview_en"),
                "genres": genres_str,
                "director": api_result.get("director", ""),
                "cast": api_result.get("cast", ""),
                "original_title": api_result.get("original_title", ""),
                "collection": api_result.get("collection", ""),
                "keywords": api_result.get("keywords", "")
            }

    
    # Función que realiza la búsqueda en OpenLibrary y aplica scoring.
    def _query_openlibrary(self, data: dict, titulo_limpio: str):
        logger.info("[BOOK] Buscando en OpenLibrary como Libro...")
        
        original_title = data.get("original_title")
        api_result = None
        best_similitud = 0
        
        def _get_best_result(query: str, target_author: str = ""):
            books = self.openlibrary.search_books(query)
            if not books:
                return None, 0, False

            best_res = None
            max_sim = 0
            best_author_match = False
            best_is_primary = False

            for res in books:
                # Normalización de datos de la API
                api_title = res.get("title", "").strip()
                api_authors_raw = res.get("author_name", [])
                if isinstance(api_authors_raw, str): api_authors_raw = [api_authors_raw]
                api_authors = [a.lower().strip() for a in api_authors_raw]
                
                # Similitud de título
                sim = SequenceMatcher(None, query.lower(), api_title.lower()).ratio()
                
                # Comprobación de autor
                author_match = False
                author_sim_score = 0
                is_primary = False
                
                if target_author:
                    for idx, a_api in enumerate(api_authors):
                        # Match directo o fuzzy
                        s = SequenceMatcher(None, target_author, a_api).ratio()
                        if target_author in a_api or a_api in target_author or s > 0.8:
                            author_match = True
                            if s > author_sim_score: author_sim_score = s
                            if idx == 0: is_primary = True
                            if s > 0.8:
                                logger.debug(f"[i] Candidato: '{api_title}' | Autor Match: '{a_api}' ({int(s*100)}%) | Primary: {is_primary}")
                
                logger.debug(f"[DEBUG] Evaluando: '{api_title}' (Sim: {sim:.2f}) | Match Autor: {author_match} | Primary: {is_primary}")

                # Lógica de actualización del mejor resultado:
                update = False
                
                # Definimos qué es un "Match Fuerte" (Autor principal + Título muy similar)
                is_strong_match = author_match and is_primary and sim >= 0.8
                best_was_strong = best_author_match and best_is_primary and max_sim >= 0.8

                if is_strong_match and not best_was_strong:
                    update = True # El primer match fuerte siempre gana a lo anterior
                elif is_strong_match and best_was_strong:
                    # Desempate entre dos matches fuertes: Prioridad absoluta a la antigüedad
                    current_year = res.get("first_publish_year")
                    best_year = best_res.get("first_publish_year")
                    
                    if current_year and best_year:
                        if current_year < best_year:
                            update = True
                            logger.debug(f"[i] Prefiriendo obra original por antigüedad: {current_year} vs {best_year} ('{api_title}')")
                    elif sim > max_sim:
                        # Si no hay años para comparar, volvemos a la similitud de título
                        update = True
                elif not best_was_strong:
                    # Si no hay matches fuertes, seguimos la lógica estándar de similitud
                    if (author_match and not best_author_match) or \
                       (author_match == best_author_match and sim > max_sim):
                        update = True

                if update:
                    best_res, max_sim = res, sim
                    best_is_primary = is_primary
                    if author_match: best_author_match = True

            return best_res, max_sim, best_author_match

        autor_ia = data.get("author", "").lower()

        # Intento 1: Título Limpio (Español)
        api_result, best_similitud, autor_match = _get_best_result(titulo_limpio, autor_ia)
        success = best_similitud >= 0.7
        
        # Intento 2: Título Original (IA / Inglés)
        if not success and original_title:
            logger.info(f"[BOOK] Similitud insuficiente con nombre en español. Probando título original IA: '{original_title}'...")
            res_alt, sim_alt, auth_alt = _get_best_result(original_title, autor_ia)
            if (auth_alt and not autor_match) or (sim_alt > best_similitud):
                api_result, best_similitud, autor_match = res_alt, sim_alt, auth_alt
                success = best_similitud >= 0.7

        # Intento 3: Plan B (Limpieza AKA)
        if not success:
            titulo_alternativo = self._get_plan_b_title(titulo_limpio)
            if titulo_alternativo:
                logger.info(f"[RETRY] Probando limpieza alternativa (sin AKA): '{titulo_alternativo}'")
                res_alt, sim_alt, auth_alt = _get_best_result(titulo_alternativo, autor_ia)
                if (auth_alt and not autor_match) or (sim_alt > best_similitud):
                    api_result, best_similitud, autor_match = res_alt, sim_alt, auth_alt

        if api_result:
            # Umbral dinámico: si el autor coincide, somos más flexibles con el título (60% en vez de 70%)
            umbral_seguridad = 0.6 if autor_match else 0.7

            if autor_match:
                logger.info(f"[MATCH] Autor coincidente encontrado: '{api_result.get('author_name_str')}'.")

            # Validación extra: Si el autor coincide, aceptamos si un título contiene al otro (casos de subtítulos)
            is_substring_match = False
            if autor_match:
                t1 = api_result.get('title', "").lower().strip()
                t2 = titulo_limpio.lower().strip()
                if t1 in t2 or t2 in t1:
                    is_substring_match = True
                    logger.info("[OK] Aceptando por inclusión de título ('%s' contenido en consulta).", t1)

            if best_similitud < umbral_seguridad and not is_substring_match:
                logger.warning("[WARN] Libro descartado por baja similitud (%d%%): '%s' vs consulta. Umbral requerido: %d%%", 
                               int(best_similitud*100), api_result.get('title'), int(umbral_seguridad*100))
                if autor_match:
                    logger.info("[i] Nota: El autor coincidía, pero la diferencia de título sigue siendo excesiva.")
                api_result = None # Descartamos

            else:
                
                if autor_match and best_similitud < 0.7:
                    logger.info("[MATCH] Aceptando por autor coincidente (%d%% similitud).", int(best_similitud*100))
                
                # ÉXITO: Promoción y enriquecimiento
                data["media_type"] = "book"

                # --- MEJORA: Preferencia de Alfabeto Latino ---
                def _is_latin(text: str) -> bool:
                    if not text: return True
                    # Comprueba si el texto contiene caracteres fuera del rango latino extendido
                    return all(ord(c) < 0x0370 for c in text)

                # Título
                api_title = api_result.get("title")
                if not _is_latin(api_title):
                    if _is_latin(titulo_limpio):
                        logger.info(f"[i] Título no latino. Manteniendo nombre limpio: '{titulo_limpio}'.")
                        data["title"] = titulo_limpio
                    elif original_title and _is_latin(original_title):
                        logger.info(f"[i] Título y archivo no latinos. Usando Fallback Inglés (IA): '{original_title}'.")
                        data["title"] = original_title
                    else:
                        data["title"] = api_title
                else:
                    data["title"] = api_title

                # Autor
                api_author = api_result.get("author_name_str")
                if not _is_latin(api_author):
                    # Intentamos buscar uno latino en la lista completa
                    found_latin = False
                    for alt_auth in api_result.get("author_name", []):
                        if _is_latin(alt_auth):
                            data["author"] = alt_auth
                            found_latin = True
                            logger.info(f"[i] Autor encontrado en API: '{alt_auth}'")
                            break
                    
                    if not found_latin and autor_ia:
                        # Si no hay ninguno en la API, usamos el de la IA (capitalizado)
                        data["author"] = autor_ia.title()
                        logger.info(f"[i] Usando nombre de autor normalizado por IA: '{data['author']}'")
                else:
                    data["author"] = api_author

                # --- Fase de Enriquecimiento profundo (Sinopsis, Personajes, Lugares, Sagas) ---
                work_key = api_result.get("key")
                details = self.openlibrary.get_book_details(work_key) if work_key else {}

                # Combinamos temas, personajes y lugares
                subjects = api_result.get("subject", [])
                people = details.get("people", [])
                places = details.get("places", [])
                
                # Intentamos detectar la Saga/Serie (Heurística sobre temas)
                collection = ""

                for s in subjects:

                    s_low = s.lower()

                    if "series" in s_low or "saga" in s_low or "sequence" in s_low:
                        # Limpieza básica de etiquetas comunes de OpenLibrary
                        collection = s.replace("(Book Series)", "").replace("(book series)", "").strip()
                        break

                # Limitamos elementos para el campo de géneros/tags
                display_subjects = subjects[:10]
                display_people = people[:10]
                display_places = places[:10]
                
                all_tags = list(dict.fromkeys(display_subjects + display_people + display_places))
                genres_str = ", ".join(all_tags)

                # Normalización de Score (OpenLibrary es rango 0-5 -> pasamos a rango 0-10)
                raw_score = api_result.get("ratings_average", 0)
                norm_score = round(raw_score * 2, 1) if raw_score else 0

                # Resolución de fecha: Priorizar el año más antiguo entre API e IA (para libros clásicos)
                api_year = api_result.get("first_publish_year")
                llm_year = data.get("year")
                final_year = api_year
                
                if llm_year and api_year:
                    # Si la IA conoce un año más antiguo, es probable que la API devuelva una edición moderna
                    if llm_year < api_year:
                        final_year = llm_year
                        logger.info(f"    [i] Corrigiendo año de edición ({api_year}) por año original ({llm_year})")
                elif llm_year and not api_year:
                    final_year = llm_year

                # Extracción de páginas (Fallback entre mediana y lista de ediciones)
                pages = api_result.get("number_of_pages_median")
                
                if not pages:
                    # Si no hay mediana, buscamos en la lista de páginas (puede ser int o list en la API)
                    raw_pages = api_result.get("number_of_pages")
                    if isinstance(raw_pages, list) and raw_pages:
                        pages = raw_pages[0] # Tomamos la primera edición como referencia
                    elif isinstance(raw_pages, (int, float)):
                        pages = int(raw_pages)

                # --- IA de Respaldo (Si OpenLibrary no tiene sinopsis/personajes) ---
                
                overview = details.get("description") or api_result.get("overview", "")
                
                if not overview or len(overview) < 10:
                    logger.info("    [AI] OpenLibrary sin sinopsis. Invocando IA de refuerzo...")
                    ai_enrich = analyze_media_content(data["title"], data["author"], media_type="book")
                    
                    if ai_enrich:
                        overview = ai_enrich.get("overview", overview)
                        if not display_people: 
                            display_people = ai_enrich.get("cast", [])
                            if isinstance(display_people, str): display_people = [display_people]
                        if not collection: collection = ai_enrich.get("collection", "")
                        if not display_places: display_places = ai_enrich.get("keywords", [])
                        
                        # Re-generamos géneros si la IA nos dio nuevos datos
                        all_tags = list(dict.fromkeys(display_subjects + display_people + display_places))
                        genres_str = ", ".join(all_tags)

                data["api_data"] = {
                    "source": "OpenLibrary",
                    "official_title": data["title"],
                    "author": data["author"],
                    "date": final_year,
                    "score": norm_score,
                    "overview": overview,
                    "genres": genres_str,
                    "pages": pages,
                    "cast": ", ".join(display_people[:10]) if isinstance(display_people, list) else str(display_people),
                    "keywords": ", ".join(display_places[:10]) if isinstance(display_places, list) else str(display_places),
                    "collection": collection
                }


    # Función que realiza la búsqueda en MusicBrainz y aplica scoring.
    def _query_musicbrainz(self, data: dict, titulo_limpio: str, artist: Optional[str] = None):

        logger.info("[AUDIO] Buscando en MusicBrainz como Audio...")

        api_result = self.musicbrainz.search_audio(titulo_limpio, artist)

        if not api_result:

            titulo_alternativo = self._get_plan_b_title(titulo_limpio)

            if titulo_alternativo:
                logger.info(f"[RETRY] Plan B: Reintentando búsqueda sin 'AKA' -> '{titulo_alternativo}'")
                api_result = self.musicbrainz.search_audio(titulo_alternativo)
        
        if api_result:

            # Función auxiliar para normalizar texto y facilitar la comparación.
            def normalizar_comparacion(s):

                # Normaliza el texto eliminando acentos y caracteres especiales
                sn = "".join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c)).lower()
                return re.sub(r'[^a-z0-9]', '', sn)

            api_title = api_result.get("title", "")
            api_artist = api_result.get("artist", "")
            full_api_name = f"{api_artist} {api_title}"
            
            search_name_clean = normalizar_comparacion(titulo_limpio)
            full_api_clean = normalizar_comparacion(full_api_name)
            api_title_clean = normalizar_comparacion(api_title)

            similitud_completa = SequenceMatcher(None, search_name_clean, full_api_clean).ratio()
            contiene_titulo = api_title_clean in search_name_clean and len(api_title_clean) > 2

            # Si la similitud es menor al 65% y no contiene el título, se descarta.
            if similitud_completa < 0.65 and not contiene_titulo:
                logger.warning(f"[WARN] Audio descartado por baja similitud ({int(similitud_completa*100)}%): '{api_artist} - {api_title}' vs '{titulo_limpio}'")
            
            # Si la similitud es alta o contiene el título, se guarda.
            else:
                # --- MEJORA: Promoción de tipo oficial y Normalización Latina ---
                def _is_latin(text: str) -> bool:
                    if not text: return True
                    return all(ord(c) < 0x0370 for c in text)

                # Título
                api_title = api_result.get("title")
                original_audio_title = data.get("original_title")

                if not _is_latin(api_title):
                    if _is_latin(titulo_limpio):
                        data["title"] = titulo_limpio
                    elif original_audio_title and _is_latin(original_audio_title):
                        logger.info(f"[i] Audio no latino. Usando Fallback Inglés (IA): '{original_audio_title}'.")
                        data["title"] = original_audio_title
                    else:
                        data["title"] = api_title
                else:
                    data["title"] = api_title

                # Artista/Autor
                api_artist = api_result.get("artist")
                if not _is_latin(api_artist) and artist:
                    data["author"] = artist.title()
                    logger.info(f"[i] Artista en alfabeto no latino. Usando versión IA: '{data['author']}'")
                else:
                    data["author"] = api_artist

                data["media_type"] = "audio"

                data["api_data"] = {
                    "source": "MusicBrainz",
                    "official_title": data["title"],
                    "author": data["author"],
                    "date": api_result.get("date"),
                    "score": api_result.get("score", 0),  # MusicBrainz suele dar un score de match 0-100 o similar, lo mantenemos como está o ajustamos
                    "genres": api_result.get("genres", "")
                }
                
                # Si el score de MusicBrainz es de relevancia (rango 0-100), lo normalizamos a rango 0-10
                if data["api_data"]["score"] > 10:
                    data["api_data"]["score"] = round(data["api_data"]["score"] / 10, 1)


    # Función que realiza el triaje de seguridad del archivo.
    def _scan_software(self, data: dict, filename: str, technical_target: str):

        internal_name = data.get("internal_representative")
        target_info = f"-> [{internal_name}]" if internal_name else ""

        # Extensiones de Office que contienen macros.
        office_macros = {
            ".xlsm", ".xlsb", ".docm", ".pptm", ".dotm", ".ppsm", ".potm", ".xltm", ".xlam",
            ".doc", ".xls", ".ppt", ".one", ".iqy", ".slk", ".pdf"
        }

        extension = data.get("extension", "").lower()

        # Si la extensión es de Office, se marca como sospechoso.
        if extension in office_macros:
             logger.warning(f"[SEC] {filename} contiene Macros de Office!! Lo trataré como ejecutable para triaje preventivo...")

        # Iniciamos el triaje de seguridad.
        logger.info(f"[SW] Software/Archivo comprimido detectado {target_info}. Iniciando triaje de seguridad con VirusTotal...")

        # Si se proporciona un target técnico (Hash/Path)
        if technical_target:

            # Realizamos el escaneo.
            vt_result = self.virustotal.scan_software(technical_target)

            # Si el archivo se encuentra en VirusTotal, se guarda.
            if vt_result:

                stats = vt_result["stats"]
                results = vt_result["results"]
                file_hash = vt_result["hash"]
                
                malicious = stats.get("malicious", 0)
                suspicious = stats.get("suspicious", 0)

                # Lista de los motores de antivirus más top.
                TOP_ANTIVIRUS = [
                    "Microsoft", "Kaspersky", "ESET-NOD32", "BitDefender", 
                    "Symantec", "Sophos", "TrendMicro", "FireEye", "CrowdStrike"
                ]
                
                top_threats = []
                
                # Buscamos si algún motor top detectó el archivo como malicioso.
                for engine in TOP_ANTIVIRUS:
                    res = results.get(engine)
                    # En caso afirmativo, se añade a la lista de amenazas.
                    if res and res.get("category") == "malicious":
                        top_threats.append(engine)

                # Asignamos el veredicto según la cantidad de detecciones:

                # Si hay al menos 1 detección por parte de Motor Antivirus Top, se marca como malicioso.
                if top_threats:
                    veredicto = f"\033[91mMALICIOUS !!! (Detected by: {', '.join(top_threats)})\033[0m"
                
                # Si no hay detecciones por parte de motores Top, se revisa el resto de motores.
                elif malicious == 0 and suspicious == 0:
                    veredicto = "\033[92mSAFE\033[0m"
                
                # Si hay entre 1 y 5 detecciones, se marca como sospechoso.
                elif 1 <= malicious <= 5:
                    veredicto = "\033[93mSUSPICIOUS\033[0m"

                # Si hay más de 5 detecciones, se marca como malicioso.
                elif malicious > 5:
                    veredicto = "\033[91mMALICIOUS\033[0m"
                
                # Si no se detecta como malicioso ni sospechoso, se marca como seguro.
                else:
                    veredicto = "\033[92mSAFE\033[0m"
                
                # URL del archivo en VirusTotal.
                vt_url = f"https://www.virustotal.com/gui/file/{file_hash}" if stats.get("suspicious") != -1 else None

                data["api_data"] = {
                    "source": "VirusTotal",
                    "official_title": filename,
                    "veredicto": veredicto,
                    "malicious_count": malicious,
                    "suspicious_count": suspicious,
                    "top_hits": top_threats,
                    "url": vt_url
                }
                
                # Si el archivo no se encuentra en VirusTotal, se marca como desconocido.
                if stats.get("suspicious") == -1:
                    data["api_data"]["veredicto"] = "\033[93mUNKNOWN (Not found in VT)\033[0m"

        else:
            logger.warning("[WARN] No se proporcionó Filepath para hacer el triaje SHA-256 del software.")


    # Función que muestra los metadatos encontrada en formato de tarjeta.
    def _log_metadata_card(self, data: dict):

        if data.get("api_data"):

            ad = data["api_data"]

            logger.info(f"[DONE] Metadatos Encontrados/Analizados en {ad['source']}!")

            logger.info(f"    - Título: {ad.get('official_title')}")

            if ad.get("date"):
               logger.info(f"    - Fecha/Año: {ad['date']}")

            if ad.get("author"):
                logger.info(f"    - Autor/Artista: {ad['author']}")

            if ad.get("score"):
                logger.info(f"    - Relevancia/Nota: {ad['score']}/10")

            if ad.get("pages") and data.get("media_type") in ["book", "documents"]:
                logger.info(f"    - Páginas: {ad['pages']}")
            
            # Información técnica complementaria (FFmpeg)
            tech = data.get("technical")
            
            # Duración en minutos
            if tech and tech.get("duration_sec"):
                mins = tech["duration_sec"] // 60
                logger.info(f"    - Duración: {mins} min")
            
            # Veredicto de seguridad
            if ad.get("veredicto"):
                logger.info(f"    - Seguridad: {ad['veredicto']}")

                if ad.get("url"):
                    logger.info(f"    - Informe VT: {ad['url']}")

            # Metadatos Enriquecidos (Extra)
            if ad.get("overview"):
                logger.info(f"    - Sinopsis: {ad['overview'][:120]}...")
            if ad.get("cast"):
                label = "Personajes" if data.get("media_type") == "book" else "Reparto"
                logger.info(f"    - {label}: {ad['cast']}")
            if ad.get("collection"):
                logger.info(f"    - Colección: {ad['collection']}")
            if ad.get("keywords"):
                label = "Lugares/Tags" if data.get("media_type") == "book" else "Keywords"
                logger.info(f"    - {label}: {ad['keywords']}")
        else:
            logger.info("[WARN] No se obtuvieron metadatos oficiales de las APIs.")


    # Método privado para obtener el título alternativo
    def _find_representative_file(self, directory: Path) -> Optional[Path]:

        """
        Busca recursivamente el archivo más pesado que sea multimedia dentro de un directorio.
        Excluye archivos con extensiones ignoradas (temporales de eMule/Torrent).
        """

        try:
            # Obtenemos todas las extensiones que consideramos "multimedia"
            media_extensions = EXTENSION_MAPPING["video"].union(EXTENSION_MAPPING["audio"])
            
            # Buscamos todos los archivos de forma recursiva
            all_files = [f for f in directory.rglob('*') if f.is_file()]
            
            # Filtramos los que sean temporales/ignorados
            valid_files = []
            for f in all_files:
                compound_ext = "".join(f.suffixes).lower()
                if compound_ext in IGNORED_EXTENSIONS or f.suffix.lower() in IGNORED_EXTENSIONS:
                    continue
                valid_files.append(f)
            
            if not valid_files:
                return None

            # 1. Intentamos buscar entre los multimedia
            media_files = [f for f in valid_files if f.suffix.lower() in media_extensions]
            
            if media_files:
                return max(media_files, key=lambda f: f.stat().st_size)
            
            # 2. Si no hay multimedia válidos, retornamos el más grande de los válidos (fallback)
            return max(valid_files, key=lambda f: f.stat().st_size)

        except Exception as e:
            logger.warning(f"[WARN] Error al buscar archivo representante en {directory.name}: {e}")
            return None
            
    
    # Función que extrae la primera parte del título antes de un 'aka' o limpia ruido residual.
    def _get_plan_b_title(self, title: str) -> Optional[str]:
        """
        Genera una versión simplificada del título para reintentar la búsqueda en la API.
        Limpia 'aka', guiones sueltos y palabras técnicas que suelen sobrevivir al primer filtro.
        """
        original_title = title
        
        # 1. Gestión de 'AKA'
        if re.search(r'\s+aka\s+', title, re.IGNORECASE): 
            title = re.split(r'\s+aka\s+', title, maxsplit=1, flags=re.IGNORECASE)[0]

        # 2. Limpieza de ruido técnico común que ensucia la búsqueda
        # (Palabras que a veces el LLM o Regex dejan por error)
        noise = [r'-', r'v-?a', r'remaster(ed)?', r'no-?ads?', r'unrated', r'uncut']
        for pattern in noise:
            title = re.sub(r'(?i)\b' + pattern + r'\b', ' ', title)

        # Limpiar espacios dobles y guiones/espacios al final
        title = re.sub(r'\s+', ' ', title).strip().strip('-').strip()

        return title if title.lower() != original_title.lower() else None
