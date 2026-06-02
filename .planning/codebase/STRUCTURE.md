# Codebase Structure

**Analysis Date:** 2026-06-02

## Directory Layout

```
SmartMule/
├── .agents/            # Agent workflows and automation pipelines
├── .github/            # GitHub configurations
│   └── workflows/      # GitHub CI test runner actions
├── docs/               # System documentation and diagrams
├── images/             # Documentation media assets
├── scratch/            # Workspace temporary/experimental scripts
├── smartmule/          # Core application module
│   ├── api/            # API clients for metadata providers and VirusTotal
│   ├── parsers/        # Internal media, archive, and LLM text parsers
│   ├── config.py       # Configuration and rotating logging setup
│   ├── database.py     # SQLite persistence layer and search indexes
│   ├── embeddings.py   # Embedding checks and check functions
│   ├── file_locker.py  # File system locking and retry utilities
│   ├── hasher.py       # ED2K hashing algorithms and fingerprinters
│   ├── notifications.py# Desktop pop-up alert managers
│   ├── organizer.py    # Zero-copy file routing and classification organizer
│   ├── queue_manager.py# Priority processing tasks queue
│   └── watcher.py      # watchdog incoming directory scanner
├── tests/              # Pytest regression suite
├── .env                # App environment vars (gitignored)
├── .env.example        # Environment variable template config
├── .gitignore          # Git exclusion rules
├── AGENTS.md           # Instructions guide for coding assistants
├── Purga_Interactiva.bat# Interactive purge tool for Windows CMD
├── purga_interactiva.sh# Interactive purge tool for UNIX shell
├── README.md           # User manual (Spanish)
├── README_EN.md        # User manual (English)
├── requirements.txt    # Base python package dependencies
├── requirements-semantic.txt# AI semantic vector dependencies
├── smartmule_launcher.sh# UNIX background service startup shell
└── smartmule_launcher.vbs# Windows invisible background startup script
```

## Directory Purposes

**smartmule/**
- Purpose: Root application package for the SmartMule processing engine.
- Contains: `*.py` core source files.
- Key files:
  - `config.py` - Manages config parameters and logging.
  - `database.py` - SQLite implementation, REGEXP functions, and FTS5/embeddings search database.
  - `queue_manager.py` - Single-worker queue with priority processing based on size.
- Subdirectories: `api/`, `parsers/`

**smartmule/api/**
- Purpose: Houses outbound HTTP clients calling remote databases.
- Contains:
  - `tmdb_client.py` - TMDB search and details API.
  - `openlibrary_client.py` - Book pages and author search API.
  - `musicbrainz_client.py` - Audio data API.
  - `virustotal_client.py` - VirusTotal threat triage lookup API.

**smartmule/parsers/**
- Purpose: Extraction engines that retrieve properties from files.
- Contains:
  - `regex_parser.py` - Lexical filename properties extractor.
  - `llm_parser.py` - Clean name AI parser (LM Studio/Gemini).
  - `media_inspector.py` - Runs `ffprobe` to determine duration/resolution.
  - `archive_inspector.py` - Uses `patool` to inspect archives.

**tests/**
- Purpose: Contains automation tests.
- Contains: `test_*.py` files validating hashlists, regexes, clients, and directory watching.
- Key files: `test_hasher.py`, `test_regex_parser.py`, `test_watcher.py`.

## Key File Locations

**Entry Points:**
- `main.py` - Central CLI interface, daemon lifecycle commands, stats, and search.
- `smartmule_launcher.vbs` - Invisible daemon launcher on Windows.

**Configuration:**
- `.env` - Environment secrets and paths.
- `.env.example` - Template showing expected keys.
- `pytest.ini` - Pytest configuration.

**Core Logic:**
- `smartmule/watcher.py` - Watchdog filesystem watcher.
- `smartmule/queue_manager.py` - Worker execution pipeline.
- `smartmule/organizer.py` - Moves files based on categories.

**Testing:**
- `tests/` - Directory holding all test suites.

**Documentation:**
- `README.md` - Spanish user documentation.
- `README_EN.md` - English user documentation.
- `AGENTS.md` - Technical onboarding guide for AI assistants.

## Naming Conventions

**Files:**
- `snake_case.py` - Python source modules.
- `test_snake_case.py` - Pytest suites.
- `UPPERCASE.md` - Documentation guides.
- `kebab-case` - Launcher scripts and configurations.

**Directories:**
- `snake_case` - Internal modules inside `smartmule/`.
- `kebab-case` or `.name` - Configuration/Agent folders.

## Where to Add New Code

**New API Client Integration:**
- Primary code: `smartmule/api/` (create client e.g. `fanart_client.py`).
- Configuration: Update `smartmule/config.py` with URL/keys.
- Tests: Add `tests/test_fanart_client.py`.

**New File Category / Organizing Path:**
- Organizer implementation: Update `_get_category_folder` and category maps in `smartmule/organizer.py`.
- Metadata engine: Update classification rules in `smartmule/metadata_engine.py`.
- Tests: Update `tests/test_organizer_hardlinks.py` or create category check tests.

**New Parser Logic:**
- Implementation: `smartmule/parsers/` (or update `regex_parser.py`).
- Tests: Append test functions in `tests/test_regex_parser.py`.

**New CLI Option:**
- CLI Definition: Add parser argument inside `main.py`.
- Handler implementation: Write execution flow inside `main.py`.

## Special Directories

**smartmule/venv/ (or venv/)**
- Purpose: Virtual environment packages.
- Committed: No (in `.gitignore`).

**smartmule.log**
- Purpose: Rotating application logs.
- Committed: No (in `.gitignore`).

---

*Structure analysis: 2026-06-02*
*Update when directory structure changes*
