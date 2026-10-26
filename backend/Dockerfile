FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend:/app
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY agents ./agents
COPY governance ./governance
COPY config ./config

EXPOSE 8000
CMD ["sh", "-c", "cd /app && alembic -c /app/backend/alembic.ini upgrade head && python -m app.seed && uvicorn app.main:app --app-dir /app/backend --host 0.0.0.0 --port 8000"]
