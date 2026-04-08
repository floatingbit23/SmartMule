import os
import json
import logging
from google import genai
import openai
import time

from smartmule.config import GEMINI_API_KEY, USE_LOCAL_LLM, LMSTUDIO_API_KEY, LOCAL_LLM_URL

logger = logging.getLogger("SmartMule.parsers.llm")

# System Prompt base, enfocado en estructuración dura sin inventarse datos

SYSTEM_PROMPT = """Eres un experto en extracción de metadatos de archivos de internet. 
Tu tarea es analizar el nombre "sucio" de un archivo descargado (con el que se llama al descargar mediante redes P2P) y extraer su metadata estructurada en formato JSON puro. 

Reglas:
1. Elimina etiquetas inútiles: x264, x265, HEVC, AC3, HDRip, WEB-DL, Dual, Spanish, Castellano, subs, uploader name, by mDudikoff, etc.
2. Identifica correctamente la calidad ("quality") si está presente (1080p, 720p, 4K, 2160p, UHD, 480p).
3. Detecta "season" y "episode" si es una serie. Usa números enteros.
4. Identifica "year" si existe. Usa número entero.
5. "media_type" debe ser exactamente uno de los siguientes strings: "video", "tv series", "movie", "book", "audio", "software", "games", "documents", "image", "subtitles", o "unknown".
6. Devuelve UNICAMENTE un bloque JSON válido, sin delimitadores de markdown (```json). No agregues texto adicional.

Ejemplo 1: "The.Office.S03E05.1080p.HEVC.x265.mkv"
{"title": "The Office", "media_type": "tv series", "season": 3, "episode": 5, "quality": "1080p", "year": null}

Ejemplo 2: "Age_of_Empires_II_Definitive_Edition-ISO-2019.rar"
{"title": "Age of Empires II Definitive Edition", "media_type": "games", "season": null, "episode": null, "quality": null, "year": 2019}

Ejemplo 3: "Manual_Usuario_SmartMule_v1.0_Final.doc"
{"title": "Manual Usuario SmartMule v1.0 Final", "media_type": "documents", "season": null, "episode": null, "quality": null, "year": null}
"""

# Función principal que decide si usar Gemini o LM Studio
def parse_with_llm(filename: str) -> dict:

    """
    Intenta limpiar y extraer toda la informaición del archivo usando Inteligencia Artificial.
    Es el paso "Capa 2" de nuestro pipeline si Regex falla (baja confianza) o la entropia es alta.
    """

    if USE_LOCAL_LLM: # Si USE_LOCAL_LLM es True, llama a LM Studio
        return _call_local_llm(filename)
    else: # Si USE_LOCAL_LLM es False, llama a la API de Google Gemini
        return _call_gemini(filename)


def _call_gemini(filename: str) -> dict:
    """Llama a la nube usando Gemini 2.5 Flash (vía SDK google-genai)."""
    
    if not GEMINI_API_KEY or GEMINI_API_KEY == "tu_gemini_api_key":
        logger.error("❌ GEMINI_API_KEY no encontrada. Por favor, revisa tu .env o habilita USE_LOCAL_LLM.")
        return {"title": filename, "confidence": "failed", "error": "Missing API Key"}

    max_retries = 3
    retry_delay = 5 # segundos

    for attempt in range(max_retries):
        try:
            # Iniciamos el cliente de la nueva librería google-genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            
            # Inferencia con salida JSON forzada
            response = client.models.generate_content(
                model='gemini-2.5-flash', # Modelo a usar
                contents=f"{SYSTEM_PROMPT}\n\nAnaliza este archivo: '{filename}'", # Prompt + archivo a analizar
                config={'response_mime_type': 'application/json'} # Forzamos la salida en JSON
            )
            
            # Convertimos el string JSON a diccionario
            result = json.loads(response.text) 
            result["confidence"] = "ai" 
            return result
            
        except Exception as e:

            error_msg = str(e)

            # Si es un error 503 (Servicio no disponible/Sobrecarga), reintentamos
            if "503" in error_msg and attempt < max_retries - 1:
                logger.warning(f"⚠️  Gemini sobrecargado (503). Reintentando en {retry_delay}s... (Intento {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
                retry_delay *= 2 # Backoff exponencial simple
                continue
            
            logger.error(f"❌ Error en Gemini (google-genai): {e}")
            return {"title": filename, "confidence": "failed", "error": error_msg}


def _call_local_llm(filename: str) -> dict:

    """Llama al servidor local de inferencia (LM Studio)"""
    
    if not LMSTUDIO_API_KEY:
         logger.warning("⚠️ LMSTUDIO_API_KEY no definida, enviando vacío...")
         
    try:
        # El BASE_URL debe pasarse forzosamente al motor de OpenAI oficial si usamos LM Studio
        client = openai.OpenAI(base_url=LOCAL_LLM_URL, api_key=LMSTUDIO_API_KEY)
        
        response = client.chat.completions.create(
            model="local-model", # LM Studio ignora el string e interroga al que tengas cargado.
            messages=[
                # Fusionamos el System Prompt con el User Prompt para máxima compatibilidad
                {"role": "user", "content": f"{SYSTEM_PROMPT}\n\nAnaliza este nombre de archivo: '{filename}'"}
            ]
        )
        
        # Leemos el string resultado
        result_str = response.choices[0].message.content
        
        if not result_str:
            raise ValueError("El modelo devolvió una respuesta vacía.")

        # Limpieza ultra-robusta: Extraemos solo lo que hay entre la primera '{' y la última '}'
        try:
            start_index = result_str.find('{')
            end_index = result_str.rfind('}')
            
            if start_index != -1 and end_index != -1:
                result_str = result_str[start_index:end_index+1]
            else:
                # Si no hay llaves, quizás el modelo respondió con bloques markdown
                if "```" in result_str:
                    result_str = result_str.split("```")[1]
                    if result_str.startswith("json"):
                        result_str = result_str[4:]
        except Exception:
            pass # Si falla la limpieza manual, intentamos parsear lo que haya
        
        # Intentamos transformar JSON a diccionario
        result = json.loads(result_str.strip())
        
        if result is None:
            raise ValueError("No se pudo parsear el JSON de la respuesta.")

        result["confidence"] = "ai" # Actualizamos la confianza
        return result
        
    except Exception as e:
        logger.error(f"❌ Error conectando con el LLM Local en {LOCAL_LLM_URL}: {e}")
        logger.error("⚠️ Verifica que LM Studio tiene el servidor levantado en ese puerto.")
        return {"title": filename, "confidence": "failed", "error": str(e)}
