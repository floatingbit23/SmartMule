import os
import json
import logging
from google import genai
import openai
import time

from smartmule.config import GEMINI_API_KEY, USE_LOCAL_LLM, LMSTUDIO_API_KEY, LOCAL_LLM_URL

logger = logging.getLogger("SmartMule.parsers.llm")

# Silenciamos los logs ruidosos de la librería de Google (AFC is enabled...)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)

# System Prompt base, enfocado en estructuración dura sin inventarse datos

SYSTEM_PROMPT = """Eres un experto en extracción de metadatos de cine y literatura. 
Tu tarea es analizar el nombre "sucio" de un archivo descargado de redes P2P y extraer su metadata estructurada en JSON puro.

Reglas prioritarias:
1. Identifica el Título Real: Si hay traducciones (ej: 'L'Ultima Missione'), sepáralas y devuelve preferiblemente el título original o internacional (ej: 'Project Hail Mary') en el campo "title".
2. Limpieza Radical: Elimina cualquier rastro de calidad (720p, 1080p), idiomas (ITA, AAC, Spanish, Castellano), o grupos de ripeo/etiquetas de escena (KVM, mDudikoff, WEB-DL, x264, x265, HEVC).
3. Formato de Salida: Devuelve exclusivamente el Título Limpio y el Año por separado. No inventes datos si no los conoces.

Reglas técnicas y de estructura:
4. Elimina etiquetas de edición (Remastered, Director's Cut, Extended, Uncut) que NO son parte del título.
5. Identifica correctamente la calidad ("quality") si está presente.
6. Detecta "season" y "episode" si es una serie (números enteros).
7. "media_type" debe ser exactamente uno de: "video", "series", "movie", "book", "audio", "software", "games", "documents", "image", "subtitles", o "unknown".
8. Proporciona el "original_title" si el título principal es una traducción.
9. Devuelve UNICAMENTE un bloque JSON válido, sin delimitadores de markdown. No agregues texto adicional.

Ejemplo 1: "The.Office.S03E05.1080p.HEVC.x265.mkv"
{"title": "The Office", "author": null, "original_title": null, "media_type": "series", "season": 3, "episode": 5, "quality": "1080p", "year": 2005}

Ejemplo 2: "L.Ultima.Missione - Project.Hail.Mary.2026.KVM.mkv"
{"title": "Project Hail Mary", "author": null, "original_title": "Project Hail Mary", "media_type": "movie", "season": null, "episode": null, "quality": "WEB-DL", "year": 2026}
"""

# Función principal que recibe el nombre y opcionalmente contexto técnico de Regex
def parse_with_llm(filename: str, context: dict = None) -> dict:

    """
    Intenta limpiar y extraer toda la información del archivo usando Inteligencia Artificial.
    Es el paso "Capa 2" de nuestro pipeline si Regex falla (baja confianza) o la entropia es alta.
    Se le puede pasar un diccionario 'context' con datos ya extraídos por Regex para ayudar.
    """
    
    # Preparamos el mensaje adicional de contexto si existe
    extra_context = ""
    
    if context:
        # Filtra los campos que tengan valor
        extracted = [f"{k}: {v}" for k, v in context.items() if v]
        if extracted:
            extra_context = f"\n\nContexto técnico ya detectado (ignora estos tags en el título): {', '.join(extracted)}"
            # Ejemplo: "Contexto técnico ya detectado (ignora estos tags en el título): languages: [EN, ES], subtitles: [ES]"

    # Decidir si usar el LLM local o la API de Google
    if USE_LOCAL_LLM: 
        return _call_local_llm(filename, extra_context)
    else: 
        return _call_gemini(filename, extra_context)


def _call_gemini(filename: str, extra_context: str = "") -> dict:
    """Llama a la nube usando Gemini (vía SDK google-genai)."""
    
    if not GEMINI_API_KEY or GEMINI_API_KEY == "tu_gemini_api_key":
        logger.error("[ERR] GEMINI_API_KEY no encontrada. Por favor, revisa tu .env o habilita USE_LOCAL_LLM.")
        return {"title": filename, "confidence": "failed", "error": "Missing API Key"}

    max_retries = 3
    retry_delay = 5 # segundos

    for attempt in range(max_retries):
        try:
            # Iniciamos el cliente de la nueva librería google-genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            
            # Inferencia con salida JSON forzada, incluyendo el contexto técnico si existe
            response = client.models.generate_content(
                model='gemini-flash-latest', 
                contents=f"{SYSTEM_PROMPT}\n\nAnaliza este archivo: '{filename}'{extra_context}", 
                config={'response_mime_type': 'application/json'}
            )
            
            # Convertimos el string JSON a diccionario
            clean_text = _clean_json_text(response.text)
            result = json.loads(clean_text) 
            result["confidence"] = "ai" 
            return result
            
        except Exception as e:

            error_msg = str(e)

            # Si es un error 503 (Servicio no disponible) o 429 (Cuota agotada), reintentamos
            if any(code in error_msg for code in ["503", "429", "RESOURCE_EXHAUSTED"]) and attempt < max_retries - 1:
                wait_time = retry_delay
                
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                    # La cuota gratuita suele requerir esperas más largas
                    wait_time = max(15, retry_delay)
                    logger.warning(f"[WARN]  Cuota de Gemini agotada (429). Esperando {wait_time}s para reintentar... (Intento {attempt + 1}/{max_retries})")
                else:
                    logger.warning(f"[WARN]  Gemini sobrecargado (503). Reintentando en {wait_time}s... (Intento {attempt + 1}/{max_retries})")
                
                time.sleep(wait_time)
                retry_delay *= 2 # Backoff exponencial simple
                continue
            
            logger.error(f"[ERR] Error en Gemini (google-genai): {e}")
            return {"title": filename, "confidence": "failed", "error": error_msg}


def _clean_json_text(raw_text: str) -> str:
    """Extrae quirúrgicamente el bloque JSON de un texto sucio."""
    if not raw_text:
        return ""
    
    # Intento 1: Limpieza de markdown
    if "```json" in raw_text:
        raw_text = raw_text.split("```json")[1].split("```")[0]
    elif "```" in raw_text:
        raw_text = raw_text.split("```")[1].split("```")[0]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]

    # Intento 2: Buscar llaves (por si hay texto antes o después)
    try:
        start_index = raw_text.find('{')
        end_index = raw_text.rfind('}')
        if start_index != -1 and end_index != -1:
            raw_text = raw_text[start_index:end_index+1]
    except Exception:
        pass

    return raw_text.strip()


def analyze_media_content(title: str, author: str = None, media_type: str = "book") -> dict:
    
    """
    Usa la IA como respaldo para generar una sinopsis y metadatos enriquecidos 
    si las APIs oficiales (OpenLibrary/TMDB) no tienen información.
    """
    
    prompt = f"""Proporciona información detallada sobre esta obra:
    Título: {title}
    {f'Autor: {author}' if author else ''}
    Tipo: {media_type}

    Devuelve un JSON con:
    - "overview": Una sinopsis o resumen de la trama (en español, max 300 palabras).
    - "cast": Lista de personajes principales (si es ficción) o temas clave (si es ensayo/técnico).
    - "collection": Nombre de la saga o colección a la que pertenece (si aplica).
    - "keywords": 5-8 etiquetas descriptivas.

    JSON puro, sin markdown."""

    try:
        if USE_LOCAL_LLM:
            client = openai.OpenAI(base_url=LOCAL_LLM_URL, api_key=LMSTUDIO_API_KEY)
            response = client.chat.completions.create(
                model="local-model",
                messages=[{"role": "user", "content": prompt}]
            )
            raw_text = response.choices[0].message.content
        else:
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content(
                model='gemini-flash-latest', 
                contents=prompt,
                config={'response_mime_type': 'application/json'}
            )
            raw_text = response.text

        clean_text = _clean_json_text(raw_text)
        return json.loads(clean_text)
    except Exception as e:
        logger.error(f"[ERR] Error al generar descripción por IA: {e}")
        return {}


def _call_local_llm(filename: str, extra_context: str = "") -> dict:

    """Llama al servidor local de inferencia (LM Studio)"""
    
    if not LMSTUDIO_API_KEY:
         logger.warning("[WARN] LMSTUDIO_API_KEY no definida, enviando vacío...")
         
    try:
        # El BASE_URL debe pasarse forzosamente al motor de OpenAI oficial si usamos LM Studio
        client = openai.OpenAI(base_url=LOCAL_LLM_URL, api_key=LMSTUDIO_API_KEY)
        
        response = client.chat.completions.create(
            model="local-model", # LM Studio ignora el string e interroga al que tengas cargado.
            messages=[
                # Fusionamos el System Prompt con el User Prompt para máxima compatibilidad
                {"role": "user", "content": f"{SYSTEM_PROMPT}\n\nAnaliza este nombre de archivo: '{filename}'{extra_context}"}
            ]
        )
        
        # Leemos el string resultado
        result_str = response.choices[0].message.content
        
        # Intentamos transformar JSON a diccionario
        clean_text = _clean_json_text(result_str)
        result = json.loads(clean_text)
        
        if result is None:
            raise ValueError("No se pudo parsear el JSON de la respuesta.")

        result["confidence"] = "ai" # Actualizamos la confianza
        return result
        
    except Exception as e:
        logger.error(f"[ERR] Error conectando con el LLM Local en {LOCAL_LLM_URL}: {e}")
        logger.error("[WARN] Verifica que LM Studio tiene el servidor levantado en ese puerto.")
        return {"title": filename, "confidence": "failed", "error": str(e)}
