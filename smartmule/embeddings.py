"""
Motor de Búsqueda Semántica (Vectorial) de SmartMule.

Optimizado para el sistema de caché (caching) de SmartMule, este módulo genera embeddings de alto rendimiento 
utilizando FastEmbed (ONNX Runtime) y calcula la Similitud del Coseno en milisegundos contra la BBDD SQLite. 
Está diseñado para Lazy Loading con el objetivo de no comprometer el rendimiento de arranque del daemon SmartMule.

Su principal fortaleza reside en la capacidad de generar embeddings de alta calidad (de 384 dimensiones)
con un tamaño reducido (~1.5KB por vector), optimizando el uso del espacio en la caché de la BBDD.
Como cada archivo tiene su propio vector, para 5000 archivos solo ocuparían alrededor de 7.5MB de almacenamiento en la BBDD.

Dependencias opcionales: fastembed, numpy
"""

import logging
from typing import Optional, List, Dict, Any

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from smartmule import config

# Configuración del logger para el motor de embeddings
logger = logging.getLogger("SmartMule.embeddings")

# --- MODELO SINGLETON (LAZY LOADED) ---
# Evitamos cargar el modelo en el arranque global para ahorrar memoria y tiempo.
# El modelo se instancia solo la primera vez que se solicita una vectorización.
_model = None
_model_name = None

# Modelo de Re-ranking (Cross-Encoder)
_rerank_model = None
_rerank_model_name = None

def is_available() -> bool:

    """
    Comprueba si las dependencias de búsqueda semántica están instaladas en el sistema.
    Esto permite que SmartMule degrade silenciosamente a búsqueda FTS5 si no hay IA disponible.
    """

    try:
        import fastembed  # noqa: F401
        return _HAS_NUMPY
    except ImportError:
        return False


def _load_model(model_name: str):

    """
    Carga el modelo de embeddings de forma perezosa (Lazy Loading).
    Solo se ejecuta una vez por sesión O si cambia el nombre del modelo.
    """

    global _model, _model_name
    
    # Si el modelo no está cargado o queremos usar uno diferente
    if _model is None or _model_name != model_name:
        from fastembed import TextEmbedding
        logger.info(f"[AI] Cargando modelo de embeddings: {model_name}...")
        
        # Inicializamos el motor de FastEmbed (usa ONNX Runtime internamente):

        # Silenciamos advertencias de pooling de FastEmbed para mantener la consola limpia
        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning, message=".*mean pooling.*")
            _model = TextEmbedding(model_name=model_name)

        _model_name = model_name
        
        logger.info("[OK] Modelo cargado (384 dims, ONNX)")
        
    return _model


def encode_text(text: str, model_name: str) -> bytes:

    """
    Vectoriza una cadena de texto y la serializa como un BLOB binario (float32).
    
    Args:
        text: El texto a vectorizar (título, sinopsis, etc.)
        model_name: El identificador del modelo a usar.
        
    Returns:
        bytes: El vector serializado listo para guardarse en un campo BLOB de SQLite.
    """

    # Cargamos el modelo (si no lo estaba) y generamos el embedding
    model = _load_model(model_name)
    
    # FastEmbed devuelve un generador (un objeto que produce los resultados en una lista real)
    # Extraemos el primer (y único) vector de la lista generada con '[0]'
    vector = list(model.embed([text]))[0]

    # NumPy trabaja en 64 bits (float64) por defecto. Convertimos a 32 bits (float32) para ahorrar el 50% de espacio en disco.
    # tobytes() convierte el array de NumPy a bytes para guardarlo en un campo BLOB de SQLite.
    # En este punto, 'vector' es un array de 384 dimensiones.
    return vector.astype(np.float32).tobytes()


def decode_blob(blob: bytes) -> 'np.ndarray':

    """
    Deserializa un BLOB binario proveniente de la BBDD a un vector de NumPy.
    """

    # np.frombuffer convierte un buffer binario a un array de NumPy en memoria (en float32), sin copiar datos.
    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity_batch(vectors, query):

    """
    Calcula la similitud de coseno entre una consulta y todos los vectores de la BBDD de forma masiva.
    Utiliza operaciones vectorizadas de NumPy (@ -> Producto Matricial) para máxima velocidad.
    
    Args:
        vectors: Lista de BLOBS (bytes) o Matriz NumPy (N, dim).
        query: Vector de la consulta (NumPy array).
        
    Returns:
        np.ndarray: Array con los scores de similitud.

    Nota Técnica: 
    Tiempo algorítmico: O(n), donde n=nº de dimensiones de los vectores (384).

    La similitud del coseno mide el ángulo entre dos vectores. En términos de embeddings, 
    esto significa que cuanto más similares sean dos textos, más cerca estarán sus vectores.
    
    Como los vectores de FastEmbed vienen ya normalizados (L2), el Producto Punto (@ en NumPy) 
    es matemáticamente equivalente a la Similitud del Coseno, pero mucho más rápido 
    de calcular al evitar raíces cuadradas y divisiones en cada comparación.
    """
    
    # SI detecta una lista vacía de vectores, devuelve una lista vacía
    if len(vectors) == 0:
        return []
    
    # 1. Normalización de entrada
    # Si recibimos una lista de BLOBS (bytes), los decodificamos y apilamos en una matriz NumPy

    # SI detecta una lista de Bytes Y esta no está vacía Y el primer elemento es un BLOB (Bytes)
    if isinstance(vectors, list) and len(vectors) > 0 and isinstance(vectors[0], bytes):
        # Convierte la lista de BLOBS a una matriz NumPy (N, 384)
        matrix = np.stack([decode_blob(b) for b in vectors])

    else:
        # Si ya recibimos una matriz NumPy (N, 384) desde database.py (CONFIGURACIÓN ACTUAL)
        matrix = vectors # Asignamos directamente la matriz NumPy


    # 2. Cálculo de Similitud del Coseno
    
    # Por si el modelo subyacente no los normaliza por defecto, 
    # forzamos la normalización L2 de forma manual tanto de la matriz (la BBDD) como del vector de búsqueda (la query). 
    # La similitud del coseno es el producto punto de vectores normalizados.
    
    # Normalizamos la consulta (query)
    query_norm = np.linalg.norm(query)

    if query_norm > 0:
        query = query / query_norm
        
    # Normalizamos la matriz de la base de datos
    matrix_norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    # Evitamos división por cero
    matrix_norms[matrix_norms == 0] = 1e-9
    matrix = matrix / matrix_norms

    # Ahora sí, el producto matricial es estrictamente la similitud del coseno [-1, 1]
    # '@' es el operador del Producto Matricial en NumPy. Multiplica cada fila de 'matrix' por el vector 'query'.
    scores = matrix @ query
    
    return scores


def get_model_info() -> Dict[str, Any]:

    """
    Intenta obtener información técnica sobre el modelo configurado (cuantización, dimensiones, etc.),
    inspeccionando la lista de modelos soportados por FastEmbed.
    """

    info = {
        "model": config.EMBEDDING_MODEL,
        "quantization": config.EMBEDDING_QUANTIZATION,
        "dim": "Unknown",
        "is_quantized": False
    }

    if not is_available():
        return info

    try:
        from fastembed import TextEmbedding
        supported_models = TextEmbedding.list_supported_models()
        
        # Buscamos el modelo en la lista de soportados
        for m in supported_models:
            if m["model"] == config.EMBEDDING_MODEL:
                info["dim"] = m.get("dim", "Unknown")
                
                # Si el usuario dejó 'Default', intentamos adivinar por el archivo o el nombre
                if info["quantization"].lower() == "default":
                    model_file = m.get("model_file", "").lower()
                    hf_source = m.get("sources", {}).get("hf", "").lower()
                    
                    if "quantized" in model_file or "-q" in hf_source or "optimized" in model_file:
                        info["quantization"] = "int8 (Auto)"
                        info["is_quantized"] = True
                    else:
                        info["quantization"] = "float32 (Auto)"
                break
    except Exception:
        pass
    
    return info

def build_metadata_text(record: dict) -> str:

    """
    Construye una cadena de texto rica a partir de los metadatos de un archivo.
    Este texto es el que se enviará al modelo para generar su "huella semántica".
    """

    parts = []
    
    # 1. Nombre de archivo original (Prioridad Máxima)
    if record.get("file_name"):
        parts.append(f"Archivo: {record['file_name']}")

    # 2. Tipo de contenido (ej: "Película", "Serie", "Música")
    m_type = record.get("media_type", "").capitalize()

    if m_type and m_type != "Unknown":
        parts.append(m_type)

    # 3. Título oficial
    if record.get("official_title"):
        parts.append(record["official_title"])
        
    # 4. Año de lanzamiento
    if record.get("release_date"):

        # (Extraemos solo el año para no confundir al modelo con días/meses irrelevantes)
        year = record["release_date"][:4] if len(record["release_date"]) >= 4 else ""

        if year:
            parts.append(f"({year})")

    # 5. Autor / Director / Artista
    if record.get("author"):
        parts.append(f"de {record['author']}")
    
    if record.get("director") and record.get("director") != record.get("author"):
        parts.append(f"Dirigida por {record['director']}")

    # 6. Géneros
    if record.get("genres"):
        parts.append(record["genres"])

    # 7. Idiomas
    if record.get("languages"):
        parts.append(f"Idiomas: {record['languages']}")
        
    # 8. Resolución (ej: "1080p")
    if record.get("resolution"):
        parts.append(record["resolution"])
        
    # 9. Puntuación (Convertimos valor numérico a concepto semántico)
    score = record.get("score", 0)

    if score:
        try:
            score_val = float(score)

            if score_val >= 9.0:
                parts.append("Obra maestra, excelente puntuación")
            elif score_val >= 8.0:
                parts.append("Gran calidad, muy buena puntuación")
            elif score_val >= 7.0:
                parts.append("Buena puntuación, interesante")
            elif 0 < score_val <= 4.0:
                parts.append("Baja puntuación, mediocre o decepcionante, mala")

        except (ValueError, TypeError):
            pass

    # 10. Sinopsis/Descripción (Español)
    if record.get("overview"):
        parts.append(record["overview"])

    # 11. Sinopsis/Descripción (Inglés) - Solo si existe Y es diferente a la de español (para evitar redundancia en el embedding)
    if record.get("overview_en") and record.get("overview_en") != record.get("overview"):
        parts.append(record["overview_en"])
    
    # Si hay metadatos, los unimos con puntos para separar conceptos
    return ". ".join(parts) if parts else record.get("file_name", "")


def _load_rerank_model(model_name: str):

    """Carga el modelo de re-ranking de forma Lazy Loading (ONNX Runtime)."""
    global _rerank_model, _rerank_model_name
    
    # Si el modelo no está cargado o es diferente al configurado, lo cargo
    if _rerank_model is None or _rerank_model_name != model_name:

        from fastembed.rerank.cross_encoder import TextCrossEncoder

        logger.info(f"[AI] Cargando modelo de re-ranking: {model_name}...")

        # Instanciamos el Cross-Encoder (lo que usará la IA de nivel superior)
        _rerank_model = TextCrossEncoder(model_name=model_name)
        # y guardamos el nombre del modelo para futuras comparaciones
        _rerank_model_name = model_name

        logger.info("[OK] Modelo de Re-ranking cargado (ONNX)")
        
    return _rerank_model


def rerank_results(query: str, results: List[Dict[str, Any]], model_name: str = None) -> List[Dict[str, Any]]:

    """
    Refina los resultados de la búsqueda usando un Cross-Encoder para mayor precisión.
    
    Este Cross-Encoder analiza (query, documento) simultáneamente, lo que es mucho más
    preciso que comparar vectores por separado (Bi-Encoder), aunque más costoso.
    """

    if not results or not is_available():
        return results
        
    if model_name is None:
        from smartmule.config import CROSS_ENCODER_MODEL
        model_name = CROSS_ENCODER_MODEL

    # Cargamos el motor de re-ranking -> El que usará el Cross-Encoder
    reranker = _load_rerank_model(model_name)
    
    # 1. Preparamos los textos de los documentos
    # Usamos el metadata_text si existe (ya está pre-calculado en la caché)
    passages = []

    for r in results:
        # Re-construimos el texto dinámicamente para asegurar que el orden de los campos 
        # (ej: nombre de archivo primero) sea el óptimo para el modelo de re-ranking actual.
        text = build_metadata_text(r)
        passages.append(text)
        
    # 2. Ejecutamos la inferencia (ONNX Runtime -> Reranking)
    # rerank() devuelve un iterador de scores
    scores = list(reranker.rerank(query, passages))
    
    # 3. Aplicamos los nuevos scores a los registros
    for i, score in enumerate(scores):

        # Actualizamos el score de relevancia
        results[i]['rerank_score'] = float(score)

        # Marcamos que este resultado ha sido "verificado" por el Cross-Encoder.
        results[i]['is_reranked'] = True

    # 4. Re-ordenamos basándonos en el score del Cross-Encoder

    # Los scores suelen estar en un rango logit (negativos y positivos). Cuanto mayor, mejor.
    results.sort(key=lambda x: x['rerank_score'], reverse=True)
    
    return results
