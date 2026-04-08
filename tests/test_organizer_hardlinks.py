import pytest
import os
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from smartmule.organizer import LibraryOrganizer

@pytest.fixture
def organizer_folders(tmp_path):
    """Prepara carpetas temporales para el test."""
    incoming = tmp_path / "Incoming"
    library = tmp_path / "Library"
    incoming.mkdir()
    library.mkdir()
    
    # Mockeamos la constante global de config
    with patch("smartmule.organizer.LIBRARY_PATH", str(library)):
        yield incoming, library

def test_hardlink_simple_file(organizer_folders):
    """Verifica que un archivo individual se vincule correctamente sin borrarse del origen."""
    incoming, library = organizer_folders
    file_src = incoming / "movie.mkv"
    file_src.write_text("contenido del video")
    
    organizer = LibraryOrganizer()
    metadata = {
        "media_type": "movie",
        "title": "Movie Test",
        "api_data": {"veredicto": "SAFE"}
    }
    
    with patch("smartmule.organizer.ORGANIZER_MODE", "hardlink"):
        dest_path_str = organizer.organize(str(file_src), metadata)
        dest_path = Path(dest_path_str)
        
        # 1. El archivo original DEBE seguir existiendo (para el seeding)
        assert file_src.exists()
        
        # 2. El archivo destino DEBE existir
        assert dest_path.exists()
        
        # 3. Deben ser el MISMO archivo físico (Hardlink)
        # En Windows/Unix samefile comprueba el ID de archivo/Inodo
        assert os.path.samefile(str(file_src), str(dest_path))
        
        # 4. El contador de enlaces (links) debe ser al menos 2
        assert file_src.stat().st_nlink >= 2

def test_hardlink_recursive_dir(organizer_folders):
    """Verifica que un directorio de release se recree con hardlinks internos."""
    incoming, library = organizer_folders
    release_dir = incoming / "Season_01"
    release_dir.mkdir()
    file1 = release_dir / "ep01.mkv"
    file1.write_text("data 1")
    subs_dir = release_dir / "Subs"
    subs_dir.mkdir()
    file2 = subs_dir / "ep01.srt"
    file2.write_text("data 2")
    
    organizer = LibraryOrganizer()
    metadata = {
        "media_type": "tv series",
        "title": "Series Test",
        "api_data": {"veredicto": "SAFE"}
    }
    
    with patch("smartmule.organizer.ORGANIZER_MODE", "hardlink"):
        dest_path_str = organizer.organize(str(release_dir), metadata)
        dest_path = Path(dest_path_str)
        
        # 1. La carpeta origen sigue ahí
        assert release_dir.exists()
        
        # 2. La estructura se ha replicado
        assert (dest_path / "ep01.mkv").exists()
        assert (dest_path / "Subs" / "ep01.srt").exists()
        
        # 3. Los ficheros internos son hardlinks
        assert os.path.samefile(str(file1), str(dest_path / "ep01.mkv"))
        assert os.path.samefile(str(file2), str(dest_path / "Subs" / "ep01.srt"))

def test_fallback_to_copy_on_cross_device(organizer_folders):
    """Verifica que si falla el hardlink (OSError EXDEV), se use copia tradicional."""
    incoming, library = organizer_folders
    file_src = incoming / "cross_disk.mkv"
    file_src.write_text("big movie file")
    
    organizer = LibraryOrganizer()
    metadata = { "media_type": "movie", "title": "Fallback Test", "api_data": {"veredicto": "SAFE"}}
    
    # Simulamos error de partición cruzada (EXDEV)
    import errno
    cross_device_err = OSError(errno.EXDEV, "Cross-device link")
    
    with patch("smartmule.organizer.ORGANIZER_MODE", "hardlink"):
        # Parcheamos la llamada de sistema os.link para que falle una vez
        with patch("os.link", side_effect=cross_device_err):
            with patch("shutil.copy2") as mock_copy:
                organizer.organize(str(file_src), metadata)
                
                # Verificamos que se llamó a la función de copia como plan B
                assert mock_copy.called
                args, _ = mock_copy.call_args
                assert str(file_src) == str(args[0])

def test_malicious_deletion_no_link(organizer_folders):
    """Verifica que el malware se borre del tirón en lugar de linkearse."""
    incoming, library = organizer_folders
    virus = incoming / "malware.exe"
    virus.write_text("soy un virus")
    
    organizer = LibraryOrganizer()
    metadata = { "media_type": "software", "api_data": {"veredicto": "MALICIOUS"}}
    
    with patch("smartmule.organizer.ORGANIZER_MODE", "hardlink"):
        result = organizer.organize(str(virus), metadata)
        
        assert result == "<DELETED_MALICIOUS>"
        # El virus debe haber sido borrado de la carpeta Incoming
        assert not virus.exists()
