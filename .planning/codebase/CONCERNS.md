# Codebase Concerns

**Analysis Date:** 2026-06-02

## Tech Debt

**Raw SQL Query Management:**
- Issue: Persistent database SQL query blocks and manual migrations are defined directly as string literals inside the database module.
- Files: `smartmule/database.py`
- Why: Simple lightweight design without the overhead of heavy third-party Python ORMs like SQLAlchemy.
- Impact: Harder to validate query syntax statically; high risk of SQL regression during database schema changes.
- Fix approach: Abstract query scripts into separate `.sql` query files or adopt a lightweight query builder.

**Hardcoded Application Paths:**
- Issue: Media playback routes for VLC rely on a hardcoded list of standard Windows installation directories.
- Files: `main.py` (lines ~480-500)
- Why: Quick fallback when the `vlc` executable is not registered in the system environment PATH.
- Impact: If VLC is installed in a custom directory on Windows, playback triggers default to standard OS associations.
- Fix approach: Expose a config option `VLC_PATH` in `.env` to override default lookups.

## Known Bugs

- None currently identified as open blockers. All core tests for watcher debouncing, ED2K parallel hashing, and zero-copy organisation are passing.

## Security Considerations

**Unscanned Software Risk (Without VirusTotal Key):**
- Risk: Executables (`.exe`, `.msi`) are processed by the system. If `VIRUSTOTAL_API_KEY` is not configured, threat triage is skipped, potentially exposing the user to malware when they run organized files.
- Files: `smartmule/organizer.py`, `smartmule/api/virustotal_client.py`
- Current mitigation: The search filter `verdict:safe` explicitly excludes the `software` type if it lacks a VirusTotal `SAFE` verdict in the database.
- Recommendations: Log a visible warning message if the daemon starts up without `VIRUSTOTAL_API_KEY` while the incoming folder is being watched.

## Performance Bottlenecks

**Deep Archive Introspection:**
- Problem: Calling `patool` on multi-gigabyte zip/rar/7z files blocks the single-threaded queue worker while reading directory trees.
- File: `smartmule/parsers/archive_inspector.py`
- Measurement: Can block the worker queue for several seconds or minutes on highly nested or massive compressed archives.
- Cause: Synchronous file extraction / metadata listings.
- Improvement path: Run archive inspection on a separate thread or limit archive parsing depth.

## Fragile Areas

**Windows Watcher Event Drops:**
- File: `smartmule/watcher.py`
- Why fragile: Heavy file copying inside the `Incoming` directory can generate hundreds of filesystem events. Windows buffers can overflow, causing watchdog to drop events.
- Common failures: Files might be missed during rapid copy operations.
- Safe modification: Rely on the periodic `scan_existing()` sweep at boot to pick up any missed events.
- Test coverage: Watcher events are mocked but buffer overflows are not tested.

## Scaling Limits

**Local LLM Connection Timeouts:**
- Current capacity: Dependent on the local LM Studio instance's speed.
- Limit: 1 request at a time; slow CPU-based generation can block the queue runner.
- Symptoms at limit: Network timeouts (`API_TIMEOUT` limit, 30s) or database lock delays.
- Scaling path: Configure remote APIs (`GEMINI_API_KEY`) as a fast cloud fallback.

## Missing Critical Features

**Index Syncing Check:**
- Problem: No automated checking to determine if the local ONNX embedding vectors are out of sync with the files table after database schema modifications.
- File: `smartmule/database.py`
- Current workaround: The user must manually execute `python main.py --build-index` to regenerate vectors.
- Implementation complexity: Low (store the index model version hash in database metadata and check it on startup).

## Test Coverage Gaps

**Daemon Signal Operations:**
- What's not tested: Process signal handling (`SIGTERM`), PID file locks, and background daemon execution.
- Risk: Process termination might leave orphan `smartmule.pid` locks on Windows.
- Priority: Medium
- Difficulty to test: Hard to execute cleanly in standard pytest wrappers without spawning subprocess daemons.

---

*Concerns audit: 2026-06-02*
*Update as issues are fixed or new ones discovered*
