# External Integrations

**Analysis Date:** 2026-06-02

## APIs & External Services

**Movie & Series Metadata:**
- TMDB (The Movie Database) - Enrichment of movie and series information (saga, cast, director, genres, overview)
  - SDK/Client: REST API via `requests`
  - Auth: Bearer Token in `TMDB_BEARER_TOKEN` env var
  - Base URL: `https://api.themoviedb.org/3`
  - Endpoints used: `/search/movie`, `/search/tv`, `/movie/{id}`, `/tv/{id}`

**Book & Comic Metadata:**
- OpenLibrary - Retrieves page counts, authors, and official titles for books
  - SDK/Client: REST API via `requests`
  - Auth: None (public API)
  - User-Agent header: Configured via `CONTACT_EMAIL_USER_AGENT` env var
  - Base URL: `https://openlibrary.org`
  - Endpoints used: `/search.json`

**Music & Audio Metadata:**
- MusicBrainz - Retrieves audio genres and artist information
  - SDK/Client: REST API via `requests`
  - Auth: None (public API)
  - User-Agent header: Configured via `CONTACT_EMAIL_USER_AGENT` env var
  - Base URL: `https://musicbrainz.org/ws/2`
  - Endpoints used: `/release`

**Security Triaging:**
- VirusTotal - Performs automated threat scans on executable and compressed files
  - SDK/Client: REST API via `requests`
  - Auth: API Key in `VIRUSTOTAL_API_KEY` env var
  - Base URL: `https://www.virustotal.com/api/v3`
  - Endpoints used: `/files` (scan request and report lookup)

**Artificial Intelligence (LLMs):**
- LM Studio (Local LLM) - Default processor for title cleaning and classification
  - SDK/Client: OpenAI API client (`openai` package)
  - Auth: API Key in `LMSTUDIO_API_KEY` (defaults to `"lm-studio"`)
  - Base URL: `http://127.0.0.1:1234/v1` (local port)
- Google Gemini (Cloud LLM) - Alternative remote processor
  - SDK/Client: Google GenAI client (`google-genai` package)
  - Auth: API Key in `GEMINI_API_KEY` env var
  - Model: `gemini-2.5-flash` or similar

## Data Storage

**Database:**
- SQLite (Local File) - Primary cache for files, metadata, search index, and vectors
  - File Location: `LIBRARY_PATH / ".data" / "smartmule.db"`
  - Client: Python built-in `sqlite3`
  - Concurrency: WAL (Write-Ahead Logging) mode enabled for concurrent read and write operations
  - Synchronous mode: Set to `NORMAL` to ensure disk safety with minimal write latency
  - Migrations: Automatic table alterations and column creation handled at connection startup in `smartmule/database.py`

**Embedding & Vector Index:**
- ONNX Embeddings (Local File) - Sentence embeddings for semantic search
  - SDK/Client: `fastembed` with ONNX Runtime
  - Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (stored in local app cache)
  - Quantization: Configurable via `EMBEDDING_QUANTIZATION` (`Default`, `8-bit`, or `4-bit`)

## Monitoring & Observability

**Logs:**
- Local Log File - Central log storage with level-based filtering and console colors
  - File Location: `BASE_DIR / "smartmule.log"`
  - Client: Python built-in `logging.handlers.RotatingFileHandler`
  - Size Limit: 5 MB per file
  - Backup Count: 3 copies retained (`smartmule.log.1`, etc.)
  - Formatting: Custom `ColoredFormatter` for ANSI terminal logs (different colors for main, watcher, hasher, database, and queue_manager)

**Notifications:**
- OS Notifications - Pop-up alert messages for completed or quarantined downloads
  - SDK/Client: `plyer.notification`
  - Platforms: Windows (balloons), macOS/Linux (libnotify/AppleScript)

## CI/CD & Deployment

**Hosting:**
- Local Daemon (Windows/Unix) - Runs continuously in the background using a file watcher
  - Launchers:
    - Windows: `smartmule_launcher.vbs` (silent background execution) or `main.py start`
    - Unix: `smartmule_launcher.sh` or `main.py start`
  - Process Lock: Singleton pattern via `smartmule.pid` to prevent concurrent daemon conflicts

**CI Pipeline:**
- GitHub Actions - Automates test execution and environment verification on commits/PRs
  - Config Location: `.github/workflows/python-tests.yml`
  - Services: Installs dependencies and runs `pytest` across Python versions

## Environment Configuration

**Required Env Variables (.env):**
- `INCOMING_PATH` - Path to the downloads folder
- `LIBRARY_PATH` - Path to the organised folder
- `TMDB_BEARER_TOKEN` - Key to enable movie/series metadata enrichment
- `VIRUSTOTAL_API_KEY` - Key to enable security scan checks

---

*Integration audit: 2026-06-02*
*Update when adding/removing external services*
