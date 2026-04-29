import logging
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

from smartmule.parsers.regex_parser import parse_filename, EXTENSION_MAPPING
from smartmule.parsers.llm_parser import parse_with_llm
from smartmule.api.tmdb_client import TMDBClient
from smartmule.api.openlibrary_client import OpenLibraryClient
from smartmule.api.musicbrainz_client import MusicBrainzClient
from smartmule.api.virustotal_client import VirusTotalClient
from smartmule.config import TMDB_BEARER_TOKEN, TMDB_BASE_URL, IGNORED_EXTENSIONS

logger = logging.getLogger("SmartMule.engine")

class MetadataEngine:

    """
    Orquestador principal del pipeline de enriquecimiento de archivos. Sigue una estructura de cascada:
    1. Regex (rápido) -> Si OK, se salta la IA.
    2. IA (lento, costoso) -> Si Regex falló o había baja confianza.
    3. APIs (TMDB/OpenLibrary) -> Siempre se ejecuta, con el nombre limpio de cualquiera de los anteriores parsers.
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
        filename, display_name, technical_target = self._resolve_target(filename, filepath)
        logger.info(f"🔍  Identificando archivo [{filename}]...")

        # --- CACHÉ DE BÚSQUEDAS (API Optimization) ---
        if self.db and ed2k_hash:
            cached_data = self.db.get_metadata_cache(ed2k_hash)
            if cached_data:
                logger.info(f"⚡ ¡Caché Hit! Metadatos recuperados instantáneamente para {ed2k_hash[:8]}...")
                return cached_data

        # ================= CAPA 1 y 2: Regex Simple y Análisis IA =================
        data = self._apply_regex_and_ai(filename)

        titulo_limpio = data.get("title", "")
        media_type = data.get("media_type", "unknown")
        logger.info(f"✨  Nombre limpio: '{titulo_limpio}' ({media_type})")

        # ================= CAPA 2.5: Antimalware Semántico (Contenedores) =================
        if self._inspect_compressed(data, filename, technical_target):
            return data

        # ================= CAPA 3: APIs Oficiales y Triaje VT =================
        self._enrich_with_apis(data, filename, technical_target)
        self._log_metadata_card(data)

        # Guardamos en caché
        if self.db and ed2k_hash:
            self.db.set_metadata_cache(ed2k_hash, data)

        return data

    def _resolve_target(self, filename: str, filepath: str) -> tuple[str, str, str]:
        item_path = Path(filepath) if filepath else Path(filename)
        display_name = filename
        technical_target = filepath or filename

        if item_path.is_dir():
            logger.info(f"📂  Procesando directorio: {display_name}")
            representative = self._find_representative_file(item_path)
            
            if representative:
                technical_target = str(representative)
                logger.info(f"🔍  Archivo representante encontrado: {representative.name}")
                if len(representative.stem) < 5 or representative.stem.lower() in ["movie", "video", "cd1", "cd2"]:
                    logger.info("ℹ️  Usando nombre de carpeta para identificar (nombre de archivo genérico)")
                else:
                    filename = representative.name
            else:
                technical_target = filepath
                logger.warning(f"⚠️  No se encontró un archivo multimedia claro en la carpeta {display_name}")

        return filename, display_name, technical_target

    def _apply_regex_and_ai(self, filename: str) -> dict:
        data = parse_filename(filename)
        
        if data.get("confidence") == "low":
            context_data = {
                "languages": data.get("languages"),
                "subtitles": data.get("subtitles")
            }
            ai_data = parse_with_llm(filename, context=context_data)
            
            if ai_data.get("confidence") != "failed":
                ai_data["extension"] = data.get("extension")
                ai_data["resolution"] = data.get("resolution", "")
                ai_data["languages"] = data.get("languages", "")
                ai_data["subtitles"] = data.get("subtitles", "")
                
                if not ai_data.get("media_type") or ai_data.get("media_type") == "unknown":
                    ai_data["media_type"] = data.get("media_type")
                    
                data = ai_data
            else:
                logger.warning("❌  Análisis por IA falló. Volviendo al resultado regular de Capa 1.")
        return data

    def _inspect_compressed(self, data: dict, filename: str, technical_target: str) -> bool:
        media_type = data.get("media_type")
        if media_type == "compressed" and technical_target:
            from smartmule.parsers.archive_inspector import inspect_archive
                
            logger.info("🗜️  Archivo comprimido detectado. Iniciando análisis...")
            inspection = inspect_archive(technical_target, expected_type=media_type)
            
            if inspection["status"] in ["MALICIOUS", "SUSPICIOUS"]:
                logger.warning("🛑  Triaje de seguridad abortado por Inconsistencia Semántica o Cifrado.")
                veredicto = "[91mMALICIOUS !!![0m" if inspection["status"] == "MALICIOUS" else "[93mSUSPICIOUS ![0m"
                data["api_data"] = {
                    "source": "Semantic Inspector",
                    "official_title": filename,
                    "veredicto": veredicto,
                    "malicious_count": 99 if inspection["status"] == "MALICIOUS" else 1, 
                    "suspicious_count": 0,
                    "url": "N/A (Semantic Malware)"
                }
                return True
                
            if inspection["status"] == "SAFE" and inspection.get("detected_media"):
                logger.info(f"🔄 Reclasificando media_type por contenido interno: 'compressed' -> '{inspection['detected_media']}'")
                data["media_type"] = inspection["detected_media"]
                if inspection.get("representative"):
                    data["internal_representative"] = Path(inspection["representative"]).name
        return False

    def _enrich_with_apis(self, data: dict, filename: str, technical_target: str):
        titulo_limpio = data.get("title", "")
        media_type = data.get("media_type", "unknown")
        year = data.get("year")

        if media_type in ["video", "tv series", "movie"]: 
            self._query_tmdb(data, titulo_limpio, year)
        elif media_type == "book":
            self._query_openlibrary(data, titulo_limpio)
        elif media_type == "audio":
            self._query_musicbrainz(data, titulo_limpio)
        elif media_type == "subtitles":
            logger.info("📝  Subtítulos detectados.")
        elif media_type in ["software", "compressed"]:
            self._scan_software(data, filename, technical_target)
        else:
            logger.info("❓  Tipo de medio desconocido, omitiendo búsqueda en APIs.")

    def _query_tmdb(self, data: dict, titulo_limpio: str, year: str):
        if data.get("season"):
            logger.info("📺 Buscando en TMDB como Serie...")
            results = self.tmdb.search_tv(titulo_limpio, year) 
        else:
            logger.info("🎬 Buscando en TMDB como Película...")
            results = self.tmdb.search_movie(titulo_limpio, year)

        if not results:
            titulo_alternativo = self._get_plan_b_title(titulo_limpio)
            if titulo_alternativo:
                logger.info(f"🔄 Plan B: Reintentando búsqueda sin 'AKA' -> '{titulo_alternativo}'")
                if data.get("season"):
                    results = self.tmdb.search_tv(titulo_alternativo, year)
                else:
                    results = self.tmdb.search_movie(titulo_alternativo, year)

        if results:
            best_match = results[0]
            best_score = -1 
            for res in results:
                score = 0
                res_title = res.get("title") or res.get("name")
                res_date = res.get("release_date") or res.get("first_air_date") or ""
                
                if res_title.lower() == titulo_limpio.lower():
                    score += 50
                if year and str(year) in res_date:
                    score += 30
                
                if score > best_score:
                    best_score = score
                    best_match = res 

            api_result = best_match
            poster = f"https://image.tmdb.org/t/p/w500{api_result.get('poster_path')}" if api_result.get("poster_path") else None
            
            data["api_data"] = {
                "source": "TMDB",
                "official_title": api_result.get("name") or api_result.get("title"),
                "date": api_result.get("first_air_date") or api_result.get("release_date"),
                "score": api_result.get("vote_average"),
                "poster_url": poster,
                "overview": api_result.get("overview")
            }

    def _query_openlibrary(self, data: dict, titulo_limpio: str):
        logger.info("📚 Buscando en OpenLibrary como Libro...")
        api_result = self.openlibrary.search_book(titulo_limpio)

        if not api_result:
            titulo_alternativo = self._get_plan_b_title(titulo_limpio)
            if titulo_alternativo:
                logger.info(f"🔄 Plan B: Reintentando búsqueda sin 'AKA' -> '{titulo_alternativo}'")
                api_result = self.openlibrary.search_book(titulo_alternativo)

        if api_result:
            similitud = SequenceMatcher(None, titulo_limpio.lower(), api_result.get("title", "").lower()).ratio()
            if similitud < 0.7:
                logger.warning(f"⚠️  Libro descartado por baja similitud ({int(similitud*100)}%): '{api_result.get('title')}' vs '{titulo_limpio}'")
            else:
                data["api_data"] = {
                    "source": "OpenLibrary",
                    "official_title": api_result.get("title"),
                    "author": api_result.get("author_name_str"),
                    "date": api_result.get("first_publish_year"),
                    "cover_id": api_result.get("cover_i"),
                    "score": api_result.get("ratings_average")
                }

    def _query_musicbrainz(self, data: dict, titulo_limpio: str):
        logger.info("🎵  Buscando en MusicBrainz como Audio...")
        api_result = self.musicbrainz.search_audio(titulo_limpio)

        if not api_result:
            titulo_alternativo = self._get_plan_b_title(titulo_limpio)
            if titulo_alternativo:
                logger.info(f"🔄  Plan B: Reintentando búsqueda sin 'AKA' -> '{titulo_alternativo}'")
                api_result = self.musicbrainz.search_audio(titulo_alternativo)
        
        if api_result:
            def normalizar_comparacion(s):
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

            if similitud_completa < 0.65 and not contiene_titulo:
                logger.warning(f"⚠️  Audio descartado por baja similitud ({int(similitud_completa*100)}%): '{api_artist} - {api_title}' vs '{titulo_limpio}'")
            else:
                data["api_data"] = {
                    "source": "MusicBrainz",
                    "official_title": api_result.get("title"),
                    "author": api_result.get("artist"),
                    "date": api_result.get("date"),
                    "score": api_result.get("score") 
                }

    def _scan_software(self, data: dict, filename: str, technical_target: str):
        internal_name = data.get("internal_representative")
        target_info = f"-> [{internal_name}]" if internal_name else ""

        office_macros = {
            ".xlsm", ".xlsb", ".docm", ".pptm", ".dotm", ".ppsm", ".potm", ".xltm", ".xlam",
            ".doc", ".xls", ".ppt", ".one", ".iqy", ".slk", ".pdf"
        }

        extension = data.get("extension", "").lower()
        if extension in office_macros:
             logger.warning(f"🛡️  [Seguridad] {filename} contiene Macros de Office!! Lo trataré como ejecutable para triaje preventivo...")

        logger.info(f"💾  Software/Archivo comprimido detectado {target_info}. Iniciando triaje de seguridad con VirusTotal...")

        if technical_target:
            vt_result = self.virustotal.scan_software(technical_target)

            if vt_result:
                stats = vt_result["stats"]
                results = vt_result["results"]
                file_hash = vt_result["hash"]
                
                malicious = stats.get("malicious", 0)
                suspicious = stats.get("suspicious", 0)

                TOP_ANTIVIRUS = [
                    "Microsoft", "Kaspersky", "ESET-NOD32", "BitDefender", 
                    "Symantec", "Sophos", "TrendMicro", "FireEye", "CrowdStrike"
                ]
                
                top_threats = []
                for engine in TOP_ANTIVIRUS:
                    res = results.get(engine)
                    if res and res.get("category") == "malicious":
                        top_threats.append(engine)

                if top_threats:
                    veredicto = f"\033[91mMALICIOUS !!! (Detected by: {', '.join(top_threats)})\033[0m"
                elif malicious == 0 and suspicious == 0:
                    veredicto = "\033[92mSAFE\033[0m"
                elif 1 <= malicious <= 5:
                    veredicto = "\033[93mSUSPICIOUS\033[0m"
                elif malicious > 5:
                    veredicto = "\033[91mMALICIOUS\033[0m"
                else:
                    veredicto = "\033[93mSUSPICIOUS\033[0m"
                
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
                
                if stats.get("suspicious") == -1:
                    data["api_data"]["veredicto"] = "\033[93mUNKNOWN (Not found in VT)\033[0m"
        else:
            logger.warning("⚠️  No se proporcionó Filepath para hacer el triaje SHA-256 del software.")

    def _log_metadata_card(self, data: dict):
        if data.get("api_data"):
            ad = data["api_data"]
            logger.info(f"✅ ¡Metadatos Encontrados/Analizados en {ad['source']}!")
            logger.info(f"    - Título: {ad.get('official_title')}")
            if ad.get("date"):
               logger.info(f"    - Fecha/Año: {ad['date']}")
            if ad.get("author"):
                logger.info(f"    - Autor/Artista: {ad['author']}")
            if ad.get("score"):
                logger.info(f"    - Relevancia/Nota: {ad['score']}")
            
            if ad.get("veredicto"):
                logger.info(f"    - Seguridad: {ad['veredicto']}")
                if ad.get("url"):
                    logger.info(f"    - Informe VT: {ad['url']}")
        else:
            logger.info("⚠️  No se obtuvieron metadatos oficiales de las APIs.")


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
            logger.warning(f"⚠️  Error al buscar archivo representante en {directory.name}: {e}")
            return None
            
    def _get_plan_b_title(self, title: str) -> Optional[str]:

        """
        Extrae la primera parte del título antes de un 'aka' (con cualquier variante de mayúsculas).
        """

        if re.search(r'\s+aka\s+', title, re.IGNORECASE): # Si el título contiene 'aka' (con cualquier variante de mayúsculas)
            parts = re.split(r'\s+aka\s+', title, maxsplit=1, flags=re.IGNORECASE) # Dividimos por el primer 'aka' que encontremos
            return parts[0].strip() # Devolvemos la primera parte del título
        return None # Si no se encuentra 'aka', devolvemos None
