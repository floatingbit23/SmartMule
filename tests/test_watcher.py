"""
test_watcher.py — Tests para el observador del sistema de archivos.

Verifico que el IncomingHandler filtre correctamente las extensiones
de eMule, que el debouncing agrupe eventos duplicados, y que el scan
inicial funcione.
"""

import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from smartmule.watcher import IncomingHandler, SmartMuleWatcher
from smartmule.queue_manager import QueueManager


class TestIncomingHandler:
    """Tests para el handler de eventos del sistema de archivos."""

    def test_ignora_archivos_part(self):
        """
        Verifico que los archivos .part de eMule se ignoren.
        Estos son descargas incompletas que no debo procesar.
        """
        # Creo un QueueManager mock para verificar que no se encole nada.
        mock_qm = MagicMock(spec=QueueManager)
        handler = IncomingHandler(mock_qm)

        # Simulo que el handler recibe la ruta de un archivo .part.
        part_path = Path("C:/eMule/Incoming/descarga.part")
        assert handler._should_ignore(part_path) is True

    def test_ignora_archivos_part_met(self):
        """
        Verifico que los archivos .part.met (metadatos de eMule) se ignoren.
        """
        mock_qm = MagicMock(spec=QueueManager)
        handler = IncomingHandler(mock_qm)

        part_met_path = Path("C:/eMule/Incoming/descarga.part.met")
        assert handler._should_ignore(part_met_path) is True

    def test_ignora_archivos_part_met_bak(self):
        """
        Verifico que los archivos .part.met.bak (backup de metadatos) se ignoren.
        """
        mock_qm = MagicMock(spec=QueueManager)
        handler = IncomingHandler(mock_qm)

        bak_path = Path("C:/eMule/Incoming/descarga.part.met.bak")
        assert handler._should_ignore(bak_path) is True

    def test_ignora_archivos_tmp(self):
        """
        Verifico que los archivos .tmp genéricos se ignoren.
        """
        mock_qm = MagicMock(spec=QueueManager)
        handler = IncomingHandler(mock_qm)

        tmp_path = Path("C:/eMule/Incoming/temp.tmp")
        assert handler._should_ignore(tmp_path) is True

    def test_no_ignora_archivos_mkv(self):
        """
        Verifico que los archivos .mkv NO se ignoren.
        Son archivos legítimos que debo procesar.
        """
        mock_qm = MagicMock(spec=QueueManager)
        handler = IncomingHandler(mock_qm)

        mkv_path = Path("C:/eMule/Incoming/pelicula.mkv")
        assert handler._should_ignore(mkv_path) is False

    def test_no_ignora_archivos_pdf(self):
        """
        Verifico que los archivos .pdf NO se ignoren.
        """
        mock_qm = MagicMock(spec=QueueManager)
        handler = IncomingHandler(mock_qm)

        pdf_path = Path("C:/eMule/Incoming/libro.pdf")
        assert handler._should_ignore(pdf_path) is False

    def test_no_ignora_archivos_exe(self):
        """
        Verifico que los archivos .exe NO se ignoren.
        Necesitan procesamiento (triaje de seguridad).
        """
        mock_qm = MagicMock(spec=QueueManager)
        handler = IncomingHandler(mock_qm)

        exe_path = Path("C:/eMule/Incoming/setup.exe")
        assert handler._should_ignore(exe_path) is False

    def test_no_ignora_archivos_mp3(self):
        """
        Verifico que los archivos .mp3 NO se ignoren.
        """
        mock_qm = MagicMock(spec=QueueManager)
        handler = IncomingHandler(mock_qm)

        mp3_path = Path("C:/eMule/Incoming/cancion.mp3")
        assert handler._should_ignore(mp3_path) is False

    def test_no_ignora_archivos_srt(self):
        """
        Verifico que los archivos de subtítulos .srt NO se ignoren.
        """
        mock_qm = MagicMock(spec=QueueManager)
        handler = IncomingHandler(mock_qm)

        srt_path = Path("C:/eMule/Incoming/subtitulo.srt")
        assert handler._should_ignore(srt_path) is False

    @patch("smartmule.watcher.wait_for_unlock", return_value=True)
    def test_debounce_agrupa_eventos(self, mock_unlock, tmp_path):
        """
        Verifico que múltiples eventos para el mismo archivo se agrupen
        en un solo dispatch gracias al debouncing.

        Creo un archivo real en tmp_path, disparo _reset_timer 5 veces
        rápidamente, y verifico que _dispatch_file se llame solo 1 vez
        tras expirar el debounce.
        """
        mock_qm = MagicMock(spec=QueueManager)
        handler = IncomingHandler(mock_qm)

        # Creo un archivo real para que _dispatch_file lo encuentre.
        test_file = tmp_path / "test_debounce.mkv"
        test_file.write_bytes(b"x" * 100)

        # Parcheo DEBOUNCE_SECONDS para que el test sea rápido.
        with patch("smartmule.watcher.DEBOUNCE_SECONDS", 0.5):
            # Disparo 5 resets rápidamente (simulando 5 eventos de Windows).
            for _ in range(5):
                handler._reset_timer(test_file)
                time.sleep(0.05)  # 50ms entre cada evento

            # Espero a que el último timer expire (0.5s de debounce).
            time.sleep(1.0)

        # El QueueManager solo debería haber recibido 1 enqueue, no 5.
        assert mock_qm.enqueue.call_count == 1

    def test_cleanup_cancela_timers(self, tmp_path):
        """
        Verifico que cleanup() cancele todos los timers activos.
        """
        mock_qm = MagicMock(spec=QueueManager)
        handler = IncomingHandler(mock_qm)

        # Creo algunos timers.
        test_file_1 = tmp_path / "file1.mkv"
        test_file_2 = tmp_path / "file2.pdf"
        test_file_1.write_bytes(b"x")
        test_file_2.write_bytes(b"x")

        with patch("smartmule.watcher.DEBOUNCE_SECONDS", 10):
            handler._reset_timer(test_file_1)
            handler._reset_timer(test_file_2)

            # Debería haber 2 timers activos.
            assert len(handler._timers) == 2

            # Limpio los timers.
            handler.cleanup()

            # Debería haber 0 timers.
            assert len(handler._timers) == 0


class TestSmartMuleWatcher:
    """Tests para el wrapper de alto nivel del watcher."""

    def test_scan_existing_encuentra_archivos(self, tmp_path):
        """
        Verifico que scan_existing() detecte archivos existentes en la carpeta
        y los encole en el QueueManager.
        """
        mock_qm = MagicMock(spec=QueueManager)

        # Creo archivos en tmp_path para simular la carpeta Incoming.
        (tmp_path / "pelicula.mkv").write_bytes(b"x" * 100)
        (tmp_path / "libro.pdf").write_bytes(b"x" * 50)
        (tmp_path / "descarga.part").write_bytes(b"x" * 200)  # Este se ignora.

        with patch("smartmule.watcher.INCOMING_PATH", tmp_path):
            with patch("smartmule.watcher.wait_for_unlock", return_value=True):
                watcher = SmartMuleWatcher(mock_qm)
                count = watcher.scan_existing()

        # Solo debería encolar 2 archivos (mkv y pdf), no el .part.
        assert count == 2
        assert mock_qm.enqueue.call_count == 2

    def test_scan_existing_sin_archivos(self, tmp_path):
        """
        Verifico que scan_existing() maneje correctamente una carpeta vacía.
        """
        mock_qm = MagicMock(spec=QueueManager)

        with patch("smartmule.watcher.INCOMING_PATH", tmp_path):
            watcher = SmartMuleWatcher(mock_qm)
            count = watcher.scan_existing()

        assert count == 0
        assert mock_qm.enqueue.call_count == 0
