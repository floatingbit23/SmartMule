"""
test_queue_manager.py — Tests para la cola de prioridad y el worker.

Verifico que los archivos se encolen con la prioridad correcta, que el
worker los procese en orden, y que el shutdown sea limpio.
"""

import time
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from smartmule.queue_manager import QueueManager, FileTask


class TestFileTask:
    """Tests para la dataclass FileTask."""

    def test_orden_por_prioridad(self):
        """
        Verifico que FileTask se ordene por prioridad numérica.
        Las tareas con menor número de prioridad deben ir primero.
        """
        task_low = FileTask(priority=5, file_path="grande.mkv", file_size=5_000_000_000)
        task_high = FileTask(priority=1, file_path="peque.pdf", file_size=1_000_000)

        # La tarea con prioridad 1 debe ser "menor que" la de prioridad 5.
        assert task_high < task_low

    def test_misma_prioridad_no_compara_path(self):
        """
        Verifico que dos tareas con la misma prioridad no fallen al compararse,
        ya que file_path tiene compare=False y no participa en el ordering.
        """
        task_a = FileTask(priority=3, file_path="a.mkv", file_size=100)
        task_b = FileTask(priority=3, file_path="b.mkv", file_size=200)

        # No deben lanzar error al compararse.
        # Con misma prioridad, el resultado de <= debe ser True.
        assert (task_a <= task_b) or (task_b <= task_a)


class TestQueueManager:
    """Tests para el QueueManager."""

    def test_asignacion_prioridad_archivo_pequeno(self, tmp_path):
        """
        Verifico que un archivo pequeño (< 50 MB) reciba prioridad 1.
        """
        # Creo un archivo pequeño de 1 KB.
        small_file = tmp_path / "documento.pdf"
        small_file.write_bytes(b"x" * 1024)

        processed = []

        def mock_process(task):
            processed.append(task)

        qm = QueueManager(process_callback=mock_process)
        qm.enqueue(small_file)

        # Espero a que el worker lo procese.
        time.sleep(1)
        qm.stop()

        assert len(processed) == 1
        assert processed[0].priority == 1

    def test_asignacion_prioridad_ejecutable(self, tmp_path):
        """
        Verifico que un ejecutable reciba prioridad 2, independientemente
        de su tamaño. Los ejecutables necesitan triaje de seguridad urgente.
        """
        exe_file = tmp_path / "setup.exe"
        exe_file.write_bytes(b"x" * 1024)

        processed = []

        def mock_process(task):
            processed.append(task)

        qm = QueueManager(process_callback=mock_process)
        qm.enqueue(exe_file)

        time.sleep(1)
        qm.stop()

        assert len(processed) == 1
        assert processed[0].priority == 2

    def test_orden_de_procesamiento(self, tmp_path):
        """
        Verifico que los archivos se procesen en orden de prioridad.
        Encolo un archivo grande (P5) y luego uno pequeño (P1).
        El pequeño debería procesarse primero.
        """
        # Creo un archivo "grande" (en realidad pequeño para el test,
        # pero con un nombre que me servirá para identificarlo).
        # Para forzar la prioridad, uso tamaños que caigan en distintos rangos.
        large_file = tmp_path / "pelicula.mkv"
        # Necesito que supere SIZE_LARGE (5 GB) para P5, pero eso es impráctico
        # en un test. En su lugar, testeo con el callback el orden real.

        processed_order = []
        process_event = threading.Event()

        def slow_process(task):
            """Proceso lento que me permite verificar el orden."""
            processed_order.append(Path(task.file_path).name)

        # Creo los archivos con tamaños que den prioridades distintas.
        small_file = tmp_path / "doc.pdf"
        small_file.write_bytes(b"x" * 100)  # < 50 MB → P1

        exe_file = tmp_path / "app.exe"
        exe_file.write_bytes(b"x" * 100)  # Ejecutable → P2

        # Creo el QueueManager con un callback que bloquea al principio.
        blocker = threading.Event()

        first_call = True

        def blocking_process(task):
            nonlocal first_call
            if first_call:
                first_call = False
                blocker.wait(timeout=2)  # Bloqueo el primer procesamiento
                return  # No registro el blocker en processed_order
            processed_order.append(Path(task.file_path).name)

        qm = QueueManager(process_callback=blocking_process)

        # Mientras el worker está bloqueado, encolo los dos archivos.
        # El pequeño (P1) debería procesarse antes que el ejecutable (P2).
        # Pero necesito un "archivo bloqueador" primero para que ambos estén
        # en la cola a la vez.
        blocker_file = tmp_path / "blocker.txt"
        blocker_file.write_bytes(b"x" * 100)
        qm.enqueue(blocker_file)  # Este se procesa primero y se bloquea.

        time.sleep(0.3)  # Espero a que el worker agarre el blocker.

        # Ahora encolo los dos archivos de interés mientras el worker
        # está bloqueado con el archivo anterior.
        qm.enqueue(exe_file)    # P2
        qm.enqueue(small_file)  # P1

        # Libero el blocker para que el worker procese los siguientes.
        blocker.set()
        time.sleep(2)

        qm.stop()

        # El PDF (P1) debería haberse procesado antes que el EXE (P2).
        assert len(processed_order) >= 2
        assert processed_order[0] == "doc.pdf"
        assert processed_order[1] == "app.exe"

    def test_shutdown_limpio(self, tmp_path):
        """
        Verifico que stop() detenga el worker sin errores.
        """
        qm = QueueManager()

        # El worker debería estar vivo.
        assert qm._worker_thread.is_alive()

        qm.stop()

        # Tras stop(), el worker debería haberse detenido.
        time.sleep(0.5)
        assert not qm._worker_thread.is_alive()

    def test_pending_count(self, tmp_path):
        """
        Verifico que pending_count refleje el número de tareas en cola.
        """
        blocker = threading.Event()

        def blocking_process(task):
            blocker.wait(timeout=5)

        qm = QueueManager(process_callback=blocking_process)

        # Creo archivos y los encolo.
        f1 = tmp_path / "a.txt"
        f1.write_bytes(b"x" * 100)
        f2 = tmp_path / "b.txt"
        f2.write_bytes(b"x" * 100)

        qm.enqueue(f1)
        time.sleep(0.3)  # Espero a que el worker agarre f1.
        qm.enqueue(f2)

        # f1 está siendo procesada, f2 está en cola.
        assert qm.pending_count >= 1

        blocker.set()
        time.sleep(1)
        qm.stop()

    def test_archivo_inexistente_no_encola(self, tmp_path):
        """
        Verifico que encolar un archivo que no existe no cause error
        y simplemente se registre el error sin encolar.
        """
        processed = []

        def mock_process(task):
            processed.append(task)

        qm = QueueManager(process_callback=mock_process)

        # Intento encolar un archivo que no existe.
        fake_file = tmp_path / "no_existe.txt"
        qm.enqueue(fake_file)

        time.sleep(1)
        qm.stop()

        # No debería haberse procesado nada.
        assert len(processed) == 0
