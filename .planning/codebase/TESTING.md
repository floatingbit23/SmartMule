# Testing Patterns

**Analysis Date:** 2026-06-02

## Test Framework

**Runner:**
- Pytest 7.0+
- Configurations specified in: `pytest.ini` in the project root

**Assertion Library:**
- Standard Pytest built-in `assert` statement.
- Custom assertions verify exact structure matches, file sizes, and ED2K hash lengths.

**Run Commands:**
```bash
pytest                                       # Run all tests in the suite
pytest -v --tb=short                         # Verbose execution with short traceback summaries
pytest tests/test_hasher.py                  # Execute a single test file
pytest -k "test_debounce"                    # Execute matching tests by expression pattern
```

## Test File Organization

**Location:**
- Dedicated `tests/` directory at the project root.
- Test modules are not colocated with the source code inside `smartmule/`.

**Naming:**
- Filename pattern: `test_*.py` (e.g., `test_hasher.py`, `test_watcher.py`).

**Structure:**
```
[project-root]/
├── smartmule/
│   ├── config.py
│   └── watcher.py
└── tests/
    ├── __init__.py
    ├── test_hasher.py
    └── test_watcher.py
```

## Test Structure

**Suite Organization:**
```python
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from smartmule.watcher import IncomingHandler

class TestIncomingHandler:

    @pytest.fixture
    def mock_qm(self):
        # Setup common mock resource
        return MagicMock()

    def test_ignora_archivos_part(self, mock_qm):
        # Arrange
        handler = IncomingHandler(mock_qm)
        part_path = Path("C:/eMule/Incoming/descarga.part")

        # Act
        result = handler._should_ignore(part_path)

        # Assert
        assert result is True
```

**Patterns:**
- **Atoms:** Test files contain clean atomic functions or classes grouped by system component (e.g. `TestIncomingHandler`, `TestCalculateED2K`).
- **Cleanups:** Uses standard Python filesystem teardown blocks (`try/finally` with `os.unlink()`) or Pytest's directory fixture `tmp_path` to delete test-generated assets automatically.
- **Explicit Mocks:** External calls are stubbed to prevent executing real remote network API calls during testing.

## Mocking

**Framework:**
- `unittest.mock` (standard Python library)
- decorators: `@patch` to intercept methods (e.g., requests, sleep times).
- clients: `MagicMock` for tracking call counts, arguments, and injecting mocked data.

**Patterns:**
```python
from unittest.mock import patch, MagicMock

@patch('smartmule.api.openlibrary_client.requests.get')
def test_search_book_success(mock_get, ol_client):
    # Setup mock response properties
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "docs": [{"title": "El Señor de los Anillos", "author_name": ["J. R. R. Tolkien"]}]
    }
    mock_get.return_value = mock_response

    # Execute and Assert
    result = ol_client.search_books("El Señor de los Anillos")
    assert result[0]["title"] == "El Señor de los Anillos"
    mock_get.assert_called_once()
```

**What to Mock:**
- API Services: Outgoing HTTP connection requests (`requests.get`, `requests.post`) for TMDB, OpenLibrary, MusicBrainz, and VirusTotal.
- Queue Manager Enqueues: Stubbed in Watcher tests to check if the file handler registers events without writing files.
- Thread Timers & sleep periods: Debouncing timeouts mocked to speed up execution of tests.

**What NOT to Mock:**
- Pure Hashing Operations: Tests write small synthetically-generated binary blocks in memory to verify MD4 correctness against real hasher executions.
- Filename cleaning logic: Regex and string manipulation tested with actual inputs.

## Fixtures and Factories

- **Test Fixtures:** Defined as standard pytest decorators `@pytest.fixture` (e.g., setting up client instances).
- **Temporary directories:** Pytest's standard `tmp_path` fixture is used extensively to mock incoming/library files.

## Coverage

- **Target:** General code-level verification; no strict minimum percentage enforced in CI pipelines, but critical modules (hasher, regex_parser, watcher, database) are covered by dedicated test suites.

## Test Types

**Unit Tests:**
- Validate single functions (e.g., regex parsing on filenames, database inserts, and ED2K tree hash boundary checks).
- Run execution within milliseconds.

**Integration Tests:**
- Validate multiple modules acting together.
- Example: Filewatcher scans local directories, debounce groups events, then checks if files are enqueued.

---

*Testing analysis: 2026-06-02*
*Update when test patterns change*
