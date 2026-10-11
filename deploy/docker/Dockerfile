FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY app ./app
COPY data ./data
COPY evals ./evals
COPY scripts ./scripts

EXPOSE 8000

# Aplica las migraciones pendientes de Postgres (idempotente) antes de levantar la API.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
