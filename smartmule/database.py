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
        CREATE TABLE IF NOT EXISTS hashes (
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
            security_verdict TEXT DEFAULT '',
            vt_url TEXT DEFAULT '',
            final_path TEXT DEFAULT '',
            is_organized INTEGER DEFAULT 0
        );
    """

    # Migraciones para añadir columnas a bases de datos antiguas de forma segura
    _MIGRATIONS = [
        "ALTER TABLE hashes ADD COLUMN fingerprint TEXT NOT NULL DEFAULT '';",
        "ALTER TABLE hashes ADD COLUMN file_mtime INTEGER DEFAULT 0;",
        "ALTER TABLE hashes ADD COLUMN official_title TEXT DEFAULT '';",
        "ALTER TABLE hashes ADD COLUMN release_date TEXT DEFAULT '';",
        "ALTER TABLE hashes ADD COLUMN author TEXT DEFAULT '';",
        "ALTER TABLE hashes ADD COLUMN score REAL DEFAULT 0;",
        "ALTER TABLE hashes ADD COLUMN media_type TEXT DEFAULT 'unknown';",
        "ALTER TABLE hashes ADD COLUMN security_verdict TEXT DEFAULT '';",
        "ALTER TABLE hashes ADD COLUMN vt_url TEXT DEFAULT '';",
        "ALTER TABLE hashes ADD COLUMN final_path TEXT DEFAULT '';",
        "ALTER TABLE hashes ADD COLUMN is_organized INTEGER DEFAULT 0;"
    ]

    # Índice compuesto (dos columnas) sobre la huella y el tamaño para búsquedas instantáneas e inequívocas (O(log n)).
    # NO es UNIQUE para evitar riesgo de colisiones de hashes SHA256 (aunque sean muy improbables).
    _CREATE_INDEX_SQL = """
        CREATE INDEX IF NOT EXISTS idx_fingerprint_size ON hashes (fingerprint, file_size);
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

        # 'check_same_thread=False' es necesario porque la BBDD 
        # es instanciada en el Main Thread (QueueManager._db) pero usada en el Worker Thread (_worker_loop._process_file._db.save())

        # Configuro SQLite para que devuelva filas que se comportan como diccionarios.
        self._conn.row_factory = sqlite3.Row
        # Así podré acceder a las columnas por nombre (ej: row['ed2k_hash']) en lugar de por índice.


        # 1º. Creo la tabla si no existe.
        self._conn.execute(self._CREATE_TABLE_SQL)
        

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
            "SELECT * FROM hashes WHERE ed2k_hash = ?", # uso placeholder '?' para evitar inyección SQL
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
            "SELECT * FROM hashes WHERE fingerprint = ? AND file_size = ?",
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

        # Consulta SQL que inserta o reemplaza un registro en la tabla 'hashes'
        self._conn.execute(
            """
            INSERT OR REPLACE INTO hashes
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


    # Función de actualización de metadatos
    def update_metadata(self, fingerprint: str, file_size: int, metadata: dict, final_path: str) -> None:

        """
        Actualiza el registro en la caché con los metadatos enriquecidos y la información del Organizador.
        """

        # Extraigo los valores (values) del diccionario que devuelve el MetadataEngine
        api_data = metadata.get("api_data") or {}

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

        # Veredicto de seguridad (Safe, Suspicious o Malicious)
        raw_verdict = api_data.get("veredicto", "")

        # Limpiamos códigos de colores ANSI para que la BBDD guarde texto plano y no BLOBs
        import re
        security_verdict = re.sub(r'\033\[[0-9;]*m', '', raw_verdict)
        
        # URL del informe de VirusTotal
        vt_url = api_data.get("url", "")
        
        # 1 si está organizado (tiene ruta final), 0 si no (no se ha movido o no se ha encontrado)
        is_organized = 1 if final_path else 0

        # Cadena vacía ("") es el valor por defecto si no se encuentra el metadato

        # Actualizo el registro en la caché con los metadatos enriquecidos y la información del Organizador
        self._conn.execute(
            """
            UPDATE hashes
            SET official_title=?, release_date=?, author=?, score=?, media_type=?, 
                security_verdict=?, vt_url=?, final_path=?, is_organized=?
            WHERE fingerprint=? AND file_size=?
            """,
            (official_title, release_date, author, score, media_type,
             security_verdict, vt_url, final_path, is_organized, fingerprint, file_size)
        )

        # Uso el fingerprint (la huella SHA256) y el file_size en el WHERE. 
        # Esto garantiza que, aunque tenga dos archivos que se llamen igual, solo actualizaré el registro exacto cuya huella digital coincida.

        self._conn.commit() # Confirmo los cambios en la BBDD

        logger.debug(f"🔹  Metadatos actualizados en BBDD para huella: {fingerprint[:8]}...")


    # Función de cierre de la BBDD SQLite
    def close(self) -> None:

        """
        Cierro la conexión a la base de datos (BBDD) SQLite limpiamente.
        Llamo a este método durante el shutdown de SmartMule.
        """

        self._conn.close() # Cierro la conexión
        
        logger.debug("🔹  Conexión a la BBDD SQLite cerrada.")
