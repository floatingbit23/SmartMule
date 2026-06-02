
import time
import os
from pathlib import Path
import pytest
from smartmule.hasher import calculate_ed2k

def test_performance_hashing_10gb(tmp_path):
    """
    PERFORMANCE TEST: Simulación de hashing de un archivo de 10GB.
    
    Este test crea un archivo 'sparse' (disperso) de 10GB que no ocupa espacio real en disco,
    pero permite al motor de hashing leerlo completo para medir el rendimiento del 
    sistema de multihilo, backpressure y cálculo MD4.
    """
    # 10 GB en bytes
    SIZE_10GB = 10 * 1024 * 1024 * 1024
    test_file = tmp_path / "performance_10gb.iso"
    
    print("\n[!] Creando archivo mock de 10GB (sparse)...")
    
    # Creamos un archivo sparse (rápido y sin ocupar espacio real)
    with open(test_file, "wb") as f:
        if os.name == 'nt':
            try:
                import ctypes
                FSCTL_SET_SPARSE = 0x000900C4
                kernel32 = ctypes.windll.kernel32
                msvcrt = ctypes.CDLL('msvcrt')
                handle = msvcrt._get_osfhandle(f.fileno())
                if handle != -1:
                    dwBytesReturned = ctypes.c_ulong()
                    kernel32.DeviceIoControl(
                        handle,
                        FSCTL_SET_SPARSE,
                        None, 0,
                        None, 0,
                        ctypes.byref(dwBytesReturned),
                        None
                    )
            except Exception:
                pass
        f.seek(SIZE_10GB - 1)
        f.write(b"\0")
    
    start_time = time.time()
    
    print("[!] Iniciando hashing ED2K de 10GB...")
    hash_result = calculate_ed2k(test_file)
    
    end_time = time.time()
    duration = end_time - start_time
    
    speed_mb_s = (10 * 1024) / duration
    
    print("\n" + "="*50)
    print("PERFORMANCE RESULTS (10GB)")
    print("="*50)
    print(f"Tiempo total: {duration:.2f} segundos")
    print(f"Velocidad:     {speed_mb_s:.2f} MB/s")
    print(f"Hash ED2K:     {hash_result}")
    print("="*50 + "\n")
    
    # Verificamos que el hash es válido (32 caracteres hexadecimales)
    assert len(hash_result) == 32
    assert all(c in "0123456789ABCDEF" for c in hash_result)
    
    # Umbral de salud: Al menos 50MB/s (MD4 es muy rápido, esto es muy conservador)
    assert speed_mb_s > 50, f"Rendimiento demasiado bajo: {speed_mb_s:.2f} MB/s"

if __name__ == "__main__":
    # Permite ejecutarlo directamente para ver el output de print
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        test_performance_hashing_10gb(Path(tmp))
