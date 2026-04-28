import pytest
import time
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
from smartmule.hasher import calculate_ed2k
from smartmule.config import ED2K_CHUNK_SIZE

"""
Test de Estrés: Simulación de hashing de un archivo de 200GB.
Este test verifica la estabilidad del sistema de hilos y el backpressure
con volúmenes de datos masivos.
"""

def test_hashing_stress_200gb():
    # 200 GB en bloques de 9.28 MB son aproximadamente 22,076 bloques
    GB_TO_SIMULATE = 200
    total_chunks = int((GB_TO_SIMULATE * 1024 * 1024 * 1024) / ED2K_CHUNK_SIZE)
    
    print(f"\n[STRESS TEST] Iniciando simulación de archivo ISO de {GB_TO_SIMULATE} GB...")
    print(f"[STRESS TEST] Total de bloques a procesar: {total_chunks}")

    # Creamos un bloque de datos vacío (ceros) para reutilizarlo
    fake_chunk = b"\0" * ED2K_CHUNK_SIZE
    
    # Mockeamos el objeto de archivo
    mock_file = MagicMock()
    # Devolvemos el mismo bloque miles de veces y luego b"" para cerrar
    # Usamos un generador para no ocupar 200GB de RAM en la lista de side_effect
    def chunk_generator():
        for _ in range(total_chunks):
            yield fake_chunk
        yield b""
        
    mock_file.read.side_effect = chunk_generator()
    mock_file.__enter__.return_value = mock_file
    
    start_time = time.time()
    
    # Parcheamos el sistema de archivos para que crea que el archivo de 200GB existe
    with patch("builtins.open", return_value=mock_file), \
         patch("pathlib.Path.is_dir", return_value=False), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat") as mock_stat:
        
        # Simulamos el tamaño de 200GB en el stat
        mock_stat.return_value.st_size = GB_TO_SIMULATE * 1024 * 1024 * 1024
        
        # EJECUCIÓN DEL HASHING REAL
        # (Usa el código real de hasher.py con sus hilos paralelos)
        ed2k_hash = calculate_ed2k(Path("fake_ultra_iso.iso"))
        
    end_time = time.time()
    duration = end_time - start_time
    
    print(f"\n" + "="*60)
    print(f"RESULTADOS DEL TEST DE ESTRÉS (200 GB)")
    print(f"Tiempo total: {duration:.2f} segundos")
    print(f"Velocidad media: {(GB_TO_SIMULATE * 1024) / duration:.2f} MB/s")
    print(f"Hash ED2K resultante: {ed2k_hash}")
    print("="*60)
    
    # Verificaciones básicas
    assert len(ed2k_hash) == 32, "El hash debe tener 32 caracteres hexadecimales"
    assert ed2k_hash != "", "El hash no puede estar vacío"
    
    # En una CPU moderna con 6+ cores y hilos paralelos, 
    # 200GB deberían procesarse en menos de 120 segundos (simulados).
    # Si tarda más, algo va mal con la paralelización.
    assert duration < 300, "El proceso es demasiado lento, revisa el pool de hilos"

if __name__ == "__main__":
    # Permite ejecutarlo directamente con python tests/test_hashing_stress.py
    test_hashing_stress_200gb()


"""
# RESULTADOS DEL TEST DE ESTRÉS (200 GB)

Se ha ejecutado la simulación de hashing ED2K de un archivo de 200 GB (unos 22.000 bloques de 9.28MB):
- Tiempo total: 54,74 segundos.
- Velocidad media de procesado: 3.741,50 MB/s (casi 4GB/s).
- Hash ED2K generado: C43965892AB32F6C55E50084C6873905.
"""