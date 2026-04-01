---
description: Pipeline for technical onboarding of SmartMule
---
// turbo-all

1. Create a virtual environment: `python -m venv venv`
2. Activate the virtual environment:
   - Windows: `.\venv\Scripts\activate`
   - Linux/macOS: `source venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Copy environment example: `cp .env.example .env`
5. Run tests to verify setup: `pytest -v --tb=short`
