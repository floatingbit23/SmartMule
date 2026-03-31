import logging

from smartmule.parsers.regex_parser import parse_filename
from smartmule.parsers.llm_parser import parse_with_llm
from smartmule.api.tmdb_client import TMDBClient
from smartmule.api.openlibrary_client import OpenLibraryClient
from smartmule.api.musicbrainz_client import MusicBrainzClient
from smartmule.api.virustotal_client import VirusTotalClient

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
            inspection = inspect_archive(filepath)
            
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
            
            # TMDB diferencia Películas de Series
            if data.get("season"):
                logger.info("📺 [Engine] Buscando en TMDB como Serie...")
                api_result = self.tmdb.search_tv(titulo_limpio, year) 

            else:
                logger.info("🎬 [Engine] Buscando en TMDB como Película...")
                api_result = self.tmdb.search_movie(titulo_limpio, year)
                
            if api_result: # Si se encontró resultado

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

            # Si se encontró resultado
            if api_result:
                # Guardamos los datos en el diccionario
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
            
            if api_result:
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
