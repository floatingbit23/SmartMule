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
    Se encarga de clasificar, mover o eliminar el archivo basándose en los metadatos y en el triaje de seguridad de SmartMule.
    """

    # Constructor de la clase LibraryOrganizer
    def __init__(self):

        # Ruta base de la biblioteca
        self.library_dir = Path(LIBRARY_PATH)

        # Directorio de cuarentena
        self.quarantine_dir = self.library_dir / "00_Quarantine"

        # Directorio de revisión
        self.review_dir = self.library_dir / "01_Review"

        # Creo directorios críticos si no existen
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.review_dir.mkdir(parents=True, exist_ok=True)


    # Método para organizar los archivos
    def organize(self, file_path_str: str, metadata: dict) -> str:

        """
        Organiza el archivo. 
        Si es "MALICIOUS": os.remove().
        Si es "SUSPICIOUS": Mover a 01_Review.
        Si es "SAFE": Mover a Library/<tipo_de_archivo>/

        Retorna la ruta final del archivo como string.
        """

        # Convierto el string a objeto Path para mejor manejo
        source_path = Path(file_path_str)
        
        # Compruebo si el archivo existe
        if not source_path.exists():
            logger.error(f"[ERR]  Archivo origen no encontrado: {source_path.name}")
            return file_path_str

        # Extraigo los metadatos necesarios
        api_data = metadata.get("api_data") or {}
        verdict = api_data.get("veredicto", "").upper()
        media_type = metadata.get("media_type", "unknown")
        filename = source_path.name 

        # Lógica de clasificación
        try:
            # Si el veredicto es "MALICIOUS", se elimina el archivo de forma permanente.
            if "MALICIOUS" in verdict:
                return self._handle_malicious(source_path, filename)
            
            # Si el veredicto es "SUSPICIOUS", se mueve el archivo a la carpeta de cuarentena.
            if "SUSPICIOUS" in verdict:
                return self._handle_suspicious(source_path, filename)
            
            # Si el veredicto es "SAFE", se mueve el archivo a la carpeta de biblioteca.
            return self._handle_clean_file(source_path, filename, metadata, api_data, media_type)

        except Exception as e:
            logger.error(f"[ERR] Fallo organizando {filename}: {e}")
            return file_path_str


    # Método para manejar archivos maliciosos
    def _handle_malicious(self, source_path: Path, filename: str) -> str:

        logger.critical(f"[MALWARE] MALWARE CONFIRMADO!!! Borrando: {filename}")

        # Si es un directorio, uso rmtree; si es un archivo, uso remove.
        if source_path.is_dir():
            shutil.rmtree(source_path)
        else:
            os.remove(source_path)

        # Envío notificación (pop-up) de seguridad.
        send_notification("Malware Eliminado [MALWARE]", f"Se ha detectado malware encubierto en '{filename}' y ha sido borrado permanentemente por seguridad.", is_critical=True)
        
        logger.critical(f"[DEL] Ítem {filename} eliminado permanentemente del sistema por su seguridad.")

        return "<DELETED_MALICIOUS>" # Retorno string para indicar que el archivo ha sido eliminado.


    # Método para manejar archivos sospechosos
    def _handle_suspicious(self, source_path: Path, filename: str) -> str:

        logger.warning(f"[WARN]  Archivo sospechoso movido a revisión: {filename}")

        # Defino el path de destino en la carpeta de cuarentena.
        dest_path = self.review_dir / filename 
        
        counter = 1
        base_stem = source_path.stem
        suffix = "" if source_path.is_dir() else source_path.suffix
        
        # Mientras el archivo exista en la carpeta de cuarentena, le añado un contador al final del nombre.
        while dest_path.exists():
            dest_path = self.review_dir / f"{base_stem}_{counter}{suffix}"
            counter += 1

        self._transfer_item(source_path, dest_path) 
        
        # Envío notificación (pop-up) de seguridad.
        send_notification("Archivo Sospechoso [WARN]", f"El archivo '{filename}' ha sido puesto en cuarentena para su revisión manual.", is_critical=True)
        
        return str(dest_path) 


    # Método para obtener la carpeta de destino
    def _get_category_folder(self, media_type: str, metadata: dict) -> str:

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

        # Si el tipo de archivo es "video" y tiene un año, lo considero una película. Si no tiene año, lo considero un clip.
        if media_type == "video" and metadata.get("year"):
            current_media_type = "movie"
        else:
            current_media_type = media_type
        return category_mapping.get(current_media_type, "Others")

    # Método para generar un nombre legible para el archivo.
    def _generate_pretty_name(self, filename: str, source_path: Path, metadata: dict, api_data: dict) -> tuple[str, str, str]:
        
        suffix = source_path.suffix if source_path.is_file() else ""
        base_name = filename 

        # Si la API devolvió un título oficial, lo uso. Si no, uso el título de los metadatos.
        if api_data and api_data.get("official_title"):
            base_name = api_data["official_title"]
            if suffix and base_name.lower().endswith(suffix.lower()):
                base_name = base_name[:-len(suffix)]
        elif metadata.get("title"):
            base_name = metadata["title"]

        year = metadata.get("year")

        # Formateo el nombre base con el año.
        if year:
            pretty_name = f"{base_name} ({year})"
        else:
            pretty_name = base_name

        # Elimino caracteres inválidos para nombres de archivo.
        clean_filename = re.sub(r'[\\/:*?"<>|]', '', pretty_name).strip()
        final_filename = f"{clean_filename}{suffix}"
        
        return final_filename, clean_filename, suffix

    # Método para obtener el emoji correspondiente a la categoría.
    def _get_emoji_for_category(self, folder_name: str) -> str:
        if folder_name == "Movies_and_Series": return "[MOVIE]"
        elif folder_name == "Books": return "[BOOK]"
        elif folder_name == "Audio_and_Music": return "[AUDIO]"
        elif folder_name == "Software": return "[SW]"
        elif folder_name == "Archives": return "[ARCHIVE]"
        elif folder_name == "Images": return "[IMG]"
        elif folder_name == "Games": return "[GAME]"
        elif folder_name == "Documents": return "[DOC]"
        else: return "[DIR]"


    # Método para manejar archivos limpios.
    def _handle_clean_file(self, source_path: Path, filename: str, metadata: dict, api_data: dict, media_type: str) -> str:
        
        folder_name = self._get_category_folder(media_type, metadata)
        dest_dir = self.library_dir / folder_name 
        dest_dir.mkdir(parents=True, exist_ok=True) 

        # Genero el nombre final del archivo.
        final_filename, clean_filename, suffix = self._generate_pretty_name(filename, source_path, metadata, api_data)
        dest_path = dest_dir / final_filename

        # Si el archivo ya existe, le añado un contador al final del nombre.
        counter = 1
        while dest_path.exists():
            dest_path = dest_dir / f"{clean_filename}_{counter}{suffix}"
            counter += 1

        # Transfiero el archivo a la carpeta correspondiente.
        self._transfer_item(source_path, dest_path)
        
        # Obtengo el emoji correspondiente a la categoría.
        emoji = self._get_emoji_for_category(folder_name)
        logger.info(f"{emoji} Movido a Biblioteca ({folder_name}): {dest_path.name}")
        
        # Formateo el nombre de la categoría para la notificación.
        cat_name = folder_name.replace("_and_", " y ").replace("_", " ")
        send_notification("Descarga Organizada [OK]", f"{emoji} {filename} se ha guardado en tu biblioteca de {cat_name}.")
        
        return str(dest_path) # Retorno el path del archivo organizado.

    # Función para transferir el archivo o directorio
    def _transfer_item(self, src: Path, dest: Path) -> None:

        """
        Transfiere el archivo o directorio basándose en ORGANIZER_MODE ("move", "copy", "hardlink").
        Si falla un hardlink por error de partición cruzada, realiza silenciosamente un fallback a "copy".
        """

        mode = ORGANIZER_MODE # Obtengo el modo de transferencia

        # Decido qué método de transferencia usar según el modo configurado en el .env
        if mode == "move":
            self._transfer_item_as_move(src, dest)
        elif mode == "copy":
            self._transfer_item_as_copy(src, dest)
        elif mode == "hardlink":
            self._transfer_item_as_hardlink(src, dest)
        else:
            # Por si el ENVIRONMENT_VARIABLE viene mal tipada
            shutil.move(str(src), str(dest))


    # Método para mover archivos
    def _transfer_item_as_move(self, src: Path, dest: Path) -> None:

        # Validamos si origen y destino están en el mismo disco físico (Zero-Copy Validation)
        if self._is_same_device(src, dest):

            # Realizo el movimiento
            os.rename(str(src), str(dest))
            logger.debug(f"[FAST]  Movimiento 'Zero-Copy' completado para {src.name}")

        else:
            # Si están en discos distintos, avisamos que la operación será más lenta (Copy + Delete)
            logger.warning(f"[SAVE] Movimiento entre discos detectado: {src.name} se copiará al nuevo destino. Esto puede tardar unos minutos...")
            shutil.move(str(src), str(dest)) # Ejecutamos la copia


    # Método para crear Hard Links
    def _transfer_item_as_hardlink(self, src: Path, dest: Path) -> None:

        try:

            # Si la carpeta de origen es un directorio
            if src.is_dir():

                # Para carpetas, recreo la estructura de carpetas y hardlinkeo cada fichero base
                dest.mkdir(parents=True, exist_ok=True)

                # Recorro la estructura de la carpeta
                for root, dirs, files in os.walk(src):

                    # Defino la ruta raíz
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
            
            # Log final
            logger.info(f"[LINK]  Hardlink creado: {src.name} -> {dest.name}")

        except OSError as e:

            # Fallback silencioso a copia si falla el hardlink (ej: intento entre particiones distintas C: y D:)
            logger.warning(f"[WARN]  No se pudo crear hardlink ({e}). Reintentando mediante copia física...")
            self._transfer_item_as_copy(src, dest) # Fallback a copia


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
            
            return s1 == s2 # Si coinciden, os.rename() es una operación de punteros instant?nea.

        except Exception:
            return False # En caso de error, preferimos hacer copy antes que romper


    # Función auxiliar para realizar copias físicas de seguridad
    def _transfer_item_as_copy(self, src: Path, dest: Path) -> None:
        
        # Si la carpeta de origen es un directorio
        if src.is_dir():

            # Copia recursiva de directorios
            shutil.copytree(src, dest)

        else:
            # Copia de archivos (preserva metadatos)
            shutil.copy2(src, dest)

