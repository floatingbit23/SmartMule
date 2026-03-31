import os # Módulo para operaciones del sistema operativo
import shutil # Módulo para operaciones con archivos y directorios
import logging
from pathlib import Path
from smartmule.config import LIBRARY_PATH
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
            logger.error(f"❌ [Organizer] Archivo origen no encontrado: {source_path.name}")
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

                logger.critical(f"💀 [Organizer] MALWARE CONFIRMADO!!! Borrando: {filename}")

                # Borro el archivo directamente, sin preguntar al usuario
                os.remove(source_path)
                
                send_notification("Malware Eliminado 💀", f"Se ha detectado malware encubierto en '{filename}' y ha sido borrado permanentemente por seguridad.", is_critical=True)

                logger.critical(f"🗑️ [Organizer] Archivo {filename} eliminado permanentemente del sistema por su seguridad.")
                
                return "<DELETED_MALICIOUS>" # Retorno String especial para que el main sepa que el archivo fue eliminado

            # 2. EVALUACIÓN DE RIESGO MEDIO (SUSPICIOUS)
            if "SUSPICIOUS" in verdict:

                logger.warning(f"⚠️ [Organizer] Archivo sospechoso movido a revisión: {filename}")

                dest_path = self.review_dir / filename # Ruta 01_Review/filename

                shutil.move(str(source_path), str(dest_path)) # Muevo el archivo
                send_notification("Archivo Sospechoso ⚠️", f"El archivo '{filename}' ha sido puesto en cuarentena para su revisión manual.", is_critical=True)

                return str(dest_path) # Retorno la ruta final

            # 3. ARCHIVOS LIMPIOS Y NORMALES (SAFE o UNKNOWN sin riesgo)

            # Diccionario de mapeo de categorías
            category_mapping = {
                "video": "Movies_and_Series",
                "movie": "Movies_and_Series",
                "tv series": "Movies_and_Series",
                "book": "Books_and_Comics",
                "audio": "Audio_and_Music",
                "software": "Software",
                "compressed": "Archives",
                "image": "Images",
                "games": "Games",
                "documents": "Documents",
                "unknown": "Others"
            }

            folder_name = category_mapping.get(media_type, "Others") # Obtengo el nombre de la carpeta
            # "Others" será la carpeta por defecto si no se encuentra el Media Type

            dest_dir = self.library_dir / folder_name # Ruta de la carpeta

            dest_dir.mkdir(parents=True, exist_ok=True) # Creo la carpeta si no existe

            dest_path = dest_dir / filename # Ruta final del archivo

            # Si el archivo ya existe en destino, le añadimos un sufijo para no sobreescribir
            counter = 1

            while dest_path.exists():
                dest_path = dest_dir / f"{source_path.stem}_{counter}{source_path.suffix}"
                counter += 1

            shutil.move(str(source_path), str(dest_path)) # Muevo el archivo
            
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
           
            logger.info(f"{emoji} [Organizer] Movido a Biblioteca ({folder_name}): {dest_path.name}")
            
            # Formatear un título amigable según la carpeta
            cat_name = folder_name.replace("_and_", " y ").replace("_", " ")
            send_notification("Descarga Organizada ✅", f"{emoji} {filename} se ha guardado en tu biblioteca de {cat_name}.")
            
            return str(dest_path)

        except Exception as e:
            logger.error(f"❌ [Organizer] Fallo organizando {filename}: {e}")
            return file_path_str
