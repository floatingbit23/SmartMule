import subprocess
import json
import logging
from pathlib import Path
from typing import Optional, Dict

"""
El objetivo de este módulo es solucionar el problema de los archivos homónimos.

Por ejemplo, si tenemos dos películas con el mismo nombre, "Solaris", 
una de 1972 y otra de 2002, el motor de búsqueda nos devolverá ambas.

Para solucionar esto, necesitamos obtener metadatos técnicos reales del archivo para poder desempatar.
"""

logger = logging.getLogger("SmartMule.parsers.media_inspector")

# Método para extraer metadatos técnicos reales del archivo (duración, resolución, etc.)
def inspect_media_file(filepath: str) -> Dict:

    """
    Usa ffprobe (parte de FFmpeg) para extraer metadatos técnicos reales del archivo (duración, resolución, etc.)
    Esto sirve para el desempate cuando hay varias películas con el mismo nombre.
    """

    path = Path(filepath)

    # Datos por defecto
    result = {
        "duration_sec": 0,
        "width": 0,
        "height": 0,
        "is_media": False
    }

    if not path.exists():
        return result

    try:

        # Comando de ffprobe para obtener duración y resolución en formato JSON

        cmd = [
            "ffprobe", 
            "-v", "error",
            "-show_entries", "format=duration:stream=width,height", # Muestra duración y resolución
            "-of", "json", # Formato de salida JSON
            filepath # Archivo a analizar
        ]
        
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT) # Ejecuta el comando y captura la salida
        data = json.loads(output) # Convierte la salida JSON a diccionario

        # Extraer duración (formato)
        if "format" in data and "duration" in data["format"]:
            result["duration_sec"] = int(float(data["format"]["duration"])) # Convierte la duración a segundos
            result["is_media"] = True # Marca como multimedia
 
        # Extraer resolución (primer stream de video)
        if "streams" in data:

            for stream in data["streams"]: # Itera sobre los streams

                if "width" in stream and "height" in stream: # Si encuentra ancho y alto
                    result["width"] = stream["width"] # Asigna el ancho
                    result["height"] = stream["height"] # Asigna el alto
                    result["is_media"] = True # Marca como multimedia
                    break

        duration_min = result["duration_sec"] // 60 # Convierte la duración a minutos
        logger.debug(f"🔍 [Inspector] Duración detectada: {duration_min} min ({filepath})") # Muestra la duración

    except Exception as e:
        logger.warning(f"⚠️ [Inspector] No se pudo leer metadatos de {path.name}: {e}")

    return result
