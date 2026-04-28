"""
Caché SQLite para los hashes ED2K procesados por SmartMule.

Uso la BBDD Relacional ligera SQLite (v3.46.0) para persistir los hashes de los archivos ya procesados. 
Esto me permite:
1. Evitar recalcular el hash de un archivo que ya fue procesado anteriormente.
2. Mantener un historial de todos los archivos que SmartMule ha gestionado.
3. Consultar en implementaciones posteriores si un archivo concreto ya fue clasificado.

La base de datos (BBDD) es un archivo único ('smartmule.db') en la carpeta Library (reside en el disco duro del usuario, memoria persistente).
No necesita un servidor, no tiene dependencias externas y se crea automáticamente si no existe. 
"""

import re # Para el soporte de expresiones regulares en la búsqueda
import sqlite3 
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional # Para indicar que una función puede devolver None
 
logger = logging.getLogger("SmartMule.database")

# Clase principal para la gestión de la base de datos
class HashDatabase:

    """
    Gestiono la caché SQLite de hashes ED2K procesados.

    La tabla 'hashes' almacena:
    - La ruta y el nombre del archivo procesado.
    - Su tamaño en bytes.
    - Su hash ED2K en formato hexadecimal.
    - El enlace ed2k:// generado.
    - La fecha y hora en que fue procesado.
    """

    # Sentencia SQL para crear la tabla si no existe
    # Uso 'CREATE TABLE IF NOT EXISTS' para que sea idempotente (se puede llamar múltiples veces sin error).
    
    _CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS files (
            id           INTEGER PRIMARY KEY AUTOINCREMENT, -- Identificador único de cada registro
            file_path    TEXT NOT NULL, -- Ruta completa del archivo
            file_name    TEXT NOT NULL, -- Nombre del archivo
            file_size    INTEGER NOT NULL, -- Tamaño del archivo en bytes
            fingerprint  TEXT NOT NULL DEFAULT '', -- Huella digital SHA256 del contenido
            ed2k_hash    TEXT NOT NULL, -- Hash ED2K en formato hexadecimal
            ed2k_link    TEXT NOT NULL, -- Enlace ed2k:// generado
            processed_at TEXT NOT NULL, -- Fecha y hora en que fue procesado
            file_mtime   INTEGER DEFAULT 0, -- Fecha de modificación del sistema de archivos
            official_title TEXT DEFAULT '',
            release_date TEXT DEFAULT '',
            author TEXT DEFAULT '',
            score REAL DEFAULT 0,
            media_type TEXT DEFAULT 'unknown',
            resolution TEXT DEFAULT '',
            languages TEXT DEFAULT '',
            subtitles TEXT DEFAULT '',
            security_verdict TEXT DEFAULT '',
            vt_url TEXT DEFAULT '',
            final_path TEXT DEFAULT '',
            is_organized INTEGER DEFAULT 0
        );
    """

    # Tabla para la Caché de Búsquedas LLM (Optimización de API)
    # Almacena de forma persistente los metadatos completos asociados a un hash ED2K.
    _CREATE_CACHE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS metadata_cache (
            ed2k_hash    TEXT PRIMARY KEY, -- Hash único del archivo
            metadata     TEXT NOT NULL,    -- JSON con el resultado del análisis (IA + API)
            cached_at    TEXT NOT NULL     -- Fecha en la que se cacheó
        );
    """


    # Migraciones para añadir columnas a bases de datos antiguas de forma segura
    _MIGRATIONS = [
        "ALTER TABLE files ADD COLUMN fingerprint TEXT NOT NULL DEFAULT '';",
        "ALTER TABLE files ADD COLUMN file_mtime INTEGER DEFAULT 0;",
        "ALTER TABLE files ADD COLUMN official_title TEXT DEFAULT '';",
        "ALTER TABLE files ADD COLUMN release_date TEXT DEFAULT '';",
        "ALTER TABLE files ADD COLUMN author TEXT DEFAULT '';",
        "ALTER TABLE files ADD COLUMN score REAL DEFAULT 0;",
        "ALTER TABLE files ADD COLUMN media_type TEXT DEFAULT 'unknown';",
        "ALTER TABLE files ADD COLUMN resolution TEXT DEFAULT '';",
        "ALTER TABLE files ADD COLUMN languages TEXT DEFAULT '';",
        "ALTER TABLE files ADD COLUMN subtitles TEXT DEFAULT '';",
        "ALTER TABLE files ADD COLUMN security_verdict TEXT DEFAULT '';",
        "ALTER TABLE files ADD COLUMN vt_url TEXT DEFAULT '';",
        "ALTER TABLE files ADD COLUMN final_path TEXT DEFAULT '';",
        "ALTER TABLE files ADD COLUMN is_organized INTEGER DEFAULT 0;"
    ]

    # Índice compuesto (dos columnas) sobre la huella y el tamaño para búsquedas instantáneas e inequívocas (O(log n)).
    # NO es UNIQUE para evitar riesgo de colisiones de hashes SHA256 (aunque sean muy improbables).
    _CREATE_INDEX_SQL = """
        CREATE INDEX IF NOT EXISTS idx_fingerprint_size ON files (fingerprint, file_size);
    """


    # Constructor
    def __init__(self, db_path: Path):

        """
        Abro (o creo) la base de datos (BBDD) SQLite y me aseguro de que la tabla existe.

        Args:
            db_path: Ruta al archivo .db (se crea si no existe)
        """

        # Me aseguro de que el directorio padre existe antes de crear el archivo .db.
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Abro la conexión con la BBDD SQLite.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.create_function("REGEXP", 2, self._regexp_worker)


        # 1º. Creo las tablas si no existen.
        self._conn.execute(self._CREATE_TABLE_SQL)
        self._conn.execute(self._CREATE_CACHE_TABLE_SQL)
        

        # 2º. MIGRACIONES: Aseguro que las columnas necesarias existan antes de indexar

        for sql in self._MIGRATIONS: # Lista de sentencias SQL de migración
            try:
                self._conn.execute(sql) # Ejecuto la sentencia SQL
            except sqlite3.OperationalError: 
                pass # Si hay error, lo ignoro (la columna ya existía)


        # 3º. ÍNDICES: Ahora que las columnas existen seguro, creo el índice si no existe.
        self._conn.execute(self._CREATE_INDEX_SQL)


        # 4º. Confirmo los cambios en la BBDD.
        self._conn.commit()

        logger.debug(f"🔹  Base de datos SQLite abierta en: {db_path}")


    def _regexp_worker(self, expr: str, item: str) -> bool:
        """
        Función auxiliar que ejecuta la lógica de búsqueda regex.
        SQLite llama a esta función por cada fila cuando usamos 'WHERE col REGEXP ?'.
        """
        if item is None:
            return False
        try:
            # Uso re.IGNORECASE para que no importe si escribes en mayúsculas o minúsculas.
            return re.search(expr, item, re.IGNORECASE) is not None
        except Exception:
            return False

    # Función de búsqueda por hash ED2K
    def get_by_hash(self, ed2k_hash: str) -> Optional[dict]:

        """
        Busco un archivo en la caché por su hash ED2K.

        Args:
            ed2k_hash: Hash ED2K en formato hexadecimal (32 caracteres).

        Returns:
            Diccionario con los datos del registro si existe, None si no está en caché.
        """

        # Consulta SQL que busca un archivo por su hash ED2K
        cursor = self._conn.execute( 
            "SELECT * FROM files WHERE ed2k_hash = ?", # uso placeholder '?' para evitar inyección SQL
            (ed2k_hash,) # tupla de 1 elemento
        )

        row = cursor.fetchone() # Obtengo el primer (y único) resultado

        # Convierto el sqlite3.Row a un diccionario ordinario para que sea más cómodo de usar.
        return dict(row) if row else None


    # Función de búsqueda por huella digital
    def get_by_fingerprint(self, fingerprint: str, file_size: int) -> Optional[dict]:

        """
        Busco un archivo en la caché por su Fingerprint y tamaño.
        Esta es la forma más rápida y robusta de identificar un archivo incluso si ha sido renombrado o movido.

        Args:
            fingerprint: El hash SHA256 de la huella digital.
            file_size: Tamaño del archivo para mayor seguridad ante colisiones.

        Returns:
            Registro de la BBDD si hay coincidencia, None en caso contrario.
        """

        # Consulta SQL que busca un archivo por su huella digital y tamaño
        cursor = self._conn.execute(
            "SELECT * FROM files WHERE fingerprint = ? AND file_size = ?",
            (fingerprint, file_size)
        )

        row = cursor.fetchone()

        return dict(row) if row else None


    # Función de guardado en la BBDD SQLite
    def save(
        self,
        file_path: Path,
        file_size: int,
        fingerprint: str,
        ed2k_hash: str,
        ed2k_link: str,
    ) -> None: 

        """
        Guardo un nuevo registro de archivo procesado en la caché (BBDD).

        Args:
            file_path: Ruta completa.
            file_size: Tamaño en bytes.
            fingerprint: Huella digital SHA256 del contenido.
            ed2k_hash: Hash ED2K.
            ed2k_link: Enlace ed2k://.
        """

        # Uso ISO 8601 con la zona horaria local del usuario para el timestamp.
        processed_at = datetime.now().astimezone().isoformat()

        # Consulta SQL que inserta o reemplaza un registro en la tabla 'files'
        self._conn.execute(
            """
            INSERT OR REPLACE INTO files
                (file_path, file_name, file_size, fingerprint, file_mtime, ed2k_hash, ed2k_link, processed_at)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(file_path),
                file_path.name,
                file_size,
                fingerprint,
                int(file_path.stat().st_mtime),
                ed2k_hash,
                ed2k_link,
                processed_at,
            )
        )

        self._conn.commit()

        logger.debug(f"🔹  Hash guardado en caché: {ed2k_hash} ({file_path.name})")


    # Función de búsqueda por nombre (para el comando purge)
    def search_by_name(self, query: str) -> list[dict]:
        """
        Busca registros cuyos nombres de archivo o títulos oficiales coincidan con la consulta.
        Soporta wildcards estilo shell (N*) y expresiones regulares (re).
        """
        regex_pattern = query
        
        # --- INTELIGENCIA DE BÚSQUEDA ---
        # Si el usuario usa '*' o '?', intentamos ser inteligentes.
        # Pero solo si NO parece una expresión regular compleja (que ya traiga +, [, ], etc.)
        regex_chars = ['+', '[', ']', '(', ')', '{', '}', '$', '^']
        has_regex_markers = any(c in query for c in regex_chars)

        if ("*" in query or "?" in query) and not has_regex_markers:
            # Es un patrón simple de "wildcard" (estilo shell).
            # Escapamos caracteres especiales pero convertimos los wildcards:
            # '*' -> '.*' (cualquier cosa)
            # '?' -> '.'  (un carácter)
            regex_pattern = re.escape(query).replace(r"\*", ".*").replace(r"\?", ".")
            
            # Si el patrón no empieza por wildcard, anclamos al principio para que "N*" sea "Empieza por N"
            if not query.startswith("*") and not regex_pattern.startswith("^"):
                regex_pattern = "^" + regex_pattern
        
        # SQL con el operador REGEXP (habilitado por nuestra función personalizada)
        sql = """
            SELECT * FROM files 
            WHERE file_name REGEXP ? OR official_title REGEXP ?
            ORDER BY processed_at DESC
        """
        
        try:
            cursor = self._conn.execute(sql, (regex_pattern, regex_pattern))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"❌  Error en búsqueda Regex/Wildcard '{query}': {e}")
            return []


    # Función para eliminar un registro por ID
    def delete_by_id(self, record_id: int) -> None:
        """
        Elimina un registro de la base de datos por su ID único.
        """
        self._conn.execute("DELETE FROM files WHERE id = ?", (record_id,))
        self._conn.commit()
        logger.debug(f"🔹  Registro {record_id} eliminado de la base de datos.")


    # Función de actualización de metadatos
    def update_metadata(self, fingerprint: str, file_size: int, metadata: dict, final_path: str) -> None:

        """
        Actualiza el registro en la caché con los metadatos enriquecidos y la información del Organizador.
        """

        # Extraigo los valores (values) del diccionario que devuelve el MetadataEngine
        api_data = metadata.get("api_data") or {}
        
        # Metadatos extraídos por el Parser (Regex o IA)
        resolution = metadata.get("resolution", "")
        languages = metadata.get("languages", "")

        # Extraigo los metadatos de las APIs:

        # Título oficial
        official_title = api_data.get("official_title", "")

        # Fecha de lanzamiento/estreno
        release_date = api_data.get("date", "")

        # Autor
        author = api_data.get("author", "")

        # Puntuación dada por los usuarios
        score = api_data.get("score", 0.0)

        # Tipo de archivo (película, serie, etc.)
        media_type = metadata.get("media_type", "unknown")

        # Idiomas (Audio)
        languages = metadata.get("languages", "")

        # Subtítulos (VOSE, etc.)
        subtitles = metadata.get("subtitles", "")

        # Veredicto de seguridad (Safe, Suspicious o Malicious)
        raw_verdict = api_data.get("veredicto", "")

        # Limpiamos códigos de colores ANSI para que la BBDD guarde texto plano y no BLOBs
        import re
        security_verdict = re.sub(r'\033\[[0-9;]*m', '', raw_verdict)
        
        # URL del informe de VirusTotal
        vt_url = api_data.get("url", "")
        
        # 1 si está organizado (tiene ruta final), 0 si no (no se ha movido o no se ha encontrado)
        is_organized = 1 if final_path else 0

        # Actualizo el registro en la caché con los metadatos enriquecidos y la información del Organizador
        self._conn.execute(
            """
            UPDATE files
            SET official_title=?, release_date=?, author=?, score=?, media_type=?, 
                resolution=?, languages=?, subtitles=?, security_verdict=?, vt_url=?, final_path=?, is_organized=?
            WHERE fingerprint=? AND file_size=?
            """,
            (official_title, release_date, author, score, media_type,
             resolution, languages, subtitles, security_verdict, vt_url, final_path, is_organized, fingerprint, file_size)
        )

        # Uso el fingerprint (la huella SHA256) y el file_size en el WHERE. 
        # Esto garantiza que, aunque tenga dos archivos que se llamen igual, solo actualizaré el registro exacto cuya huella digital coincida.

        self._conn.commit() # Confirmo los cambios en la BBDD

        logger.debug(f"🔹  Metadatos actualizados en BBDD para huella: {fingerprint[:8]}...")


    # Función para obtener todos los registros (para el flag --list)
    def get_all_files(self) -> list[dict]:

        """
        Devuelve todos los archivos registrados en la base de datos, ordenados por fecha de procesamiento (los más recientes primero).
        """

        sql = "SELECT * FROM files ORDER BY processed_at DESC"
        cursor = self._conn.execute(sql)
        return [dict(row) for row in cursor.fetchall()]


    # Función para obtener estadísticas de la base de datos
    def get_stats(self) -> dict:

        """
        Devuelve un resumen estadístico: total de archivos y conteo por categoría.
        """
        
        stats = {
            "total": 0,
            "categories": {}
        }

        try:
            # 1. Obtener total
            cursor = self._conn.execute("SELECT COUNT(*) FROM files")
            stats["total"] = cursor.fetchone()[0]

            # 2. Obtener conteo por categoría
            cursor = self._conn.execute("SELECT media_type, COUNT(*) FROM files GROUP BY media_type ORDER BY COUNT(*) DESC")
            for row in cursor.fetchall():
                stats["categories"][row[0]] = row[1]
            
        except Exception as e:
            logger.error(f"❌  Error al obtener estadísticas de la BBDD: {e}")
        
        return stats


    # --- MÉTODOS DE CACHÉ DE LLM ---
    def get_metadata_cache(self, ed2k_hash: str) -> Optional[dict]:
        """Recupera los metadatos parseados previamente para un hash ED2K."""
        if not ed2k_hash:
            return None
            
        sql = "SELECT metadata FROM metadata_cache WHERE ed2k_hash = ?"
        cursor = self._conn.execute(sql, (ed2k_hash,))
        row = cursor.fetchone()
        
        if row:
            import json
            try:
                return json.loads(row['metadata'])
            except Exception as e:
                logger.error(f"❌  Error parseando JSON de caché para hash {ed2k_hash}: {e}")
                return None
        return None

    def set_metadata_cache(self, ed2k_hash: str, metadata_dict: dict) -> None:
        """Guarda permanentemente el resultado del análisis (IA+API) para un hash."""
        if not ed2k_hash or not metadata_dict:
            return
            
        import json
        sql = """
            INSERT OR REPLACE INTO metadata_cache (ed2k_hash, metadata, cached_at)
            VALUES (?, ?, ?)
        """
        now_str = datetime.now(timezone.utc).isoformat()
        try:
            metadata_json = json.dumps(metadata_dict)
            self._conn.execute(sql, (ed2k_hash, metadata_json, now_str))
            self._conn.commit()
            logger.debug(f"💾 Metadatos cacheados para hash {ed2k_hash}")
        except Exception as e:
            logger.error(f"❌  Error guardando en metadata_cache para {ed2k_hash}: {e}")


    # Función de cierre de la BBDD SQLite
    def close(self) -> None:

        """
        Cierro la conexión a la base de datos (BBDD) SQLite limpiamente.
        Llamo a este método durante el shutdown de SmartMule.
        """

        self._conn.close() # Cierro la conexión
        
        logger.debug("🔹  Conexión a la BBDD SQLite cerrada.")
