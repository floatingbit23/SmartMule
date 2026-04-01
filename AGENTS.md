# Agents.md - Guide for AI Coding Assistants 🧠

This file provides critical context, instructions, and workflows for AI agents working on the **SmartMule** project.

## 🚀 Project Overview

**SmartMule** is an automated media library manager for P2P ecosystems (eMule, aMule). It monitors a download directory, identifies files using hashing (ED2K) and AI, verfies safety (VirusTotal), and organizes them into a clean library structure.

- **Stack**: Python 3.10+, SQLite, Watchdog (FS events), LLMs (Gemini/LM Studio).
- **Core Workflow**: Watcher → Fingerprinting → Semantic Analysis (AI) → API Enrichment (TMDB/OpenLibrary) → Organizer.

---

## 🛠️ Onboarding & Environment Setup

### 1. Python Dependencies
Agents should ensure a virtual environment is used and dependencies are installed from `requirements.txt`.
```bash
python -m venv venv
# Windows
.\venv\Scripts\activate
# Linux/macOS
source venv/bin/activate
pip install -r requirements.txt
```

### 2. System Dependencies (Required)
The project relies on external binaries. If they are missing, features *will* fail.
- **FFmpeg (ffprobe)**: For video duration/resolution extraction.
- **7-Zip (or Patool)**: For deep archive introspection.

### 3. Environment Configuration
Copy `.env.example` to `.env` and configure paths and API keys.
- `INCOMING_PATH`: Where eMule puts finished files.
- `LIBRARY_PATH`: Final destination for organized media.
- `TMDB_BEARER_TOKEN`: Required for movie/series metadata.
- `VIRUSTOTAL_API_KEY`: Required for security triage.

---

## 🏗️ Technical Architecture

### Core Components
- `main.py`: Entry point for both the daemon and the CLI control (start/stop).
- `smartmule/watcher.py`: Monitors `INCOMING_PATH` for new files.
- `smartmule/hasher.py`: Calculates ED2K hashes for precise P2P identification.
- `smartmule/metadata_engine.py`: Uses LLM to clean names and classifies media type.
- `smartmule/organizer.py`: Moves and renames files based on metadata.
- `smartmule/database.py`: Persists file status, metadata, and fingerprints.

### Key Logic: Tie-Breaking
When an LLM provides multiple matches for a title, SmartMule uses `ffprobe` to compare file duration against TMDB data to select the correct production.

---

## 🧪 Testing & Validation

Run the test suite before any major PR/Push:
```bash
pytest -v --tb=short
```
Tests are located in `/tests` and use mock objects for external APIs and file system events.

---

## 📋 Development Guidelines

1. **Bilingual Documentation**: Keep `README.md` (Spanish) and `README_EN.md` (English) in sync.
2. **Error Resilience**: Use exponential backoff for API calls (see `smartmule/api/`).
3. **Log Integrity**: Maintain `smartmule.log` for debugging the background daemon.
4. **No Placeholders**: Never use placeholder text in generated code or documentation.

---

## 🛠️ Workflows for Agents

### How to Start/Stop the Service (Windows Daemon)
- **Start**: Run `python main.py start` (standard) or `smartmule_launcher.vbs` (invisible).
- **Stop**: Run `python main.py stop`. This looks for the persistent PID and shuts down the watcher cleanly.

### How to Add a New Category
1. Add classification logic to `smartmule/metadata_engine.py`.
2. Define the folder structure in `smartmule/organizer.py`.
3. Add relevant tests in `tests/`.

---

> [!IMPORTANT]
> Always verify that `FFmpeg` and `7-Zip` are in the system `PATH` if debugging extraction or metadata errors.
