import logging
from typing import Any, Optional

from smartmule.parsers.regex_parser import parse_filename
from smartmule.parsers.llm_parser import parse_with_llm
from smartmule.api.tmdb_client import TMDBClient
from smartmule.api.openlibrary_client import OpenLibraryClient
from smartmule.api.musicbrainz_client import MusicBrainzClient
from smartmule.api.virustotal_client import VirusTotalClient
import re # regex

logger = logging.getLogger("SmartMule.engine")

class MetadataEngine:

    """
    Orquestador principal del pipeline de enriquecimiento de archivos. Sigue una estructura de cascada:
    1. Regex (rápido) -> Si OK, se salta la IA.
    2. IA (lento, costoso) -> Si Regex falló o había baja confianza.
    3. APIs (TMDB/OpenLibrary) -> Siempre se ejecuta, con el nombre limpio de cualquiera de los anteriores parsers.
    """
    
    # Constructor de la clase MetadataEngine
    def __init__(self):

        self.tmdb = TMDBClient() # Instancio la clase TMDBClient
        self.openlibrary = OpenLibraryClient() # Instancio la clase OpenLibraryClient
        self.musicbrainz = MusicBrainzClient() # Instancio la clase MusicBrainzClient
        self.virustotal = VirusTotalClient() # Instancio la clase VirusTotalClient


    # Método para identificar el archivo
    def identify_file(self, filename: str, filepath: str = None) -> dict:

        logger.info(f"🔍  Identificando archivo [{filename}]...")
        

        # ================= CAPA 1: Regex Simple =================


        data = parse_filename(filename)
        

        # ================= CAPA 2: IA =================


        if data.get("confidence") == "low": # Si la confianza en el resultado de Regex es baja, escalamos a IA

            logger.info("⚠️  Nombre de archivo confuso. Consultando a la IA (Capa 2)...")

            ai_data = parse_with_llm(filename) # Llamamos a la IA
            
            # Si la IA tuvo éxito, combinamos
            if ai_data.get("confidence") != "failed":

                # Respetamos la extensión original que sacó la Capa 1
                ai_data["extension"] = data.get("extension")
                
                # Respetamos el media_type original (obtenido por Regex) si la IA lo borró o no sabía ("unknown")
                if not ai_data.get("media_type") or ai_data.get("media_type") == "unknown":
                    ai_data["media_type"] = data.get("media_type") 
                    
                data = ai_data # Combinamos los datos de la IA con los de Regex

            else:
                logger.warning("❌  Análisis por IA falló. Volviendo al resultado regular de Capa 1.")
                
        # Extracción de datos clave para la siguiente fase
        titulo_limpio = data.get("title", "")
        media_type = data.get("media_type", "unknown")
        year = data.get("year")
        
        logger.info(f"✨  Nombre limpio: '{titulo_limpio}' ({media_type})")


        # ================= CAPA 2.5: Antimalware Semántico (Contenedores) =================
        

        if media_type == "compressed" and filepath: # Si el archivo es un comprimido y tenemos la ruta

            from smartmule.parsers.archive_inspector import inspect_archive
                
            logger.info(f"🗜️  Archivo comprimido detectado. Iniciando análisis...")
            inspection = inspect_archive(filepath, expected_type=media_type)
            
            # Si el interior revela un FAKE/MALICIOUS o está encriptado (protegido con contraseña), anulamos todo el proceso.
            if inspection["status"] in ["MALICIOUS", "SUSPICIOUS"]:
                logger.warning(f"🛑  Triaje de seguridad abortado por Inconsistencia Semántica o Cifrado.")
                
                # Simulamos la respuesta final para que conste en BBDD y en el Organizer
                veredicto = "\033[91mMALICIOUS !!!\033[0m" if inspection["status"] == "MALICIOUS" else "\033[93mSUSPICIOUS !\033[0m"
                
                data["api_data"] = {
                    "source": "Semantic Inspector",
                    "official_title": filename,
                    "veredicto": veredicto,
                    "malicious_count": 99 if inspection["status"] == "MALICIOUS" else 1, 
                    "suspicious_count": 0,
                    "url": "N/A (Semantic Malware)" # No hay URL porque se trata de un archivo comprimido
                }

                # Mantenemos status sin procesar APIs oficiales
                return data
                
            # Si el archivo comprimido es SAFE, y contiene un archivo multimedia claro, reclasificamos para que TMDB/OpenLibrary hagan su trabajo
            # Por ejemplo, si el archivo es "Mi_Pelicula.rar" y dentro tiene "Mi_Pelicula.mp4", lo reclasificamos como "video"

            if inspection["status"] == "SAFE" and inspection.get("detected_media"):

                logger.info(f"🔄 [Engine] Reclasificando media_type por contenido interno: 'compressed' -> '{inspection['detected_media']}'")
                
                media_type = inspection["detected_media"] # Obtenemos el Media Type
                data["media_type"] = media_type # Actualizamos el Media Type
 

        # ================= CAPA 3: APIs Oficiales =================

        api_result = None
        data["api_data"] = None

        if media_type in ["video", "tv series", "movie"]: 
            
            # --- DESEMPATE TÉCNICO (En caso de homónimos) ---

            # Obtenemos duración real del archivo para desempate si hay homónimos
            from smartmule.parsers.media_inspector import inspect_media_file

            tech_info = inspect_media_file(filepath) # Información técnica del archivo
            actual_duration_min = tech_info.get("duration_sec", 0) // 60 # Duración en minutos

            # TMDB diferencia Películas de Series
            if data.get("season"):
                logger.info("📺 [Engine] Buscando en TMDB como Serie...")
                results = self.tmdb.search_tv(titulo_limpio, year) 
            else:
                logger.info("🎬 [Engine] Buscando en TMDB como Película...")
                results = self.tmdb.search_movie(titulo_limpio, year)

            # === PLAN B: Reintento por duplicidad de títulos (AKA) ===

            if not results:

                # Obtenemos el título alternativo
                titulo_alternativo = self._get_plan_b_title(titulo_limpio)

                if titulo_alternativo:
                    logger.info(f"🔄 [Engine] Plan B: Reintentando búsqueda sin 'AKA' -> '{titulo_alternativo}'")
                    
                    if data.get("season"): # Si es una serie
                        results = self.tmdb.search_tv(titulo_alternativo, year)
                    else: # Si es una película
                        results = self.tmdb.search_movie(titulo_alternativo, year)


            if results: # Si se encontraron resultados
                
                # Algoritmo de Scoring (Criterio de desempate)
                best_match = results[0] # Fallback al primero
                best_score = -1 

                for res in results: # Para cada resultado

                    # Inicializamos la puntuación (Score)
                    score = 0

                    # Obtenemos el título y la fecha de la API
                    res_title = res.get("title") or res.get("name")
                    res_date = res.get("release_date") or res.get("first_air_date") or ""
                    
                    # Criterio 1: PUNTUACIÓN POR TÍTULO (Exacto = 50 pts)
                    if res_title.lower() == titulo_limpio.lower():
                        score += 50
                    
                    # Criterio 2: PUNTUACIÓN POR AÑO (Si coincide año de estreno = 30 pts)
                    if year and str(year) in res_date:
                        score += 30

                    # Criterio 3: PUNTUACIÓN POR DURACIÓN

                    # TMDB no da el runtime en el /search directamente, pero si estuviera, sumaríamos 20 pts.
                    # Por ahora, si solo hay un resultado, es ese. Si hay varios, el año suele ser decisivo.
                    
                    # Actualizamos el mejor resultado si este tiene mayor puntuación
                    if score > best_score:
                        best_score = score
                        best_match = res 

                api_result = best_match # Asignamos el mejor resultado

                # Construimos la URL del póster
                poster = f"https://image.tmdb.org/t/p/w500{api_result.get('poster_path')}" if api_result.get("poster_path") else None
                
                # Guardamos los datos en el diccionario
                data["api_data"] = {
                    "source": "TMDB",
                    "official_title": api_result.get("name") or api_result.get("title"),
                    "date": api_result.get("first_air_date") or api_result.get("release_date"),
                    "score": api_result.get("vote_average"), # Puntuación en TMDB
                    "poster_url": poster,
                    "overview": api_result.get("overview")
                }
                
        elif media_type == "book":

            logger.info("📚 [Engine] Buscando en OpenLibrary como Libro...")
            api_result = self.openlibrary.search_book(titulo_limpio)

            # === PLAN B: Reintento por duplicidad de títulos (AKA) ===
            if not api_result:
                titulo_alternativo = self._get_plan_b_title(titulo_limpio)
                if titulo_alternativo:
                    logger.info(f"🔄 [Engine] Plan B: Reintentando búsqueda sin 'AKA' -> '{titulo_alternativo}'")
                    api_result = self.openlibrary.search_book(titulo_alternativo)

            # Si se encontró resultado
            if api_result:
                # --- VALIDACIÓN DE CONFIANZA (Filtro de Falsos Positivos) ---
                from difflib import SequenceMatcher
                similitud = SequenceMatcher(None, titulo_limpio.lower(), api_result.get("title", "").lower()).ratio()
                
                if similitud < 0.7:
                    logger.warning(f"⚠️ [Engine] Libro descartado por baja similitud ({int(similitud*100)}%): '{api_result.get('title')}' vs '{titulo_limpio}'")
                    api_result = None
                else:
                    data["api_data"] = {
                        "source": "OpenLibrary",
                        "official_title": api_result.get("title"),
                        "author": api_result.get("author_name_str"),
                        "date": api_result.get("first_publish_year"),
                        "cover_id": api_result.get("cover_i"), # ID de la portada
                        "score": api_result.get("ratings_average") # Puntuación media sobre 5
                    }
                
        elif media_type == "audio":

            logger.info("🎵 [Engine] Buscando en MusicBrainz como Audio...")
            api_result = self.musicbrainz.search_audio(titulo_limpio)

            # === PLAN B: Reintento por duplicidad de títulos (AKA) ===
            if not api_result:
                titulo_alternativo = self._get_plan_b_title(titulo_limpio)
                if titulo_alternativo:
                    logger.info(f"🔄 [Engine] Plan B: Reintentando búsqueda sin 'AKA' -> '{titulo_alternativo}'")
                    api_result = self.musicbrainz.search_audio(titulo_alternativo)
            
            if api_result:
                # --- VALIDACIÓN DE CONFIANZA (Filtro de Falsos Positivos) ---
                # Comprobamos que el título de la API se parezca al menos un 70% al original
                from difflib import SequenceMatcher
                similitud = SequenceMatcher(None, titulo_limpio.lower(), api_result.get("title", "").lower()).ratio()
                
                if similitud < 0.7:
                    logger.warning(f"⚠️ [Engine] Resultado de Audio descartado por baja similitud ({int(similitud*100)}%): '{api_result.get('title')}' no coincide con '{titulo_limpio}'")
                    api_result = None # Invalidamos el resultado
                else:
                    data["api_data"] = {
                        "source": "MusicBrainz",
                        "official_title": api_result.get("title"),
                        "author": api_result.get("artist"),
                        "date": api_result.get("date"),
                        "score": api_result.get("score") # Relevancia del resultado
                    }

        elif media_type == "subtitles":
            logger.info("📝 [Engine] Subtítulos detectados.")

        # Triaje de seguridad para software y archivos comprimidos
        elif media_type == "software" or media_type == "compressed":

            logger.info("💾 [Engine] Software/Archivo comprimido detectado. Iniciando triaje de seguridad con VirusTotal...")

            if filepath:

                # Hacemos el triaje SHA-256 del software
                vt_result = self.virustotal.scan_software(filepath)

                # Si se encontró resultado
                if vt_result:
                    stats = vt_result["stats"]
                    file_hash = vt_result["hash"]
                    
                    malicious = stats.get("malicious", 0)
                    suspicious = stats.get("suspicious", 0)

                    # Determinamos el veredicto
                    if malicious == 0 and suspicious == 0:
                        veredicto = "\033[92mSAFE\033[0m" # Verde (seguro)
                    elif 1 <= malicious <= 3:
                        veredicto = "\033[93mSUSPICIOUS !\033[0m" # Amarillo (sospechoso)
                    else:
                        veredicto = "\033[91mMALICIOUS !!!\033[0m" # Rojo (malicioso)
                    
                    vt_url = f"https://www.virustotal.com/gui/file/{file_hash}"

                    data["api_data"] = {
                        "source": "VirusTotal",
                        "official_title": filename,
                        "veredicto": veredicto, # SAFE, SUSPICIOUS o MALICIOUS
                        "malicious_count": malicious,
                        "suspicious_count": suspicious,
                        "url": vt_url
                    }
                    
                    if stats.get("suspicious") == -1: # Si el archivo no se encontró en VirusTotal
                        data["api_data"]["veredicto"] = "\033[93mUNKNOWN (Not found in VT)\033[0m"
           
            else:
                logger.warning("⚠️ [Engine] No se proporcionó Filepath para hacer el triaje SHA-256 del software.")

        # Si el tipo de medio es desconocido, omitimos la búsqueda en APIs
        else:
            logger.info("❓ [Engine] Tipo de medio desconocido, omitiendo búsqueda en APIs.")


        # Imprimir "Tarjeta de Metadatos" resumen en el log
        if data.get("api_data"):

            ad = data["api_data"]

            # Imprimimos la tarjeta de metadatos
            logger.info(f"✅ ¡Metadatos Encontrados/Analizados en {ad['source']}!")

            logger.info(f"    - Título: {ad.get('official_title')}")

            if ad.get("date"):
               logger.info(f"    - Fecha/Año: {ad['date']}")
            if ad.get("author"):
                logger.info(f"    - Autor/Artista: {ad['author']}")
            if ad.get("score"):
                logger.info(f"    - Relevancia/Nota: {ad['score']}")
            
            # Formato especial para VirusTotal
            if ad.get("veredicto"): # Si existe veredicto, es que es un software
                logger.info(f"    - Seguridad: {ad['veredicto']}")
                if ad.get("url"):
                    logger.info(f"    - Informe VT: {ad['url']}")

        else:
            logger.info("⚠️ [Engine] No se obtuvieron metadatos oficiales de las APIs.")

        # Devolvemos el diccionario final con toda la información recopilada
        return data


    # Método privado para obtener el título alternativo
    def _get_plan_b_title(self, title: str) -> Optional[str]:

        """
        Extrae la primera parte del título antes de un 'aka' (con cualquier variante de mayúsculas).
        """

        if re.search(r'\s+aka\s+', title, re.IGNORECASE): # Si el título contiene 'aka' (con cualquier variante de mayúsculas)
            parts = re.split(r'\s+aka\s+', title, maxsplit=1, flags=re.IGNORECASE) # Dividimos por el primer 'aka' que encontremos
            return parts[0].strip() # Devolvemos la primera parte del título
        return None # Si no se encuentra 'aka', devolvemos None
