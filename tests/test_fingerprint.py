import tempfile
import os
from pathlib import Path
from smartmule.hasher import calculate_fingerprint

def test_fingerprint_archivo_pequeno():
    """Archivos < 512KB se hashean enteros."""
    data = b"Contenido de prueba para archivo pequeno"
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    
    try:
        f1 = calculate_fingerprint(tmp_path, len(data))
        assert len(f1) == 64
        
        # Mismo contenido, diferente nombre (simulado)
        f2 = calculate_fingerprint(tmp_path, len(data))
        assert f1 == f2
        
        # Cambio un solo byte
        with open(tmp_path, "wb") as f:
            f.write(data + b"!")
        f3 = calculate_fingerprint(tmp_path, len(data) + 1)
        assert f1 != f3
    finally:
        os.unlink(tmp_path)

def test_fingerprint_archivo_grande():
    """Archivos >= 512KB hashean solo extremos."""
    size = 1024 * 1024  # 1MB
    # Genero datos aleatorios
    data = os.urandom(size)
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    
    try:
        f_original = calculate_fingerprint(tmp_path, size)
        
        # 1. Modifico el CENTRO del archivo (a 512KB)
        # El fingerprint NO debería cambiar porque solo mira los extremos (256KB).
        with open(tmp_path, "r+b") as f:
            f.seek(512 * 1024)
            f.write(b"MODIFICACION_CENTRAL")
        
        f_centro_modificado = calculate_fingerprint(tmp_path, size)
        assert f_original == f_centro_modificado, "El fingerprint cambio al modificar el centro!"

        # 2. Modifico el PRINCIPIO del archivo
        # El fingerprint DEBE cambiar.
        with open(tmp_path, "r+b") as f:
            f.seek(0)
            f.write(b"HEAD")
        
        f_inicio_modificado = calculate_fingerprint(tmp_path, size)
        assert f_original != f_inicio_modificado, "El fingerprint NO cambio al modificar el inicio!"

        # 3. Modifico el FINAL del archivo
        # El fingerprint DEBE cambiar.
        with open(tmp_path, "r+b") as f:
            f.seek(size - 10)
            f.write(b"TAIL")
        
        f_final_modificado = calculate_fingerprint(tmp_path, size)
        assert f_inicio_modificado != f_final_modificado, "El fingerprint NO cambio al modificar el final!"

    finally:
        os.unlink(tmp_path)
