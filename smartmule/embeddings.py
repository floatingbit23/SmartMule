"""
Motor de Búsqueda Semántica (Vectorial) de SmartMule.

Optimizado para el sistema de caché (caching) de SmartMule, este módulo genera embeddings de alto rendimiento 
utilizando FastEmbed (ONNX Runtime) y calcula la similitud coseno en milisegundos contra la BBDD SQLite. 
Está diseñado para Lazy Loading con el objetivo de no comprometer el rendimiento de arranque del daemon SmartMule.

Su principal fortaleza reside en la capacidad de generar embeddings de alta calidad (de 384 dimensiones)
con un tamaño reducido (~1.5KB por vector), optimizando el uso del espacio en la caché de la BBDD.
Como cada archivo tiene su propio vector, para 5000 archivos solo ocuparían alrededor de 7.5MB de almacenamiento en la BBDD.

Dependencias opcionales: fastembed, numpy
"""

import logging
from typing import Optional, List, Dict, Any
import numpy as np

from smartmule import config

# Configuración del logger para el motor de embeddings
logger = logging.getLogger("SmartMule.embeddings")

# --- MODELO SINGLETON (LAZY LOADED) ---
# Evitamos cargar el modelo en el arranque global para ahorrar memoria y tiempo.
# El modelo se instancia solo la primera vez que se solicita una vectorización.
_model = None
_model_name = None

def is_available() -> bool:
    """
    Comprueba si las dependencias de búsqueda semántica están instaladas en el sistema.
    Esto permite que SmartMule degrade silenciosamente a búsqueda FTS5 si no hay IA disponible.
    """
    try:
        import fastembed  # noqa: F401
        import numpy  # noqa: F401
        return True
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
        
        # Inicializamos el motor de FastEmbed (usa ONNX Runtime internamente)
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
    
    # FastEmbed devuelve un generador, extraemos el primer vector
    vector = list(model.embed([text]))[0]
    
    # Convertimos a float32 para ahorrar el 50% de espacio (en comparación con formato por defecto; float64)
    return vector.astype(np.float32).tobytes()

def decode_blob(blob: bytes) -> 'np.ndarray':
    """
    Deserializa un BLOB binario proveniente de la BBDD a un vector de NumPy.
    """

    # np.frombuffer convierte un buffer binario a un array de NumPy en memoria, sin copiar datos.
    return np.frombuffer(blob, dtype=np.float32)

def cosine_similarity_batch(query_blob: bytes, db_blobs: list[bytes]) -> list[float]:
    """
    Calcula la Similitud del Coseno entre un query (consumido como un vector de búsqueda) y una lista de vectores de la BBDD.
    Utiliza operaciones vectorizadas de NumPy para máxima velocidad.
    """
    
    # Deserializamos el vector de búsqueda
    query = decode_blob(query_blob)
    
    # Si la lista de vectores está vacía, devolvemos una lista vacía
    if not db_blobs:
        return []
    
    # Reconstruimos la matriz de todos los vectores de la biblioteca
    matrix = np.stack([decode_blob(b) for b in db_blobs])
    
    # Como los vectores de FastEmbed vienen ya normalizados, el Producto Punto es equivalente a la Similitud Coseno, 
    # pero mucho más rápido de calcular (@ -> Producto Punto en NumPy)
    scores = matrix @ query

    """
    Tiempo algorítmico: O(n), donde n=dimensión de los vectores (384)

    SIMILITUD DEL COSENO:

    La similitud del coseno (A · B / |A| |B|) mide el coseno del ángulo entre dos vectores. 
        Si los vectores apuntan en la misma dirección, el ángulo es 0 y el coseno es 1. 
        Si apuntan en direcciones opuestas, el ángulo es 180 grados y el coseno es -1. 
        Si son ortogonales (perpendiculares), el ángulo es 90 grados y el coseno es 0.
    
    En términos de embeddings, esto significa que cuanto más similares sean dos textos, 
    más cerca estarán sus vectores en el espacio vectorial, y mayor será su similitud del coseno.

    PRODUCTO PUNTO:
    El producto punto (A · B) es más rápido de calcular que la similitud del coseno. 
    Son equivalentes pero SOLO cuando los vectores están normalizados (su magnitud es 1).

    Calcular un Producto Punto es solo hacer multiplicaciones y sumas. 
    Calcular el coseno real obligaría al procesador a calcular raíces cuadradas (para las normas) 
    y divisiones en cada comparación, lo cual es mucho más lento.

    Como los vectores de FastEmbed vienen normalizados, en nuestro caso es preferible usar el Producto Punto.
    """
    
    return scores.tolist()

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
    
    # Añadimos piezas de información si están disponibles

    # 1. Tipo de contenido (ej: "Película", "Serie", "Música")
    m_type = record.get("media_type", "").capitalize()

    if m_type and m_type != "Unknown":
        parts.append(m_type)

    # 2. Título oficial
    if record.get("official_title"):
        parts.append(record["official_title"])
        
    # 3. Año de lanzamiento
    if record.get("release_date"):

        # (Extraemos solo el año para no confundir al modelo con días/meses irrelevantes)
        year = record["release_date"][:4] if len(record["release_date"]) >= 4 else ""

        if year:
            parts.append(f"({year})")

    # 4. Autor / Director
    if record.get("author"):
        parts.append(f"de {record['author']}")

    # 5. Géneros
    if record.get("genres"):
        parts.append(record["genres"])

    # 6. Idiomas
    if record.get("languages"):
        parts.append(f"Idiomas: {record['languages']}")
        
    # 7. Resolución (ej: "1080p")
    if record.get("resolution"):
        parts.append(record["resolution"])
        
    # 8. Puntuación (Convertimos valor numérico a concepto semántico)
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

    # 9. Sinopsis/Descripción (Español)
    if record.get("overview"):
        parts.append(record["overview"])

    # 10. Sinopsis/Descripción (Inglés) - Solo si existe Y es diferente a la de español (para evitar redundancia en el embedding)
    if record.get("overview_en") and record.get("overview_en") != record.get("overview"):
        parts.append(record["overview_en"])
    
    # 11. Nombre de archivo original (como red de seguridad para etiquetas técnicas/grupos)
    if record.get("file_name"):
        parts.append(f"Archivo: {record['file_name']}")
    
    # Si hay metadatos, los unimos con puntos para separar conceptos
    return ". ".join(parts) if parts else record.get("file_name", "")
