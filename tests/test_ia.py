import logging
import sys
import os

# Asegurar que el directorio raíz esté en el path de Python para los imports
sys.path.append(os.getcwd())

from smartmule.metadata_engine import MetadataEngine
from smartmule.config import setup_logging

# Configuramos logs con nuestro formato estándar de SmartMule
setup_logging(level="INFO")

# Lista de casos "difíciles" que forzarán a la Capa 2 (IA)
test_files = [
    "EICAR_TEST_FILE.exe",
    "Peli_v982_Nueva_2024_HDRip_x264.mp4",
    "La.Guerra.De.Las.Galaxias.Una.Nueva.Esperanza.mkv",
    "Torrente 2 Mision en Marbella [DVDRip][Spanish].avi",
    "Camus, Albert - El Extranjero [1942].pdf",
    "Matrix.Revolutions.(2003).(Spanish.English.Subs).WEB-DL.1080p.mkv",
    "01 - Queen - Bohemian Rhapsody.mp3"
]

def run_test():
    engine = MetadataEngine()

    print("\n" + "="*50)
    print("      🧪 TEST DE PIPELINE HÍBRIDO (REGEX + IA)      ")
    print("="*50 + "\n")

    for filename in test_files:
        print(f"🔹 PROCESANDO: {filename}")
        
        filepath = None
        # Si es un ejecutable para testear el triaje y VirusTotal
        if filename.endswith(".exe"):
            filepath = os.path.join(os.getcwd(), filename)
            
            # Caso especial: EICAR (Simulación de virus para ver el semáforo en ROJO)
            if filename == "EICAR_TEST_FILE.exe":
                content = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
            else:
                content = b"Archivo de prueba inofensivo para SmartMule VirusTotal Test"
            
            with open(filepath, "wb") as f:
                f.write(content)
            
            # Pequeño retardo para dar tiempo al sistema de archivos en Windows
            import time
            time.sleep(0.2)
        
        # El engine evaluará si Regex (Capa 1) es suficiente o si escala a IA (Capa 2)
        # Finalmente consultará la API oficial (Capa 3 y VT)
        result = engine.identify_file(filename, filepath)
        
        print("-" * 50 + "\n")
        
        # Limpiamos el archivo falso tras el test
        if filepath and os.path.exists(filepath):
            os.remove(filepath)

    print("✅ TEST FINALIZADO")

if __name__ == "__main__":
    run_test()
