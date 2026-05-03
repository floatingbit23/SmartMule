"""
Motor de Persistencia y Motor de Metadatos de SmartMule.

Gestiono el almacenamiento centralizado en SQLite (v3.46+) para garantizar la integridad y el 
enriquecimiento de la biblioteca multimedia.

Este módulo es el "cerebro" que permite:
1. Optimización P2P: Evitar el recalculo de hashes ED2K/SHA256 y prevenir duplicidad de archivos.

2. Enriquecimiento Semántico: Almacenar metadatos avanzados (Autores, Títulos, Resoluciones) obtenidos mediante el análisis híbrido (Regex + LLM + APIs externas).

3. Triage de Seguridad: Persistir veredictos de seguridad y enlaces de informes de VirusTotal.

4. Motor de Búsqueda: Servir como base para el sistema de búsqueda global avanzada (FTS5).
    Cascada de búsqueda: FTS5 (rápido) → REGEXP (rápido) → Distancia de Levenshtein (lento, pero resuelve typos)

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
            is_organized INTEGER DEFAULT 0, -- Por defecto: no organizado=0, organizado=1 
            duration INTEGER DEFAULT 0 -- Duración en segundos (extraída por FFmpeg)
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


    # --- MOTOR DE BÚSQUEDA INTELIGENTE FTS5 (Full-Text Search 5) ---

    # Tabla Virtual FTS5 (Búsqueda Inteligente)

    # Usamos contenido externo ('files') para no duplicar datos y el tokenizer unicode61 con eliminación de diacríticos.
    _CREATE_FTS_TABLE_SQL = """
        CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
            file_name,
            official_title,
            author,
            languages,
            content='files',
            content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        );
    """

    # Triggers para sincronización automática en tiempo real
    _CREATE_TRIGGER_AI_SQL = """
        CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
          INSERT INTO files_fts(rowid, file_name, official_title, author, languages) 
          VALUES (new.id, new.file_name, new.official_title, new.author, new.languages);
        END;
    """

    _CREATE_TRIGGER_AD_SQL = """
        CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
          INSERT INTO files_fts(files_fts, rowid, file_name, official_title, author, languages) 
          VALUES('delete', old.id, old.file_name, old.official_title, old.author, old.languages);
        END;
    """

    _CREATE_TRIGGER_AU_SQL = """
        CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
          INSERT INTO files_fts(files_fts, rowid, file_name, official_title, author, languages) 
          VALUES('delete', old.id, old.file_name, old.official_title, old.author, old.languages);
          INSERT INTO files_fts(rowid, file_name, official_title, author, languages) 
          VALUES (new.id, new.file_name, new.official_title, new.author, new.languages);
        END;
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
        "ALTER TABLE files ADD COLUMN is_organized INTEGER DEFAULT 0;",
        "ALTER TABLE files ADD COLUMN duration INTEGER DEFAULT 0;"
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

        # Habilitamos el modo WAL (Write-Ahead Logging) para mejorar la concurrencia.
        # Esto permite que el Watcher y el Worker operen simultáneamente sin bloqueos 'database is locked'.
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")

        # Devuelvo filas personalizadas que se comportan como diccionarios. Esto facilita el acceso por nombre de columna
        self._conn.row_factory = sqlite3.Row

        # Habilito funciones personalizadas para el motor de búsqueda
        self._conn.create_function("REGEXP", 2, self._regexp_worker) # REGEX
        self._conn.create_function("levenshtein", 2, self._levenshtein_distance) # FUZZY SEARCH (ÚLTIMO RECURSO)
        self._conn.create_function("stem", 1, lambda x: Path(x).stem if x else "") # Eliminar extensiones


        # 1º. Creo las tablas si no existen.
        self._conn.execute(self._CREATE_TABLE_SQL)
        self._conn.execute(self._CREATE_CACHE_TABLE_SQL)
        

        # 2º. MIGRACIONES: Aseguro que las columnas necesarias existan antes de indexar

        for sql in self._MIGRATIONS: # Lista de sentencias SQL de migración
            try:
                self._conn.execute(sql) # Ejecuto la sentencia SQL
            except sqlite3.OperationalError: 
                pass # Si hay error, lo ignoro (la columna ya existía)


        # 3º. ÍNDICES Y BÚSQUEDA: Ahora que las columnas existen seguro, creamos la infraestructura FTS5.
        self._conn.execute(self._CREATE_INDEX_SQL)
        
        # Infraestructura de búsqueda inteligente (FTS5 + Triggers)
        self._conn.execute(self._CREATE_FTS_TABLE_SQL)
        self._conn.execute(self._CREATE_TRIGGER_AI_SQL)
        self._conn.execute(self._CREATE_TRIGGER_AD_SQL)
        self._conn.execute(self._CREATE_TRIGGER_AU_SQL)


        # 4º. POBLADO INICIAL (MIGRACIÓN): Sincroniza archivos preexistentes con el índice FTS5.
        # Esto solo ocurre la primera vez que se activa FTS5 en una base de datos antigua.
        cursor = self._conn.execute("SELECT COUNT(*) FROM files_fts")

        if cursor.fetchone()[0] == 0:

            self._conn.execute("""
                INSERT INTO files_fts(rowid, file_name, official_title, author, languages)
                SELECT id, file_name, official_title, author, languages FROM files
            """)

            self._conn.commit()

            logger.info("[i]  Índice FTS5 poblado con registros existentes.")


        # 5º. Confirmo los cambios en la BBDD.
        self._conn.commit()

        logger.debug(f"[*]  Base de datos SQLite abierta en: {db_path}")


    def _regexp_worker(self, expr: str, item: str) -> bool:

        """
        Función auxiliar que ejecuta la lógica de búsqueda regex.
        SQLite la llama por cada fila evaluada en 'WHERE column REGEXP ?'.
        """

        if not item:
            return False
        try:
            return re.search(expr, item, re.IGNORECASE) is not None
        except Exception:
            return False

    # FALLBACK A FUZZY SEARCH

    def _levenshtein_distance(self, s1: str, s2: str) -> int:

        """
        Algoritmo iterativo para calcular la distancia de edición (Levenshtein).
        Se usa como métrica para la búsqueda difusa (fuzzy search).

        Ejemplo: "Michael" vs "Mikael" -> Distancia 2 (Sustituir 'c' por 'k' + Eliminar 'h').
        
        IMPORTANTE!! -> Si la distancia es <= 2, SmartMule suele considerarlos coincidencia válida.

        Pasos del algoritmo (basado en el ejemplo):
        1. Inicializar fila anterior: [0, 1, 2, 3, 4, 5, 6] (coste de borrar "mikael").
        2. Iterar sobre s1 ("michael") letra a letra.
        3. Para cada celda, calcular tres caminos y elegir el MÍNIMO:
            - Coincidencia (Coste +0) o Sustitución (Coste +1).
            - Inserción (Coste +1).
            - Eliminación (Coste +1).
        4. Las coincidencias ('m', 'i', 'a', 'e', 'l') mantienen el coste bajo.
        5. Los "conflictos" ('c' vs 'k' y la 'h' extra) suben el marcador.
        6. El resultado final (2) es el acumulado de operaciones mínimas.
        """
        
        # CASO BASE: Si alguna cadena está vacía, devolvemos la longitud de la otra.
        if not s1 or not s2:
            return len(s1 or s2 or "")
        
        # PRE-PROCESAMIENTO: Case-insensitive
        s1, s2 = s1.lower(), s2.lower()
        
        # Optimización: s2 siempre debe ser la cadena más corta para reducir espacio
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)

        # Inicializamos la "fila anterior" [0, 1, 2, ..., n]
        previous_row = range(len(s2) + 1)

        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                # Costes de las tres operaciones posibles
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                
                current_row.append(min(insertions, deletions, substitutions))

            previous_row = current_row
        
        return previous_row[-1]


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


    # --- MOTOR DE BÚSQUEDA INTELIGENTE ---
    
    def _sanitize_fts_query(self, raw_query: str) -> str:
        """
        Convierte un término de búsqueda libre en una consulta FTS5 segura.
        Envuelve cada token entre comillas dobles para evitar que FTS5
        interprete operadores no intencionados (guiones, puntos, paréntesis).
        """
        # Dividimos por espacios y envolvemos cada fragmento entre comillas
        tokens = raw_query.split()
        
        # Cada token se escapa individualmente: "The" "Matrix" "1999"
        safe_tokens = [f'"{t}"' for t in tokens if t.strip()]
        
        if not safe_tokens:
            return '""'
        
        return " ".join(safe_tokens)


    def _parse_filtered_query(self, raw_query: str) -> tuple[str, list, list]:
        """
        Separa una consulta mixta en texto libre + filtros SQL con lógica avanzada.
        Soporta multi-valor (OR para el mismo campo), búsquedas parciales y fechas.

        Ejemplo: "type:movie type:tv score>7.5 res:1080p verdict:safe added:today organized:y" ->
        "Busca películas O series que tengan una puntuación mayor a 7.5, sean de resolución 1080p, tengan un veredicto seguro, hayan sido añadidas hoy y estén organizadas."
        """
        grouped_raw = {} # { "col": [ (op, val, is_raw), ... ] }
        remaining = raw_query
        
        # 1. Definición de patrones y handlers
        def organized_handler(m):
            val = m.group(1).lower()
            # Si el usuario escribe 'organized:yes/y/true/t/1', se traduce a 'is_organized = 1' (True)
            # Si el usuario escribe 'organized:no/n/false/f/0', se traduce a 'is_organized = 0' (False)
            return ("is_organized", "= ?", 1 if val in ["yes", "y", "1", "true", "t"] else 0, False)

        # Handler para fechas: 'added:today' o 'added:Nd' (Nd = N días)
        def date_handler(m):

            val = m.group(1).lower()

            if val == "today":
                return ("processed_at", ">=", "date('now', 'localtime')", True)

            elif val.endswith("d"):
                days = val[:-1]
                return ("processed_at", ">=", f"date('now', '-{days} days', 'localtime')", True)
                
            return (None, None, None, None)

        # Handler para veredictos: 'verdict:safe' incluye multimedia por defecto
        def verdict_handler(m):
            val = m.group(1).lower()
            if val == "safe":
                # Lógica: (f.security_verdict = 'SAFE' OR (f.security_verdict = '' AND f.media_type IN ('movie', 'series', 'video', 'audio', 'image', 'book', 'document')))
                return ("security_verdict", "= 'SAFE' OR (f.security_verdict = '' AND f.media_type IN ('movie', 'series', 'video', 'audio', 'image', 'book', 'document'))", "", True)
            return ("security_verdict", "LIKE ?", f"{val.upper()}%", False)

        filter_patterns = {
            r"type:(\S+)":       lambda m: ("media_type", "LIKE ?", f"{m.group(1).lower()}%", False),
            r"score([><=]+)([\d.]+)": lambda m: ("score", f"{m.group(1)} ?", float(m.group(2)), False),
            r"verdict:(\S+)":    verdict_handler,
            r"res:(\S+)":        lambda m: ("resolution", "LIKE ?", f"{m.group(1)}%", False),
            r"organized:(\S+)":  organized_handler,
            r"added:(\d+d|today)": date_handler,
        }
        
        # 2. Extracción de filtros
        for pattern, handler in filter_patterns.items():

            # Buscamos todas las ocurrencias del patrón
            matches = list(re.finditer(pattern, remaining, re.IGNORECASE))

            # Itera sobre todos los matches encontrados
            for match in matches:

                try:
                    col, op, val, is_raw = handler(match)
                    
                    if col:
                        if col not in grouped_raw: grouped_raw[col] = []
                        grouped_raw[col].append((op, val, is_raw))

                except Exception as e:
                    logger.debug(f"[i] Error parseando filtro '{match.group(0)}': {e}")

            remaining = re.sub(pattern, '', remaining, flags=re.IGNORECASE)

        # 3. Construcción de cláusulas SQL agrupadas por campo (OR interno, AND externo)
        conditions = []
        params = []
        
        for col, items in grouped_raw.items():
            field_clauses = []
            for op, val, is_raw in items:
                if is_raw:
                    field_clauses.append(f"f.{col} {op} {val}")
                else:
                    field_clauses.append(f"f.{col} {op}")
                    params.append(val)
            
            # Unimos los valores del mismo campo con OR
            if field_clauses:
                conditions.append("(" + " OR ".join(field_clauses) + ")")
        
        text_query = remaining.strip()

        return text_query, conditions, params


    def search_by_name(self, query: str) -> list[dict]:
        """
        Motor de búsqueda híbrido avanzado con soporte para filtros agrupados.
        """

        # Si no hay query, devolvemos todo (--purge sin argumentos)
        if not query:
            return self.get_all_files()

        # --- 1. PARSE DE FILTROS ---
        text_query, filter_conditions, filter_params = self._parse_filtered_query(query)

        # Base de la consulta
        sql_base = "SELECT f.* FROM files f"
        where_clauses = []
        all_params = []

        # Si hay texto, usamos FTS5 (MATCH contra la tabla virtual)
        if text_query:
            sql_base += " JOIN files_fts fts ON f.id = fts.rowid"
            where_clauses.append("files_fts MATCH ?")
            all_params.append(self._sanitize_fts_query(text_query))

        # Añadimos los filtros agrupados
        for cond in filter_conditions:
            where_clauses.append(cond)
        all_params.extend(filter_params)

        try:
            sql = sql_base
            if where_clauses:
                sql += " WHERE " + " AND ".join(where_clauses)
            
            sql += " ORDER BY f.processed_at DESC"
            
            cursor = self._conn.execute(sql, tuple(all_params))
            results = [dict(row) for row in cursor.fetchall()]
            
            # Si no hay resultados FTS5 y hay texto, intentamos fallbacks
            if not results and text_query:
                # 1. Fallback a Regex (si no hay filtros puros)
                if not filter_conditions:
                    results = self._search_by_regexp(text_query)
                
                # 2. Si sigue sin haber resultados, intentamos Fuzzy (último recurso)
                if not results and len(text_query) > 3 and "*" not in text_query:
                    results = self._search_fuzzy(text_query, filter_conditions, filter_params)
                    if results:
                        logger.info(f"[!] Resultados difusos encontrados para '{text_query}'")

            return results

        except Exception as e:
            logger.error(f"[ERR] Error en búsqueda: {e}")
            return []


    def _search_by_regexp(self, query: str, filter_conditions: list = None, filter_params: list = None) -> list[dict]:
        
        """
        Fallback basado en expresiones regulares para soportar wildcards (* y ?) y regex avanzados.
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
            
            # Si el patrón no empieza por wildcard, anclamos al principio
            if not query.startswith("*") and not regex_pattern.startswith("^"):
                regex_pattern = "^" + regex_pattern
        
        # SQL con el operador REGEXP y soporte para filtros
        sql = """
            SELECT * FROM files 
            WHERE (file_name REGEXP ? OR official_title REGEXP ?)
        """
        all_params = [regex_pattern, regex_pattern]

        if filter_conditions:
            for cond in filter_conditions:
                sql += f" AND {cond}"
            all_params.extend(filter_params)
            
        sql += " ORDER BY processed_at DESC"
        
        try:
            cursor = self._conn.execute(sql, tuple(all_params))
            return [dict(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"[ERR]  Error en búsqueda Regex/Wildcard con filtros '{query}': {e}")
            return []


    def _search_fuzzy(self, query: str, filter_conditions: list = None, filter_params: list = None, max_distance: int = 2) -> list[dict]:
       
        """
        Búsqueda difusa como último recurso contra errores tipográficos (typos).
        Calcula la distancia de Levenshtein entre el query y los títulos.

        La función levenshtein(a, b) calcula cuántas letras necesitas cambiar, añadir o borrar para transformar "a" en "b".
        La función stem() elimina la extensión del archivo para tratar "matrix.mkv" como "matrix".
        """

        # SQL que calcula la distancia de Levenshtein mínima entre el nombre de archivo (sin extensión) y el título oficial
        # Filtrado por longitud de cadena: solo evaluamos registros cuyo nombre sea de tamaño similar (+/- 3 caracteres).
        min_len = max(0, len(query) - 3)
        max_len = len(query) + 3

        """
        SQLite ejecutará la función Levenshtein en Python solo sobre los registros que tienen una longitud de nombre similar al término de búsqueda (margen de +/- 3 caracteres). 
        Esto convierte una búsqueda costosa de O(N) en una operación filtrada extremadamente rápida de O(filtrado), ideal para bibliotecas con miles de archivos.
        """

        sql = """
            SELECT *, 
                   MIN(levenshtein(stem(file_name), ?), levenshtein(official_title, ?)) as dist
            FROM files 
            WHERE (LENGTH(stem(file_name)) BETWEEN ? AND ? OR LENGTH(official_title) BETWEEN ? AND ?)
              AND MIN(levenshtein(stem(file_name), ?), levenshtein(official_title, ?)) <= ?
        """
        all_params = [query, query, min_len, max_len, min_len, max_len, query, query, max_distance]

        if filter_conditions:
            for cond in filter_conditions:
                sql += f" AND {cond}"
            all_params.extend(filter_params)
            
        sql += " ORDER BY dist ASC, processed_at DESC LIMIT 10"
        
        try:
            cursor = self._conn.execute(sql, tuple(all_params))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"[ERR]  Error en búsqueda difusa para '{query}': {e}")
            return []


    # Función para eliminar un registro por ID
    def delete_by_id(self, record_id: int) -> None:
        """
        Elimina un registro de la base de datos por su ID único.
        """
        self._conn.execute("DELETE FROM files WHERE id = ?", (record_id,))
        self._conn.commit()
        logger.debug(f"[*]  Registro {record_id} eliminado de la base de datos.")


    # Función para eliminar un registro y su caché por Hash ED2K
    def delete_by_ed2k(self, ed2k_hash: str) -> None:

        """
        Elimina un archivo de la tabla principal y de la caché de metadatos usando el hash completo.
        Esto fuerza a que el archivo sea re-identificado desde cero (vuelva a pasar el flujo REGEX -> IA -> API).
        """

        # 1. Borrar de la tabla principal 'files' usando el hash ED2K oficial
        self._conn.execute("DELETE FROM files WHERE ed2k_hash = ?", (ed2k_hash,))
        
        # 2. Borrar de la caché de metadatos (LLM/API)
        self._conn.execute("DELETE FROM metadata_cache WHERE ed2k_hash = ?", (ed2k_hash,))
        
        self._conn.commit()
        logger.debug(f"[*]  Registro y caché eliminados para hash: {ed2k_hash[:8]}...")


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

        # Duración (técnica)
        duration = metadata.get("technical", {}).get("duration_sec", 0)

        self._conn.execute(
            """
            UPDATE files
            SET official_title=?, release_date=?, author=?, score=?, media_type=?, 
                resolution=?, languages=?, subtitles=?, security_verdict=?, vt_url=?, final_path=?, is_organized=?, duration=?
            WHERE fingerprint=? AND file_size=?
            """,
            (official_title, release_date, author, score, media_type,
             resolution, languages, subtitles, security_verdict, vt_url, final_path, is_organized, duration, fingerprint, file_size)
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
