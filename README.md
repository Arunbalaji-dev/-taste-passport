# Taste Passport

Discover new places in any city that you'll actually love, based on what you already love.

## Run locally (Windows cmd)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

Then open http://localhost:8000. Run the tests with `pytest`.
