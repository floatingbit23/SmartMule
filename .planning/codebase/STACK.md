# Technology Stack

**Analysis Date:** 2026-06-02

## Languages

**Primary:**
- Python 3.10+ - All application code and tests

**Secondary:**
- VBScript - Background daemon launching script (`smartmule_launcher.vbs`)
- Shell Scripting (.sh) - Unix startup and interactive purge scripts (`smartmule_launcher.sh`, `purga_interactiva.sh`)
- Windows Batch (.bat) - Windows interactive purge script (`Purga_Interactiva.bat`)

## Runtime

**Environment:**
- Python 3.10+ runtime
- External binaries required in system PATH:
  - `FFmpeg (ffprobe)` - Used for video metadata extraction (duration/resolution)
  - `7-Zip` (or compatible archive manager) - Used by `patool` for deep archive inspection

**Package Manager:**
- pip - Package installer for Python
- Lockfile: None (dependencies managed via `requirements.txt` and `requirements-semantic.txt`)

## Frameworks

**Core:**
- None (vanilla Python-based daemon and CLI app)

**Testing:**
- Pytest 7.0+ - Unit and integration testing framework

**Build/Dev:**
- None (standard Python execution, no compilation step needed)

## Key Dependencies

**Critical:**
- `watchdog>=4.0.0` - Monitors file system events in real-time (uses `ReadDirectoryChangesW` on Windows)
- `psutil>=5.9.0` - Restricts I/O and CPU priority (`IOPRIO_VERYLOW`, `IDLE_PRIORITY_CLASS`) to make the daemon resource-efficient
- `pycryptodome>=3.20.0` - Provides the MD4 algorithm (necessary for eMule's ED2K hash calculation, as Python 3.9+ removed MD4 from `hashlib`)
- `google-genai>=0.3.0` & `openai>=1.14.0` - LLM interfaces for title parsing and metadata cleaning
- `fastembed>=0.4.0` & `numpy>=1.24.0` - Lightweight ONNX-based semantic search embeddings (no PyTorch required)

**Infrastructure:**
- `requests>=2.31.0` - Synchronous HTTP library for TMDB, OpenLibrary, MusicBrainz, and VirusTotal APIs
- `python-dotenv>=1.0.0` - Environment variable loader from `.env`
- `patool>=2.2.0` - Archive parser/extractor wrapper
- `plyer>=2.1.0` - Cross-platform OS notification service (pop-ups)
- Built-in `sqlite3` - Lightweight SQL engine (Write-Ahead Logging mode enabled for concurrent writes/reads)

## Configuration

**Environment:**
- `.env` files (loaded by `smartmule/config.py`)
- Key configurations:
  - `INCOMING_PATH` - Path to the folder containing raw eMule/Torrent downloads
  - `LIBRARY_PATH` - Target path where organised media files are hardlinked/moved
  - `TMDB_BEARER_TOKEN` - Bearer token for TMDB Movie/Series lookup
  - `VIRUSTOTAL_API_KEY` - API key for checking file hashes against VirusTotal database
  - `ORGANIZER_MODE` - Transfer mode (`hardlink`, `copy`, or `move`)

**Build:**
- `pytest.ini` - Pytest runner configuration

## Platform Requirements

**Development:**
- Windows (primary development platform; makes direct Win32 API calls via `watchdog` and `psutil`)
- Linux/macOS supported with fallback behavior (e.g., standard file watch and POSIX process nice levels)

**Production:**
- Standard Python 3.10+ execution environment
- Access to the same partition/disk for both `Incoming` and `Library` directories to enable zero-copy operations (`hardlink` or standard `move`)

---

*Stack analysis: 2026-06-02*
*Update after major dependency changes*
