import os # Módulo para operaciones del sistema operativo
import shutil # Módulo para operaciones con archivos y directorios
import logging
import re

from pathlib import Path
from smartmule.config import LIBRARY_PATH, ORGANIZER_MODE
from smartmule.notifications import send_notification

logger = logging.getLogger("SmartMule.organizer")

# Clase que se encarga de organizar los archivos en la biblioteca
class LibraryOrganizer:

    """
    Se encarga de clasitar, mover o eliminar el archivo baseando en los metadatos y triaje de seguridad de SmartMule.
    """

    # Constructor de la clase LibraryOrganizer
    def __init__(self):

        # Ruta base de la biblioteca
        self.library_dir = Path(LIBRARY_PATH)
        # Directorio de cuarentena
        self.quarantine_dir = self.library_dir / "00_Quarantine"
        # Directorio de revisión
        self.review_dir = self.library_dir / "01_Review"

        # Crear directorios críticos si no existen
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.review_dir.mkdir(parents=True, exist_ok=True)

    # Método para organizar los archivos
    def organize(self, file_path_str: str, metadata: dict) -> str:

        """
        Organiza el archivo. 
        Si MALICIOUS: os.remove().
        Si SUSPICIOUS: Mover a 01_Review.
        Si SAFE/Normal: Mover a Library/<media_type>/

        Retorna la ruta final del archivo como string.
        """
        
        # Ruta del archivo
        source_path = Path(file_path_str)
        
        # Si el archivo no existe, logueo error y retorno
        if not source_path.exists():
            logger.error(f"❌  Archivo origen no encontrado: {source_path.name}")
            return file_path_str

        # Obtengo los datos de la API
        api_data = metadata.get("api_data") or {}

        # Obtengo el veredicto de seguridad
        verdict = api_data.get("veredicto", "").upper()

        # Obtengo el Media Type
        media_type = metadata.get("media_type", "unknown")

        # Nombre del archivo
        filename = source_path.name 

        try:

            # 1. EVALUACIÓN DE PELIGRO EXTREMO (MALICIOUS)
            if "MALICIOUS" in verdict:

                logger.critical(f"💀 MALWARE CONFIRMADO!!! Borrando: {filename}")

                # Borro el ítem directamente. shutil.rmtree para carpetas, os.remove para archivos.
                if source_path.is_dir():
                    shutil.rmtree(source_path)
                else:
                    os.remove(source_path)
                
                send_notification("Malware Eliminado 💀", f"Se ha detectado malware encubierto en '{filename}' y ha sido borrado permanentemente por seguridad.", is_critical=True)

                logger.critical(f"🗑️ Ítem {filename} eliminado permanentemente del sistema por su seguridad.")
                
                return "<DELETED_MALICIOUS>"

            # 2. EVALUACIÓN DE RIESGO MEDIO (SUSPICIOUS)
            if "SUSPICIOUS" in verdict:

                logger.warning(f"⚠️  Archivo sospechoso movido a revisión: {filename}")

                dest_path = self.review_dir / filename 
                
                # Manejo de duplicados en Review
                counter = 1
                base_stem = source_path.stem
                if source_path.is_dir():
                    suffix = ""
                else:
                    suffix = source_path.suffix
                
                while dest_path.exists():
                    dest_path = self.review_dir / f"{base_stem}_{counter}{suffix}"
                    counter += 1

                self._transfer_item(source_path, dest_path) 
                send_notification("Archivo Sospechoso ⚠️", f"El archivo '{filename}' ha sido puesto en cuarentena para su revisión manual.", is_critical=True)

                return str(dest_path) 

            # 3. ARCHIVOS LIMPIOS Y NORMALES (SAFE o UNKNOWN sin riesgo)

            # Diccionario de mapeo de categorías
            category_mapping = {
                "movie": "Movies_and_Series",
                "tv series": "Movies_and_Series",
                "video": "Video_Clips",
                "book": "Books_and_Comics",
                "audio": "Audio_and_Music",
                "software": "Software",
                "compressed": "Archives",
                "image": "Images",
                "games": "Games",
                "documents": "Documents",
                "subtitles": "Movies_and_Series/Subtitles",
                "info": "Info_and_Verification",
                "unknown": "Others"
            }

            # Si es vídeo genérico pero tiene año, asumimos que es una película/serie para que no vaya a Video_Clips
            if media_type == "video" and metadata.get("year"):
                current_media_type = "movie"
            else:
                current_media_type = media_type

            folder_name = category_mapping.get(current_media_type, "Others") # Obtengo el nombre de la carpeta
            dest_dir = self.library_dir / folder_name # Ruta de la carpeta
            dest_dir.mkdir(parents=True, exist_ok=True) # Creo la carpeta si no existe

            # --- CAPA DE EMBELLECIMIENTO (Renombrado Inteligente) ---
            
            # 1. Obtenemos extensión y base
            suffix = source_path.suffix if source_path.is_file() else ""
            base_name = filename 

            api_data = metadata.get("api_data") 

            # 2. Intentamos obtener el título oficial de las APIs
            if api_data and api_data.get("official_title"):
                base_name = api_data["official_title"]
                
                # Si el título oficial ya trae la extensión, se la quitamos para no duplicar
                if suffix and base_name.lower().endswith(suffix.lower()):
                    base_name = base_name[:-len(suffix)]

            elif metadata.get("title"):
                base_name = metadata["title"]

            # 3. Añadimos el año si lo conocemos para un look profesional
            year = metadata.get("year")
            if year:
                pretty_name = f"{base_name} ({year})"
            else:
                pretty_name = base_name

            # 4. Saneamos el nombre (eliminamos carácteres prohibidos)
            clean_filename = re.sub(r'[\\/:*?"<>|]', '', pretty_name).strip()
            
            final_filename = f"{clean_filename}{suffix}"

            # Construimos la ruta final
            dest_path = dest_dir / final_filename

            # Si el ítem ya existe en destino, le añadimos un sufijo para no sobreescribir
            counter = 1

            while dest_path.exists():
                dest_path = dest_dir / f"{clean_filename}_{counter}{suffix}"
                counter += 1

            # Ejemplo: "The.Matrix.1999.mp4" -> "The.Matrix.1999_1.mp4"
            # Ejemplo Carpeta: "Peli_2024" -> "Peli_2024_1"

            # 5. Realizamos transferencia física según modo (Move, Copy, Hardlink)
            self._transfer_item(source_path, dest_path)
            
            # Selecciono el emoji correspondiente a la categoría para el log final
            if folder_name == "Movies_and_Series":
                emoji = "🍿"
            elif folder_name == "Books":
                emoji = "📚"
            elif folder_name == "Music":
                emoji = "🎵"
            elif folder_name == "Software":
                emoji = "💻"
            elif folder_name == "Archives":
                emoji = "📦"
            elif folder_name == "Images":
                emoji = "📸"
            elif folder_name == "Games":
                emoji = "🎮"
            elif folder_name == "Documents":
                emoji = "📄"
            else:
                emoji = "📁"
           
            logger.info(f"{emoji} Movido a Biblioteca ({folder_name}): {dest_path.name}")
            
            # Formatear un título amigable según la carpeta
            cat_name = folder_name.replace("_and_", " y ").replace("_", " ")
            send_notification("Descarga Organizada ✅", f"{emoji} {filename} se ha guardado en tu biblioteca de {cat_name}.")
            
            return str(dest_path)

        except Exception as e:
            logger.error(f"❌ Fallo organizando {filename}: {e}")
            return file_path_str
            
    # Función para transferir el archivo o directorio
    def _transfer_item(self, src: Path, dest: Path) -> None:

        """
        Transfiere el archivo o directorio basándose en ORGANIZER_MODE ("move", "copy", "hardlink").
        Si falla un hardlink por error de partición cruzada, realiza silenciosamente un fallback a "copy".
        """

        mode = ORGANIZER_MODE # Obtengo el modo de transferencia

        # Si el modo es "move", muevo el archivo o directorio
        if mode == "move":

            # Validamos si origen y destino están en el mismo disco físico (Zero-Copy Validation)
            if self._is_same_device(src, dest):

                """
                Si lo están, 'os.rename' es instantáneo y solo cambia el puntero en el sistema de archivos.
                Ejemplos de Zero-Copy:
                - Movimientos de punteros en la MTF del sistema de archivos NTFS en Windows
                - Movimientos en sistemas de archivos Apple File System (APFS) en macOS
                - Movimientos en sistemas de archivos Ext4 en Linux
                """

                # Realizo el movimiento
                os.rename(str(src), str(dest))
                logger.debug(f"⚡  Movimiento 'Zero-Copy' completado para {src.name}")

            else:
                # Si están en discos distintos, avisamos que la operación será más lenta (Copy + Delete)
                logger.warning(f"💾 Movimiento entre discos detectado: {src.name} se copiará al nuevo destino. Esto puede tardar unos minutos...")
                shutil.move(str(src), str(dest))
            
        # Si el modo es "copy", copio el archivo o directorio
        elif mode == "copy":
            
            if src.is_dir():
                shutil.copytree(src, dest) # el directorio se copia con todos sus archivos y subdirectorios
            else:
                shutil.copy2(src, dest) # el archivo se copia con todos sus metadatos
                
        # Si el modo es "hardlink", creo un hardlink del archivo o directorio
        elif mode == "hardlink":

            try:

                # Si la carpeta de origen es un directorio
                if src.is_dir():

                    # Para carpetas, recreo la estructura de carpetas y hardlinkeo cada fichero base
                    dest.mkdir(parents=True, exist_ok=True)

                    for root, dirs, files in os.walk(src):

                        root_path = Path(root)

                        # Replicamos subdirectorios
                        for d in dirs:
                            rel_path = (root_path / d).relative_to(src)
                            (dest / rel_path).mkdir(parents=True, exist_ok=True)
                            
                        # Hardlinks de los archivos
                        for f in files:
                            rel_path = (root_path / f).relative_to(src)
                            os.link(root_path / f, dest / rel_path)
                
                # Si la carpeta de origen es un archivo
                else:
                    os.link(src, dest) # crea un Hardlink del archivo
                
                logger.info(f"🔗  Hardlink creado: {src.name} -> {dest.name}")

            except (OSError, PermissionError) as e:

                # Fallback silencioso a copia si falla el hardlink (ej: intento entre particiones distintas C: y D:)
                logger.warning(f"⚠️  No se pudo crear hardlink ({e}). Reintentando mediante copia física...")
                self._transfer_item_as_copy(src, dest)

        else:
            # Fallback the fallback en caso de environment variable mal tipada
            shutil.move(str(src), str(dest))

    # Función auxiliar booleana para verificar si dos rutas pertenecen al mismo dispositivo físico/partición
    def _is_same_device(self, path1: Path, path2: Path) -> bool:
        """
        Verifica si dos rutas pertenecen al mismo dispositivo físico/partición.
        Útil para garantizar operaciones 'Zero-Copy' instantáneas.
        """
        try:

            # Comparamos el ID del dispositivo (st_dev).
            # Si coinciden, os.rename() es una operación de punteros instantánea.
            
            # Nota: path2 puede no existir aún, así que comprobamos su padre
            s1 = os.stat(path1).st_dev
            s2 = os.stat(path2.parent).st_dev
            
            return s1 == s2
        except Exception:
            return False

    # Función auxiliar para realizar copias físicas de seguridad
    def _transfer_item_as_copy(self, src: Path, dest: Path) -> None:
        
        # Si la carpeta de origen es un directorio
        if src.is_dir():
            # Copia recursiva de directorios
            shutil.copytree(src, dest)
        else:
            # Copia de archivos (preserva metadatos)
            shutil.copy2(src, dest)

