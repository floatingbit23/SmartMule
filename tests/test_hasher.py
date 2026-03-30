"""
test_hasher.py — Tests unitarios del módulo de hashing ED2K de SmartMule.

Verifico el algoritmo ED2K con archivos sintéticos y valores de referencia conocidos.
Todos los tests usan tempfile para crear archivos temporales en memoria y no dependen
de archivos reales del disco, lo que los hace rápidos y reproducibles.
"""

import tempfile
import os
from pathlib import Path

import pytest
from Crypto.Hash import MD4

from smartmule.hasher import calculate_ed2k, format_ed2k_link
from smartmule.config import ED2K_CHUNK_SIZE


# ==============================================================================
# Helpers
# ==============================================================================

def _write_temp_file(data: bytes) -> Path:
    """Escribo datos en un archivo temporal y devuelvo su Path."""
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(data)
    tmp.close()
    return Path(tmp.name)


def _md4_hex(data: bytes) -> str:
    """Calculo el MD4 de unos datos y devuelvo el digest en hexadecimal (en MAYÚSCULAS)."""
    return MD4.new(data).hexdigest().upper()


def _md4_bytes(data: bytes) -> bytes:
    """Calculo el MD4 de unos datos y devuelvo el digest en bytes."""
    return MD4.new(data).digest()


# ==============================================================================
# Tests del algoritmo ED2K
# ==============================================================================

class TestCalculateED2K:

    def test_hash_archivo_vacio(self):
        """
        Un archivo vacío (0 bytes) tiene el MD4 de una cadena vacía.
        Este es un valor conocido del estándar MD4.
        """
        file_path = _write_temp_file(b"")
        try:
            result = calculate_ed2k(file_path)
            expected = _md4_hex(b"")
            assert result == expected, f"Hash de archivo vacío incorrecto: {result} != {expected}"
        finally:
            os.unlink(file_path)

    def test_hash_archivo_pequeño_un_byte(self):
        """
        Un archivo de 1 byte (muy menor que ED2K_CHUNK_SIZE) debe dar el MD4 directo del contenido.
        Verifico que el caso de "un solo chunk" funciona correctamente.
        """
        data = b"\x42"  # Un byte arbitrario
        file_path = _write_temp_file(data)
        try:
            result = calculate_ed2k(file_path)
            expected = _md4_hex(data)
            assert result == expected
        finally:
            os.unlink(file_path)

    def test_hash_archivo_menor_que_un_chunk(self):
        """
        Un archivo de 1 MB (< 9.28 MB) debe dar el MD4 directo del archivo completo.
        """
        data = b"\xAB" * (1024 * 1024)  # 1 MB de bytes 0xAB
        file_path = _write_temp_file(data)
        try:
            result = calculate_ed2k(file_path)
            expected = _md4_hex(data)
            assert result == expected
        finally:
            os.unlink(file_path)

    def test_hash_exactamente_un_chunk(self):
        """
        Un archivo de exactamente ED2K_CHUNK_SIZE bytes (9,728,000 bytes) es un solo chunk.
        El hash ED2K debe ser el MD4 directo del contenido.
        """
        data = b"\x00" * ED2K_CHUNK_SIZE  # 9.28 MB de ceros
        file_path = _write_temp_file(data)
        try:
            result = calculate_ed2k(file_path)
            expected = _md4_hex(data)
            assert result == expected
        finally:
            os.unlink(file_path)

    def test_hash_dos_chunks_exactos(self):
        """
        Un archivo de exactamente 2 * ED2K_CHUNK_SIZE bytes tiene dos chunks completos.
        El hash final debe ser el MD4 de la concatenación de los dos MD4s parciales.
        """
        chunk1 = b"\x01" * ED2K_CHUNK_SIZE
        chunk2 = b"\x02" * ED2K_CHUNK_SIZE
        data = chunk1 + chunk2
        file_path = _write_temp_file(data)
        try:
            result = calculate_ed2k(file_path)
            # Calculo manualmente el hash esperado según el estándar ED2K
            hash1 = _md4_bytes(chunk1)
            hash2 = _md4_bytes(chunk2)
            expected = _md4_hex(hash1 + hash2)
            assert result == expected, f"Hash de 2 chunks incorrecto: {result} != {expected}"
        finally:
            os.unlink(file_path)

    def test_hash_un_chunk_y_medio(self):
        """
        Un archivo de 1.5 * ED2K_CHUNK_SIZE bytes tiene dos chunks (uno completo y uno parcial).
        El hash final debe ser el MD4 de la concatenación de los MD4s de ambos chunks.
        """
        chunk1 = b"\xAA" * ED2K_CHUNK_SIZE
        chunk2 = b"\xBB" * (ED2K_CHUNK_SIZE // 2)  # Medio chunk
        data = chunk1 + chunk2
        file_path = _write_temp_file(data)
        try:
            result = calculate_ed2k(file_path)
            hash1 = _md4_bytes(chunk1)
            hash2 = _md4_bytes(chunk2)
            expected = _md4_hex(hash1 + hash2)
            assert result == expected
        finally:
            os.unlink(file_path)

    def test_hash_un_byte_mas_que_un_chunk(self):
        """
        Un archivo de ED2K_CHUNK_SIZE + 1 bytes ya entra en el caso del árbol jerárquico.
        Este test verifica la frontera exacta del algoritmo.
        """
        chunk1 = b"\xCC" * ED2K_CHUNK_SIZE
        chunk2 = b"\xDD"  # Un único byte extra
        data = chunk1 + chunk2
        file_path = _write_temp_file(data)
        try:
            result = calculate_ed2k(file_path)
            hash1 = _md4_bytes(chunk1)
            hash2 = _md4_bytes(chunk2)
            expected = _md4_hex(hash1 + hash2)
            assert result == expected
        finally:
            os.unlink(file_path)

    def test_hash_es_string_hexadecimal_32_caracteres(self):
        """
        El hash ED2K siempre debe ser un string hexadecimal de exactamente 32 caracteres (128 bits).
        """
        data = b"SmartMule test data"
        file_path = _write_temp_file(data)
        try:
            result = calculate_ed2k(file_path)
            assert isinstance(result, str)
            assert len(result) == 32
            assert all(c in "0123456789ABCDEF" for c in result)
        finally:
            os.unlink(file_path)

    def test_mismo_contenido_mismo_hash(self):
        """
        Dos archivos con el mismo contenido deben producir exactamente el mismo hash.
        Esto verifica que el algoritmo es determinista.
        """
        data = b"contenido identico para los dos archivos"
        file1 = _write_temp_file(data)
        file2 = _write_temp_file(data)
        try:
            assert calculate_ed2k(file1) == calculate_ed2k(file2)
        finally:
            os.unlink(file1)
            os.unlink(file2)

    def test_contenido_diferente_hash_diferente(self):
        """
        Dos archivos con contenido diferente deben producir hashes diferentes.
        """
        file1 = _write_temp_file(b"contenido A")
        file2 = _write_temp_file(b"contenido B")
        try:
            assert calculate_ed2k(file1) != calculate_ed2k(file2)
        finally:
            os.unlink(file1)
            os.unlink(file2)

    def test_archivo_no_existente_lanza_excepcion(self):
        """
        Si el archivo no existe, calculate_ed2k debe lanzar FileNotFoundError o OSError.
        """
        ruta_falsa = Path("C:/esto/no/existe/archivo.mkv")
        with pytest.raises((FileNotFoundError, OSError)):
            calculate_ed2k(ruta_falsa)


# ==============================================================================
# Tests del formato del enlace ED2K
# ==============================================================================

class TestFormatED2KLink:

    def test_formato_correcto(self):
        """
        El enlace ED2K debe seguir el formato estándar:
        ed2k://|file|nombre|tamaño|hash|/
        """
        file_path = Path("C:/Incoming/Matrix.1999.mkv")
        file_size = 2_912_345_678
        hash_hex = "A3F7B8C9D0E1F2A3B4C5D6E7F8A9B0C1"

        result = format_ed2k_link(file_path, file_size, hash_hex)

        assert result == f"ed2k://|file|Matrix.1999.mkv|{file_size}|{hash_hex}|/"

    def test_incluye_nombre_archivo(self):
        """El enlace debe usar solo el nombre del archivo, no la ruta completa."""
        file_path = Path("C:/una/ruta/muy/larga/pelicula.mkv")
        result = format_ed2k_link(file_path, 1000, "a" * 32)
        assert "pelicula.mkv" in result
        assert "una/ruta/muy/larga" not in result

    def test_incluye_tamano_correcto(self):
        """El tamaño debe aparecer exactamente en el enlace."""
        file_path = Path("archivo.mkv")
        file_size = 9_999_999_999
        result = format_ed2k_link(file_path, file_size, "b" * 32)
        assert str(file_size) in result

    def test_comienza_con_ed2k_protocol(self):
        """El enlace debe comenzar con el protocolo ed2k://."""
        result = format_ed2k_link(Path("test.mkv"), 1000, "c" * 32)
        assert result.startswith("ed2k://|file|")

    def test_termina_con_barra(self):
        """El enlace debe terminar con |/ según el estándar eDonkey."""
        result = format_ed2k_link(Path("test.mkv"), 1000, "d" * 32)
        assert result.endswith("|/")
