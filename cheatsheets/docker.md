# Cheatsheet · Docker

Operar VethisAgent con `docker compose`. Ejecutá todo desde `project-agent/` (donde está el
`docker-compose.yml`).

---

## 0 · Requisitos

En macOS necesitás **Docker Desktop corriendo** (el daemon). Si `docker ps` falla con
`Cannot connect to the Docker daemon`:

```bash
open -a Docker
# esperar a que arranque:
until docker info >/dev/null 2>&1; do sleep 2; done; echo "Docker listo"
```

---

## 1 · Levantar el stack

```bash
# LLM_PROVIDER=openai/anthropic  -> Ollama solo se usa para embeddings.
# Este override evita que el job ollama-pull descargue llama3.1:8b (~4.7 GB) al pedo:
OLLAMA_CHAT_MODEL=nomic-embed-text docker compose up -d --build

# LLM_PROVIDER=ollama -> sí querés el modelo de chat, levantá normal:
docker compose up -d --build
```

Primera vez: construye la imagen `api` (pip install) + baja postgres/redis/ollama + el job
`ollama-pull` descarga los modelos. Puede tardar varios minutos.

### Los 5 servicios

| Servicio | Rol | Puerto |
|---|---|---|
| `api` | backend FastAPI (VethisAgent) | 8000 |
| `postgres` | PostgreSQL + pgvector (memoria largo plazo — aún no conectada) | 5432 |
| `redis` | memoria de sesión: checkpointer LangGraph (imagen `redis:8`, con RediSearch) | 6379 |
| `ollama` | embeddings (y chat si `LLM_PROVIDER=ollama`) | 11434 |
| `ollama-pull` | job de un solo uso: descarga los modelos y termina | — |

### Comprobar que responde

```bash
curl http://localhost:8000/health           # {"status":"ok"}
open http://localhost:8000/docs             # Swagger

curl -s -XPOST localhost:8000/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"mensaje":"hola, alimento para gato adulto?","session_id":"test-1"}'
```

Multi-turno (misma `session_id` = misma conversación, la memoria la mantiene Redis):

```bash
SID="demo-$(date +%s)"
curl -s -XPOST localhost:8000/api/v1/chat -H 'Content-Type: application/json' \
  -d "{\"mensaje\":\"Tengo un gato llamado Miso, 4 kg\",\"session_id\":\"$SID\"}"
curl -s -XPOST localhost:8000/api/v1/chat -H 'Content-Type: application/json' \
  -d "{\"mensaje\":\"Como se llama mi gato?\",\"session_id\":\"$SID\"}"
```

---

## 2 · Actualizar tras un cambio

| Cambiaste… | Comando |
|---|---|
| Código Python (`app/`, `evals/`) | `docker compose up -d --build api` |
| `.env` | `docker compose up -d --force-recreate api` (no necesita `--build`) |
| `requirements.txt` | `docker compose build api && docker compose up -d api` |
| `docker-compose.yml` | `docker compose up -d` (agregá `--force-recreate` si tocaste un servicio con datos) |
| Nada arranca / estado raro | `docker compose down && docker compose up -d --build` |

> **Nota**: el código va *copiado dentro de la imagen* `api`, no montado. Por eso todo
> cambio de `.py` necesita `--build`. Para iterar sin rebuild, agregá al servicio `api`:
> ```yaml
>     volumes:
>       - ./app:/app/app
>     command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
> ```

Verificar que tomó el cambio:

```bash
docker compose logs -f api
docker compose exec api sh -c 'echo $LLM_PROVIDER $OPENAI_CHAT_MODEL'
docker compose exec api pip show langgraph-checkpoint-redis | head -2
```

---

## 3 · Estado y logs

```bash
docker compose ps                        # qué está corriendo + health
docker compose logs -f api               # seguir logs del api
docker compose logs --tail 50 redis      # últimas 50 líneas de redis
docker compose logs ollama-pull          # confirmar que bajó los modelos
docker stats --no-stream                 # CPU / RAM por contenedor
```

---

## 4 · Ejecutar cosas dentro de un contenedor

```bash
# tests
docker compose exec api python -m pytest -q

# evals (1 caso, sin gastar tokens de más)
docker compose exec api python -m evals.run_evals --caso fuera-de-rol-descuento
docker compose exec api python -m evals.run_evals            # todos

# shell dentro del api
docker compose exec api sh

# python one-liner
docker compose exec api python -c "from app.core.config import get_settings; print(get_settings())"
```

Los reportes de evals quedan en `evals/reportes/` (está montado: `./evals/reportes:/app/evals/reportes`).

---

## 5 · Inspeccionar los datos

### Redis (checkpointer de sesión)

```bash
docker compose exec redis redis-cli DBSIZE
docker compose exec redis redis-cli --scan --pattern 'checkpoint*' | head
docker compose exec redis redis-cli --scan --pattern 'checkpoint:demo-*' \
  | head -1 | xargs -I{} docker compose exec -T redis redis-cli TTL "{}"
docker compose exec redis redis-cli MODULE LIST | grep -A1 search   # confirmar RediSearch
docker compose exec redis redis-cli FLUSHDB                          # borrar TODAS las sesiones
```

### Postgres

```bash
docker compose exec postgres psql -U vethis -d vethis -c '\dt'
docker compose exec postgres psql -U vethis -d vethis
```

### Ollama

```bash
docker compose exec ollama ollama list                              # modelos descargados
curl -s localhost:11434/api/tags | python3 -m json.tool
docker compose exec ollama ollama pull nomic-embed-text             # bajar un modelo a mano
```

---

## 6 · Apagar y limpiar

```bash
docker compose stop                 # pausar (mantiene contenedores y datos)
docker compose down                 # eliminar contenedores (los volúmenes PERSISTEN)
docker compose down -v              # + borrar volúmenes (Postgres, Redis, modelos Ollama)
docker compose down --rmi local     # + borrar la imagen 'api' construida

docker system df                    # cuánto disco ocupa Docker
docker system prune -f              # limpiar imágenes/redes/caché sin usar (cuidado)
```

---

## 7 · Troubleshooting

| Síntoma | Causa / arreglo |
|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop apagado → `open -a Docker` |
| `api` sube pero `/chat` da 500 `LLM_PROVIDER no soportado` | typo en `.env` (`openai`/`ollama`/`anthropic`) → corregir + `docker compose up -d --force-recreate api` |
| `unknown command 'FT.CREATE'` en logs de `api` al arrancar | `redis` no es la imagen `redis:8` (o `redis-stack`); el checkpointer necesita RediSearch → `docker compose up -d --force-recreate redis` con la imagen correcta en el compose |
| `bind: address already in use` (8000/5432/6379/11434) | otro proceso usa el puerto → `lsof -i :8000` y matarlo, o cambiar el mapeo en `docker-compose.yml` |
| `ollama-pull` tarda muchísimo / falla | está bajando `llama3.1:8b` (~4.7 GB) que no usás → relevantá con `OLLAMA_CHAT_MODEL=nomic-embed-text docker compose up -d` |
| Cambié código y no se refleja | falta `--build`: `docker compose up -d --build api` |
| Build de `api` usa caché vieja | `docker compose build --no-cache api` |
| Todo roto, empezar de cero | `docker compose down -v && OLLAMA_CHAT_MODEL=nomic-embed-text docker compose up -d --build` |

---

## 8 · Sin Docker para la API (modo local)

Levantar solo los servicios de soporte en Docker y correr `uvicorn` en el venv:

```bash
docker compose up -d postgres redis ollama ollama-pull
.venv/bin/uvicorn app.main:app --reload      # usa localhost:6379 / 5432 / 11434
```

> El venv local necesita **Python 3.11+** y, por `asyncpg`, no siempre compila en 3.13:
> ver el README para el detalle. En Docker esto no pasa (imagen `python:3.11-slim`).
