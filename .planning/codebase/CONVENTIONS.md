# Coding Conventions

**Analysis Date:** 2026-06-02

## Naming Patterns

**Files:**
- `snake_case.py` for all Python modules (e.g., `queue_manager.py`).
- `test_snake_case.py` for test suites (e.g., `test_regex_parser.py`).
- `kebab-case` for launcher scripts and configurations.

**Functions & Methods:**
- `snake_case` for all functions and methods (e.g., `calculate_ed2k`, `get_by_hash`).
- Private methods and internal helper functions must be prefixed with a single underscore (e.g., `_process_deletions`, `_regexp_worker`).

**Variables:**
- `snake_case` for general variables (e.g., `file_path`, `media_type`).
- `UPPER_SNAKE_CASE` for global settings and constants (e.g., `ED2K_CHUNK_SIZE`, `PID_FILE`).

**Classes:**
- `PascalCase` for all classes (e.g., `HashDatabase`, `LibraryOrganizer`, `QueueManager`).

**Types & Type Hints:**
- Explicit type annotations are used for variables, function signatures, and return values (e.g., `def get_active_pid() -> Optional[int]:`, `BASE_DIR: Path = Path(...)`).

## Code Style

**Formatting:**
- Standard Python PEP 8 style (4 spaces indentation).
- Semicolons are omitted.
- Maximum line length is around 100-120 characters.
- String quotes: Double quotes `"` are generally preferred for SQL statements, docstrings, and print logs; single quotes `'` for dictionary lookups or small values.

**Linting:**
- Checked via GitHub CI workflows on check-ins.

## Import Organization

**Order:**
1. Standard library imports (e.g., `os`, `sys`, `logging`, `time`).
2. Third-party packages (e.g., `watchdog`, `psutil`, `dotenv`, `pytest`).
3. Local application modules (e.g., `from smartmule.config import BASE_DIR`).

**Grouping:**
- Keep standard, third-party, and local imports separated by a single blank line.
- Alphabetical sorting within each import group.

## Error Handling

**Patterns:**
- Wrap I/O operations, network queries, and subprocess calls inside `try/except` blocks.
- Catch specific errors (e.g., `FileNotFoundError`, `OSError`, `sqlite3.OperationalError`) whenever possible, falling back to general `Exception` only when logging unhandled failures.
- Log failures using logger instances with context (e.g., `logger.error(f"[ERR] Fallo organizando {filename}: {e}")`).

**Triage & Validation Errors:**
- Fail fast: Validate critical paths (e.g., `Incoming` folder existence) at daemon startup.
- Cross-device linking: Explicitly catch `EXDEV` failures on `os.link` and fall back to copying.

## Logging

**Framework:**
- Built-in `logging` module.
- Log levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.
- Console outputs are colored using a custom `ColoredFormatter` (defined in `smartmule/config.py`) to distinguish module tags.
- Logs are rotated through a file handler (`smartmule.log`) limited to 5 MB per file, keeping up to 3 backups.

## Comments

**When to Comment:**
- Business logic: Explain why certain thresholds exist (e.g., the 3s debouncing delay or the 120s lock retrieval timeout).
- Official standard specifications (e.g., how the ED2K MD4 chunk hashing tree behaves).
- Skip obvious comments (e.g., `# set value to 0`).

**Docstrings:**
- Module-level docstrings at the beginning of each file detailing its role in the architecture.
- Class and function-level docstrings explaining arguments, returns, and execution steps.
- Write comments in Spanish or English.

---

*Convention analysis: 2026-06-02*
*Update when patterns change*
