# Architecture

**Analysis Date:** 2026-06-02

## Pattern Overview

**Overall:** Event-Driven Daemon with Queue-Based Pipeline and SQLite Persistence

**Key Characteristics:**
- **Asynchronous File Observation:** Monitors files via OS-level events (`watchdog`) with debouncing logic.
- **Resource-Efficient Queue:** Thread-safe execution pipeline sorting tasks by file size (smallest first) and executing on a single background worker thread to prevent CPU/Disk starvation.
- **Low-Priority Process Model:** Direct courtesy resource limits (`psutil` Low I/O and CPU priority) to run seamlessly in the background without affecting user gaming or general tasks.
- **Zero-Copy File Routing:** Optimised file transfers (`hardlinks` by default) with automatic cross-partition fallback (`EXDEV` → copy/move).
- **WAL-Mode Persistence:** SQLite Write-Ahead Logging to prevent database locks between background daemon writes and user CLI search executions.

## Layers

**1. Entry Point & Control Layer (`main.py`):**
- Purpose: Service management (Daemon startup/shutdown/restart/status), CLI querying (Hybrid Search, stats), and administrative tasks (manual purging, reprocessing).
- Entry point locations: `main.py`
- Depends on: Watcher, Database, Queue Manager, Organizer

**2. Watcher & Debouncing Layer (`smartmule/watcher.py`):**
- Purpose: File system observation of the `Incoming` download folder.
- Contains: `SmartMuleWatcher` utilizing OS-level event notification.
- Naming/Design: Uses debouncing buffer (`DEBOUNCE_SECONDS`, default 3s) to wait for file writing to complete before queueing.

**3. Queue & Resource Manager Layer (`smartmule/queue_manager.py`):**
- Purpose: Manages tasks queue.
- Contains: Single-worker thread handling processing, ordered by file size. Includes a deferred cleanup manager to release directory locks without leaking threads.
- Depends on: Hasher, Metadata Engine, Database, Organizer

**4. Hasher & Identity Layer (`smartmule/hasher.py`):**
- Purpose: Calculates unique identifiers (ED2K hash and SHA256 fingerprints).
- Contains: Hashing engine using sequential disk reads combined with parallel MD4 chunk computation (`ThreadPoolExecutor`), backpressure controls, and quick-hash fingerprinters (reading first/last 256KB of large files).
- Depends on: `Crypto.Hash.MD4`

**5. Parse & Metadata Engine Layer (`smartmule/metadata_engine.py`, `smartmule/parsers/`):**
- Purpose: Clean filename metadata, determine media type, inspect media codecs, and inspect archives.
- Contains:
  - `regex_parser.py`: Extract resolution, codecs, languages, series season/episode, year, title.
  - `llm_parser.py`: Connects to LM Studio/Gemini to clean dirty titles.
  - `media_inspector.py`: Runs `ffprobe` to determine duration/resolution.
  - `archive_inspector.py`: Runs `patool` to inspect contents of zip/rar/tar archives.
- Depends on: External binaries (ffprobe, 7-zip)

**6. API Enrichment Layer (`smartmule/api/`):**
- Purpose: Fetches community database information and malware analysis.
- Contains: Clients for TMDB, OpenLibrary, MusicBrainz, and VirusTotal.
- Design: Implements exponential backoff and connection timeout guards.

**7. Database & Persistence Layer (`smartmule/database.py`):**
- Purpose: High-performance caching, full-text search indexing, and vector similarity search.
- Contains: Custom SQLite functions (REGEXP, Levenshtein distance, stem), FTS5 virtual tables, automatic sync triggers, and `fastembed` ONNX vector storage.

**8. Organizer Layer (`smartmule/organizer.py`):**
- Purpose: File classification and safe directory transfer.
- Contains: Centralized file routing (SAFE, SUSPICIOUS, MALICIOUS) and the physical transfer implementations (hardlink, copy, move).

## Data Flow

### Event-Driven Processing Flow:

```
[Incoming File Event] 
        │
        ▼ (Watcher)
[Debounce Buffer (3s)]
        │
        ▼ (Queue Manager)
[Queue sorted by file size]
        │
        ▼ (Hasher)
[Fingerprint check in DB] ──(Match)──► [Skip Hashing/API] ──► [Organizer: Hardlink]
        │ (No Match)
        ▼ (Hasher)
[Parallel ED2K Hashing]
        │
        ▼ (Metadata Engine)
[Regex + LLM Parsing] ──► [ffprobe inspection] ──► [API Enrichment]
        │
        ▼ (VirusTotal API)
[Security Verdict Scan] ──(Malicious)──► [Physical File Purge]
        │ (Safe/Suspicious)
        ▼ (Database)
[Save Cache & Vectors]
        │
        ▼ (Organizer)
[Transfer: Hardlink/Move] ──► [OS notification pop-up]
```

### Search Execution Flow (Weighted RRF):
1. User enters: `python main.py --search "matrix 1080p"`
2. Database executes Lexical Search on FTS5 virtual table (BM25 search scoring with Author weights).
3. Database executes Semantic Search on ONNX vectors (Cosine similarity scoring).
4. Both result rankings are fused using Reciprocal Rank Fusion (Weighted RRF: 1.5x Lexical weight, 1.0x Semantic weight).
5. Search yields combined list, displaying match tags (`🧠✨ AI+`, `🧠+📝`, `📝 TEXT`) and scaled score.

## Key Abstractions

**Watcher (`smartmule/watcher.py`):**
- Purpose: Watchdog event handlers translating raw OS events into stable file processing triggers.

**Fingerprinter (`smartmule/hasher.py`):**
- Purpose: Generates an instantaneous 512KB identifier for files to skip expensive calculations.

**API Client (`smartmule/api/`):**
- Purpose: Base REST clients with exponential retry mechanisms.

**Library Organizer (`smartmule/organizer.py`):**
- Purpose: Standardised directory router applying security triaging policies and file system commands.

## Entry Points

**CLI Control (`main.py`):**
- Handles commands: `start`, `stop`, `restart`, `status`, `--search`, `--stats`, `--purge`, `--reprocess`.

**Daemon Startup:**
- Launched invisibly on Windows by `smartmule_launcher.vbs`, spawning the main python process in background.

## Error Handling

- **Resource Lock Retries:** File lock acquisition retry loop (up to 120s) with exponential backoff (`FILE_LOCK_INITIAL_DELAY` to `FILE_LOCK_MAX_DELAY`).
- **EXDEV Fallback:** Catches cross-device hardlink failures (`errno.EXDEV`) and falls back to physical copies automatically.
- **Malware Sanitisation:** Completely removes malicious files before database registration to keep workspace secure.

## Cross-Cutting Concerns

**Logging:**
- Custom `ColoredFormatter` prints logs to stdout with module-specific ANSI colors. Logs are also written to a rotating file `smartmule.log` (5MB limits, 3 archives max).

**Validation:**
- Path validations checks at boot: blocks execution if `Incoming` path is not present in host OS.

---

*Architecture analysis: 2026-06-02*
*Update when major patterns change*
