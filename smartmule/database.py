"""
database.py — Caché SQLite para los hashes ED2K procesados por SmartMule.

Uso SQLite (incluido en Python estándar) para persistir los hashes de los archivos
ya procesados. Esto me permite:

1. Evitar recalcular el hash de un archivo que ya fue procesado anteriormente.
2. Mantener un historial de todos los archivos que SmartMule ha gestionado.
3. Consultar en retos posteriores si un archivo concreto ya fue clasificado.

La base de datos (BBDD) es un archivo único ('smartmule.db') en la carpeta Library.
No necesita un servidor, no tiene dependencias externas y se crea automáticamente
si no existe.
"""

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("SmartMule.database")


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

    # Sentencia SQL para crear la tabla si no existe.
    # Uso 'CREATE TABLE IF NOT EXISTS' para que sea idempotente (se puede llamar múltiples veces sin error).
    _CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS hashes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path    TEXT NOT NULL,
            file_name    TEXT NOT NULL,
            file_size    INTEGER NOT NULL,
            file_mtime    REAL NOT NULL DEFAULT 0,
            ed2k_hash    TEXT NOT NULL,
            ed2k_link    TEXT NOT NULL,
            processed_at TEXT NOT NULL
        );
    """

    # Migración: Me aseguro de que la columna file_mtime exista (por si el usuario ya tenía la DB de antes)
    _MIGRATE_SQL = "ALTER TABLE hashes ADD COLUMN file_mtime REAL NOT NULL DEFAULT 0;"

    # Índice sobre el hash para que las búsquedas sean O(log n) en lugar de O(n).
    _CREATE_INDEX_SQL = """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ed2k_hash ON hashes (ed2k_hash);
    """

    def __init__(self, db_path: Path):
        """
        Abro (o creo) la base de datos (BBDD) SQLite y me aseguro de que la tabla existe.

        Args:
            db_path: Ruta al archivo .db (se crea automáticamente si no existe).
        """

        # Me aseguro de que el directorio padre existe antes de crear el archivo .db.
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Abro la conexión. 'check_same_thread=False' es necesario porque la BBDD
        # es instanciada en el hilo principal pero usada en el Worker Thread.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)

        # Configuro SQLite para que devuelva filas que se comportan como diccionarios.
        # Así puedo acceder a las columnas por nombre (ej: row['ed2k_hash']) en lugar de por índice.
        self._conn.row_factory = sqlite3.Row

        # Creo la tabla y el índice si no existen.
        self._conn.execute(self._CREATE_TABLE_SQL)
        self._conn.execute(self._CREATE_INDEX_SQL)
        
        # Intento la migración por si la BBDD es antigua (si falla porque ya existe la columna, no pasa nada).
        try:
            self._conn.execute(self._MIGRATE_SQL)
        except sqlite3.OperationalError:
            pass # La columna ya existía

        self._conn.commit()

        logger.debug(f"🔹  Base de datos SQLite abierta en: {db_path}")


    def get_by_hash(self, ed2k_hash: str) -> Optional[dict]:
        """
        Busco un archivo en la caché por su hash ED2K.

        Args:
            ed2k_hash: Hash ED2K en formato hexadecimal (32 caracteres).

        Returns:
            Diccionario con los datos del registro si existe, None si no está en caché.
        """

        cursor = self._conn.execute(
            "SELECT * FROM hashes WHERE ed2k_hash = ?",
            (ed2k_hash,)
        )
        row = cursor.fetchone()

        # Convierto el sqlite3.Row a un diccionario ordinario para que sea más cómodo de usar.
        return dict(row) if row else None


    def get_by_metadata(self, file_path: Path, file_size: int, file_mtime: float) -> Optional[dict]:
        """
        Busco un archivo en la caché por sus metadatos (ruta + tamaño + fecha modificación).

        Esto permite saltarse el cálculo del hash (que es lento) si el archivo no ha cambiado.

        Args:
            file_path: Ruta completa.
            file_size: Tamaño en bytes.
            file_mtime: Timestamp de última modificación.

        Returns:
            Registro de la BBDD si hay coincidencia exacta, None en caso contrario.
        """

        cursor = self._conn.execute(
            "SELECT * FROM hashes WHERE file_path = ? AND file_size = ? AND file_mtime = ?",
            (str(file_path), file_size, file_mtime)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


    def save(
        self,
        file_path: Path,
        file_size: int,
        file_mtime: float,
        ed2k_hash: str,
        ed2k_link: str,
    ) -> None:
        """
        Guardo un nuevo registro de archivo procesado en la caché (BBDD).

        Uso 'INSERT OR REPLACE' para que si el hash ya existe (por ejemplo, si el mismo
        archivo se procesa dos veces), se borre el antiguo y se guarde el nuevo con los
        metadatos actualizados (mtime).

        Args:
            file_path: Ruta completa al archivo procesado.
            file_size: Tamaño del archivo en bytes.
            file_mtime: Timestamp de última modificación.
            ed2k_hash: Hash ED2K en formato hexadecimal.
            ed2k_link: Enlace ed2k:// generado para el archivo.
        """

        # Uso ISO 8601 con zona horaria UTC para el timestamp.
        processed_at = datetime.now(timezone.utc).isoformat()

        self._conn.execute(
            """
            INSERT OR REPLACE INTO hashes
                (file_path, file_name, file_size, file_mtime, ed2k_hash, ed2k_link, processed_at)
            VALUES
                (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(file_path),
                file_path.name,
                file_size,
                file_mtime,
                ed2k_hash,
                ed2k_link,
                processed_at,
            )
        )
        self._conn.commit()

        logger.debug(f"🔹  Hash guardado en caché: {ed2k_hash} ({file_path.name})")


    def close(self) -> None:
        """
        Cierro la conexión a la base de datos (BBDD) SQLite limpiamente.
        Llamo a esto durante el shutdown de SmartMule.
        """

        self._conn.close()
        logger.debug("🔹  Conexión a la BBDD SQLite cerrada.")
