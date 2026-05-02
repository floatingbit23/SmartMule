"""
Motor de Persistencia y Motor de Metadatos de SmartMule.

Gestiono el almacenamiento centralizado en SQLite (v3.46+) para garantizar la integridad y el 
enriquecimiento de la biblioteca multimedia.

Este módulo es el "cerebro" que permite:
1. Optimización P2P: Evitar el recalculo de hashes ED2K/SHA256 y prevenir duplicidad de archivos.
2. Enriquecimiento Semántico: Almacenar metadatos avanzados (Autores, Títulos, Resoluciones) 
   obtenidos mediante el análisis híbrido (Regex + LLM + APIs externas).
3. Triage de Seguridad: Persistir veredictos de seguridad y enlaces de informes de VirusTotal.
4. Motor de Búsqueda: Servir como base para el sistema de búsqueda global avanzada (FTS5).
5. Trazabilidad: Mantener el estado de organización (is_organized) y rutas físicas finales.

La base de datos es un archivo autónomo ('smartmule.db') ubicado en la carpeta Library. 
No requiere configuración, es resiliente a fallos y escala eficientemente para miles de registros.
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

    La tabla 'files' almacena:
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
            file_path    TEXT NOT NULL UNIQUE, -- Ruta completa del archivo (ÚNICA para evitar duplicados)
            file_name    TEXT NOT NULL, -- Nombre del archivo
            file_size    INTEGER NOT NULL, -- Tamaño del archivo en bytes
            fingerprint  TEXT NOT NULL DEFAULT '', -- Huella digital SHA256 del contenido
            ed2k_hash    TEXT NOT NULL, -- Hash ED2K en formato hexadecimal
            ed2k_link    TEXT NOT NULL, -- Enlace ed2k:// generado
            processed_at TEXT NOT NULL, -- Fecha y hora en que fue procesado
            file_mtime   INTEGER DEFAULT 0, -- Fecha de modificación del sistema de archivos
            official_title TEXT DEFAULT '', -- Título oficial 
            release_date TEXT DEFAULT '', -- Fecha de lanzamiento
            author TEXT DEFAULT '', -- Autor 
            score REAL DEFAULT 0, -- Puntuación 
            media_type TEXT DEFAULT 'unknown', -- Tipo de archivo (audio, video, documento, imagen, etc.)
            resolution TEXT DEFAULT '', -- Resolución
            languages TEXT DEFAULT '', -- Idiomas detectados
            subtitles TEXT DEFAULT '', -- Subtítulos detectados
            security_verdict TEXT DEFAULT '', -- Veredicto de seguridad
            vt_url TEXT DEFAULT '', -- URL del informe de VirusTotal
            final_path TEXT DEFAULT '', -- Ruta final del archivo
            is_organized INTEGER DEFAULT 0 -- Por defecto: no organizado=0, organizado=1 
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

        logger.debug(f"[*]  Base de datos SQLite abierta en: {db_path}")


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
        # Formato legible: Ejemplo -> 2026-04-28 23:30:26
        processed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

        logger.debug(f"[*]  Hash guardado en caché: {ed2k_hash} ({file_path.name})")


    # Función de búsqueda por nombre (para el comando purge)
    def search_by_name(self, query: str) -> list[dict]:

        """
        Busca registros cuyos nombres de archivo o títulos oficiales coincidan con la consulta.
        Soporta wildcards estilo shell (N*) y expresiones regulares (re).
        """

        # Procesamos el término de búsqueda.
        regex_pattern = query

        # --- INTELIGENCIA DE BÚSQUEDA ---
        # Si el usuario usa '*' o '?', convertimos a regex.
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
            logger.error(f"[ERR]  Error en búsqueda Regex/Wildcard '{query}': {e}")
            return []


    # Función para eliminar un registro por ID
    def delete_by_id(self, record_id: int) -> None:
        """
        Elimina un registro de la base de datos por su ID único.
        """
        self._conn.execute("DELETE FROM files WHERE id = ?", (record_id,))
        self._conn.commit()
        logger.debug(f"[*]  Registro {record_id} eliminado de la base de datos.")


    # Función de actualización de metadatos
    def update_metadata(self, fingerprint: str, file_size: int, metadata: dict, final_path: str) -> None:

        """
        Actualiza el registro en la caché con los metadatos enriquecidos y la información del Organizador.
        """

        api_data = metadata.get("api_data") or {}
        
        # Metadatos técnicos extraídos por el Parser o Inspección FFmpeg
        resolution = metadata.get("resolution", "")

        # === EXTRACCIÓN CON RESPALDO (API > PARSER) ===
        
        # Título oficial (Si no hay API, usamos el nombre limpio del regex parser)
        official_title = api_data.get("official_title") or metadata.get("title", "")

        # Fecha de lanzamiento (Si no hay API, usamos el año del regex parser)
        release_date = api_data.get("date") or str(metadata.get("year", ""))

        # Autor (Si no hay API, usamos el autor extraído por el regex parser)
        author = api_data.get("author") or metadata.get("author", "")

        # Puntuación
        score = api_data.get("score", 0.0)

        # Tipo de archivo
        media_type = metadata.get("media_type", "unknown")

        # Idiomas y Subtítulos
        languages = metadata.get("languages", "")
        subtitles = metadata.get("subtitles", "")

        # Veredicto de seguridad (Limpiamos colores ANSI)
        raw_verdict = api_data.get("veredicto", "")
        import re
        security_verdict = re.sub(r'\x1b\[[0-9;]*m', '', raw_verdict)
        
        # URL de VirusTotal
        vt_url = api_data.get("url", "")
        
        # Estado del organizador
        is_organized = 1 if final_path else 0

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

        self._conn.commit()
        logger.debug(f"[*]  Metadatos actualizados en BBDD para huella: {fingerprint[:8]}...")


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
        Devuelve un resumen estadístico: total de archivos, conteo por categoría y tamaño acumulado.
        """
        
        stats = {
            "total": 0,
            "total_size": 0,
            "categories": {}
        }

        try:
            # 1. Obtener total y tamaño acumulado
            cursor = self._conn.execute("SELECT COUNT(*), SUM(file_size) FROM files")
            row = cursor.fetchone()
            stats["total"] = row[0]
            stats["total_size"] = row[1] or 0

            # 2. Obtener conteo por categoría
            cursor = self._conn.execute("SELECT media_type, COUNT(*) FROM files GROUP BY media_type ORDER BY COUNT(*) DESC")
            for row in cursor.fetchall():
                stats["categories"][row[0]] = row[1]
            
        except Exception as e:
            logger.error(f"[ERR]  Error al obtener estadísticas de la BBDD: {e}")
        
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
                logger.error(f"[ERR]  Error parseando JSON de caché para hash {ed2k_hash}: {e}")
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
        # Formato legible: Ejemplo -> 2026-04-28 23:30:26
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            metadata_json = json.dumps(metadata_dict)
            self._conn.execute(sql, (ed2k_hash, metadata_json, now_str))
            self._conn.commit()
            logger.debug(f"[SAVE] Metadatos cacheados para hash {ed2k_hash}")
        except Exception as e:
            logger.error(f"[ERR]  Error guardando en metadata_cache para {ed2k_hash}: {e}")


    # Función de cierre de la BBDD SQLite
    def close(self) -> None:

        """
        Cierro la conexión a la base de datos (BBDD) SQLite limpiamente.
        Llamo a este método durante el shutdown de SmartMule.
        """

        self._conn.close() # Cierro la conexión
        
        logger.debug("[*]  Conexión a la BBDD SQLite cerrada.")
