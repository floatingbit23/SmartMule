"""
BENCHMARK: ThreadPoolExecutor vs ProcessPoolExecutor para hashing ED2K.

Este script mide las DOS dimensiones relevantes del cambio:

  1. THROUGHPUT: ¿Cuántos MB/s puede procesar cada executor?
     → Aquí ProcessPool puede ser ligeramente MÁS LENTO por el overhead de
       serializar chunks de 9.28MB entre procesos (IPC/pickle).

  2. REACTIVIDAD DEL DAEMON: ¿Cuánto "jitter" sufren los hilos I/O del proceso
     principal mientras se hashea un archivo grande?
     → Aquí ProcessPool debería ser CLARAMENTE MEJOR, porque el cómputo MD4
       ocurre en procesos separados que no compiten por el GIL del proceso
       principal. Los threading.Timer y watchdog siguen respondiendo.

Ejecución:
    python tests/benchmark_executor_comparison.py

El script genera un archivo temporal sparse de ~2GB, ejecuta el hashing con
ambos executors, y reporta los resultados lado a lado.
"""

import os
import sys
import time
import threading
import statistics
import concurrent.futures
import collections
import ctypes
from pathlib import Path

# Añado el directorio raíz al path para importar módulos del proyecto
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smartmule.config import ED2K_CHUNK_SIZE
from smartmule.hasher import _calculate_md4_chunk


# =============================================================================
# Configuración del benchmark
# =============================================================================

# Tamaño del archivo de prueba (2GB es suficiente para medir la tendencia)
BENCHMARK_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB

# Intervalo del timer de reactividad (simula los timers del daemon)
TIMER_INTERVAL_MS = 50  # 50ms — igual que un timer de debounce típico

# Número de muestras del timer de reactividad
TIMER_SAMPLES = 100


# =============================================================================
# Motor de hashing parametrizado (acepta Thread o Process pool)
# =============================================================================

def _hash_with_executor(file_path: Path, executor_class):
    """Ejecuta el hashing ED2K usando el executor proporcionado."""

    cpu_count = os.cpu_count() or 1
    max_workers = max(1, cpu_count // 2)
    max_pending = max_workers * 2
    chunk_hashes = []

    with open(file_path, "rb") as f:
        with executor_class(max_workers=max_workers) as executor:
            futures = collections.deque()

            while True:
                if len(futures) >= max_pending:
                    chunk_hashes.append(futures.popleft().result())
                    continue

                chunk = f.read(ED2K_CHUNK_SIZE)
                if not chunk:
                    break

                futures.append(executor.submit(_calculate_md4_chunk, chunk))

            for fut in futures:
                chunk_hashes.append(fut.result())

    return chunk_hashes


# =============================================================================
# Monitor de reactividad (mide el jitter de un timer periódico)
# =============================================================================

class ReactivityMonitor:
    """
    Simula los hilos I/O del daemon (timers, watchdog) y mide cuánto se
    desvían del intervalo esperado mientras el hashing está en curso.

    Un jitter alto = los hilos del daemon no consiguen tiempo de CPU.
    Un jitter bajo = el daemon sigue reactivo durante el hashing.
    """

    def __init__(self, interval_ms: float, max_samples: int):
        self.interval_s = interval_ms / 1000.0
        self.max_samples = max_samples
        self.jitters_ms: list[float] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        """Arranca el monitor en un hilo daemon."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Detiene el monitor y espera a que el hilo termine."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self):
        """Bucle principal: duerme y mide cuánto tardó realmente."""
        while len(self.jitters_ms) < self.max_samples:
            if self._stop_event.is_set():
                break

            t0 = time.perf_counter()
            time.sleep(self.interval_s)
            t1 = time.perf_counter()

            actual_ms = (t1 - t0) * 1000.0
            expected_ms = self.interval_s * 1000.0
            jitter_ms = actual_ms - expected_ms

            self.jitters_ms.append(jitter_ms)

    def get_stats(self) -> dict:
        """Devuelve estadísticas de jitter en milisegundos."""
        if not self.jitters_ms:
            return {"samples": 0}

        return {
            "samples": len(self.jitters_ms),
            "mean_ms": statistics.mean(self.jitters_ms),
            "median_ms": statistics.median(self.jitters_ms),
            "p95_ms": sorted(self.jitters_ms)[int(len(self.jitters_ms) * 0.95)],
            "p99_ms": sorted(self.jitters_ms)[int(len(self.jitters_ms) * 0.99)],
            "max_ms": max(self.jitters_ms),
            "stdev_ms": statistics.stdev(self.jitters_ms) if len(self.jitters_ms) > 1 else 0.0,
        }


# =============================================================================
# Creación del archivo de prueba
# =============================================================================

def create_test_file(path: Path, size: int):
    """Crea un archivo sparse del tamaño indicado (rápido, sin ocupar disco real)."""
    print(f"  Creando archivo sparse de {size / (1024**3):.1f} GB...")

    with open(path, "wb") as f:
        if os.name == 'nt':
            try:
                FSCTL_SET_SPARSE = 0x000900C4
                kernel32 = ctypes.windll.kernel32
                msvcrt = ctypes.CDLL('msvcrt')
                handle = msvcrt._get_osfhandle(f.fileno())
                if handle != -1:
                    dwBytesReturned = ctypes.c_ulong()
                    kernel32.DeviceIoControl(
                        handle, FSCTL_SET_SPARSE,
                        None, 0, None, 0,
                        ctypes.byref(dwBytesReturned), None
                    )
            except Exception:
                pass
        f.seek(size - 1)
        f.write(b"\0")


# =============================================================================
# Ejecución del benchmark
# =============================================================================

def run_single_benchmark(file_path: Path, executor_class, label: str) -> dict:
    """Ejecuta un benchmark individual: throughput + reactividad."""

    print(f"\n{'-' * 60}")
    print(f"  Ejecutando: {label}")
    print(f"{'-' * 60}")

    # Arranco el monitor de reactividad ANTES del hashing
    monitor = ReactivityMonitor(TIMER_INTERVAL_MS, TIMER_SAMPLES)
    monitor.start()

    # Ejecuto el hashing y mido throughput
    t0 = time.perf_counter()
    chunks = _hash_with_executor(file_path, executor_class)
    t1 = time.perf_counter()

    # Detengo el monitor
    monitor.stop()

    duration = t1 - t0
    size_mb = BENCHMARK_SIZE / (1024 * 1024)
    throughput = size_mb / duration

    reactivity = monitor.get_stats()

    print(f"  Throughput:    {throughput:>8.1f} MB/s ({duration:.2f}s)")
    print(f"  Chunks:        {len(chunks)}")
    print(f"  Timer jitter:  mean={reactivity['mean_ms']:.2f}ms, "
          f"p95={reactivity['p95_ms']:.2f}ms, "
          f"max={reactivity['max_ms']:.2f}ms")

    return {
        "label": label,
        "throughput_mbs": throughput,
        "duration_s": duration,
        "chunks": len(chunks),
        "reactivity": reactivity,
    }


def main():
    import tempfile

    print("=" * 60)
    print("  BENCHMARK: ThreadPoolExecutor vs ProcessPoolExecutor")
    print("  Motor de hashing ED2K de SmartMule")
    print("=" * 60)
    print(f"\n  Archivo:     {BENCHMARK_SIZE / (1024**3):.1f} GB (sparse)")
    print(f"  Chunk size:  {ED2K_CHUNK_SIZE / (1024**2):.2f} MB")
    print(f"  CPU cores:   {os.cpu_count()}")
    print(f"  Workers:     {max(1, (os.cpu_count() or 1) // 2)}")
    print(f"  Timer:       {TIMER_INTERVAL_MS}ms × {TIMER_SAMPLES} samples")

    with tempfile.TemporaryDirectory() as tmp:
        test_file = Path(tmp) / "benchmark.bin"
        create_test_file(test_file, BENCHMARK_SIZE)

        # Warmup: una ejecución rápida para inicializar los pools
        print("\n  Warmup...")
        _hash_with_executor(test_file, concurrent.futures.ProcessPoolExecutor)

        # Benchmark A: ThreadPoolExecutor (la implementación anterior)
        result_thread = run_single_benchmark(
            test_file,
            concurrent.futures.ThreadPoolExecutor,
            "ThreadPoolExecutor (anterior)"
        )

        # Benchmark B: ProcessPoolExecutor (la implementación nueva)
        result_process = run_single_benchmark(
            test_file,
            concurrent.futures.ProcessPoolExecutor,
            "ProcessPoolExecutor (actual)"
        )

    # Resultados comparativos
    print("\n" + "=" * 60)
    print("  RESULTADOS COMPARATIVOS")
    print("=" * 60)

    # Tabla de throughput
    t_diff = result_process["throughput_mbs"] - result_thread["throughput_mbs"]
    t_pct = (t_diff / result_thread["throughput_mbs"]) * 100 if result_thread["throughput_mbs"] else 0

    print(f"\n  {'Metrica':<28} {'Thread':>12} {'Process':>12} {'Diff':>10}")
    print(f"  {'-' * 62}")
    print(f"  {'Throughput (MB/s)':<28} {result_thread['throughput_mbs']:>12.1f} {result_process['throughput_mbs']:>12.1f} {t_pct:>+9.1f}%")
    print(f"  {'Duracion (s)':<28} {result_thread['duration_s']:>12.2f} {result_process['duration_s']:>12.2f}")

    # Tabla de reactividad
    rt = result_thread["reactivity"]
    rp = result_process["reactivity"]

    if rt["samples"] > 0 and rp["samples"] > 0:
        print(f"\n  {'Reactividad (jitter)':<28} {'Thread':>12} {'Process':>12} {'Mejor':>10}")
        print(f"  {'-' * 62}")

        metrics = [
            ("Mean jitter (ms)", "mean_ms"),
            ("Median jitter (ms)", "median_ms"),
            ("P95 jitter (ms)", "p95_ms"),
            ("P99 jitter (ms)", "p99_ms"),
            ("Max jitter (ms)", "max_ms"),
            ("Stdev (ms)", "stdev_ms"),
        ]

        for label, key in metrics:
            tv = rt[key]
            pv = rp[key]
            winner = "Process *" if pv < tv else ("Thread *" if tv < pv else "=")
            print(f"  {label:<28} {tv:>12.2f} {pv:>12.2f} {winner:>10}")

    print(f"\n  {'-' * 62}")
    print("  Nota: Un jitter BAJO = el daemon sigue reactivo durante el hashing.")
    print("  El throughput puede ser ligeramente peor con Process (overhead IPC).")
    print("  Lo importante es la REACTIVIDAD: que watchdog y timers no se bloqueen.\n")


if __name__ == "__main__":
    main()
