# VethisAgent

Backend del agente conversacional asesor de una tienda veterinaria (proyecto **Vethis**,
Curso de Agentes de IA — UTEC Posgrado). El agente ayuda al cliente a elegir el alimento
adecuado para su mascota (según especie, edad, peso, condición y presupuesto) y comparte
el link del producto en la tienda web, donde el cliente completa la compra.

Este repo es exclusivamente el **backend**: expone el agente como una API con FastAPI para
que cualquier tienda pueda integrarlo en su propio chat web (frontend).

> Estado actual: scaffold del proyecto + entrypoint de FastAPI (`/health`). El grafo del
> agente, las tools, la memoria y la conexión a Postgres/Redis/Ollama todavía no están
> implementadas — ver [Roadmap](#roadmap).

## Stack (100% open source)

| Capa | Tecnología |
|---|---|
| API | FastAPI + Uvicorn |
| Orquestación del agente | LangGraph + LangChain |
| LLM y embeddings | Ollama (ej. `llama3.1:8b` para chat, `nomic-embed-text` para embeddings) |
| Memoria de sesión (corto plazo) | Redis |
| Memoria de cliente (largo plazo) + catálogo vectorizado | PostgreSQL + pgvector |
| Observabilidad | Langfuse + OpenTelemetry |
| Validación de datos | Pydantic |

No se usa ningún servicio propietario (sin OpenAI, sin AWS Bedrock): todo corre
self-hosted, en local o en tu propia infraestructura.

## Arquitectura del agente

El flujo del agente es un grafo de estados (no una cadena lineal), pensado así porque la
regla "síntoma médico ⇒ derivar al veterinario antes de recomendar" necesita poder
interrumpir el flujo:

```
perfilar → buscar → recomendar
              ↓
           derivar (si hay síntoma o condición médica)
```

- **Conocimiento**: catálogo de alimentos (`data/catalogo/`) + guías de nutrición, reglas
  de derivación, transición de alimentos y políticas de la tienda (`data/conocimiento/`).
- **Tools**: `buscar_alimentos`, `consultar_disponibilidad`, `calcular_racion`,
  `derivar_veterinario` (`app/tools/`).
- **Memoria**: corto plazo por sesión con el checkpointer de LangGraph sobre Redis
  (`langgraph-checkpoint-redis`, `app/memory/short_term/`; `thread_id == session_id`, TTL 30
  min); largo plazo por cliente en Postgres (`app/memory/long_term/`, pendiente).
- **Guardrails y evals**: reglas duras de derivación y anclaje al catálogo
  (`app/guardrails/`), set dorado de pruebas (`evals/`).

Detalle completo del diseño en `../Asesor_de_ventas.html` (blueprint de las 5 capas).

## Estructura del proyecto

```
project-agent/
├── app/
│   ├── main.py              # entrypoint de FastAPI
│   ├── api/v1/               # routers y dependencias HTTP
│   ├── core/                  # settings / configuración
│   ├── agent/                 # prompts del sistema (grafo LangGraph propio: pendiente)
│   ├── tools/                  # tools del agente (funciones puras + wrappers @tool de LangChain)
│   ├── guardrails/              # validaciones de entrada/salida
│   ├── scoring/                  # re-ranking y feedback
│   ├── memory/                    # short_term (checkpointer LangGraph+Redis) / long_term (Postgres)
│   ├── models/                     # esquemas Pydantic
│   ├── services/                    # lógica de negocio
│   ├── db/                           # cliente Postgres+pgvector (Redis lo maneja el checkpointer)
│   └── observability/                 # Langfuse / OTel
├── data/                                # catálogo, conocimiento, historial, memoria, derivaciones
├── etl/                                  # export catálogo → Pydantic → embeddings
├── evals/                                 # set dorado de pruebas
├── tests/{unit,integration}/
├── deploy/{docker,nginx,jenkins}/
├── scripts/
├── docker-compose.yml
├── .dockerignore
├── requirements.txt
└── .env.example
```

## Requisitos previos

- [Docker](https://www.docker.com/) + Docker Compose (opción recomendada, levanta todo el stack), **o**
- Python 3.11+, [Ollama](https://ollama.com), PostgreSQL 15+ con `pgvector` y Redis **8+** (o `redis-stack`, necesita el módulo RediSearch para el checkpointer) instalados a mano (opción manual)

## Cómo levantar el proyecto

### Opción A: todo con Docker Compose (recomendada)

Levanta Postgres+pgvector, Redis, Ollama (con descarga automática de los modelos) y la
API en un solo comando — todo open source, nada de servicios propietarios.

```bash
cp .env.example .env   # opcional: ajustar modelos, orígenes CORS, etc.
docker compose up -d --build
```

Esto arranca 4 servicios:

| Servicio | Rol | Puerto |
|---|---|---|
| `postgres` | PostgreSQL + pgvector (catálogo, memoria largo plazo) | 5432 |
| `redis` | memoria de sesión (corto plazo) | 6379 |
| `ollama` | LLM + embeddings | 11434 |
| `ollama-pull` | job de un solo uso que descarga los modelos configurados y termina | — |
| `api` | backend FastAPI (VethisAgent) | 8000 |

Ver logs / estado:

```bash
docker compose logs -f api
docker compose logs -f ollama-pull   # confirmar que terminó de descargar los modelos
```

Apagar todo (los datos persisten en volúmenes):

```bash
docker compose down
```

### Opción B: entorno local sin Docker para la API

Útil para desarrollar la API con recarga automática (`--reload`) fuera de un contenedor.

**1. Crear entorno virtual e instalar dependencias**

```bash
cd project-agent
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**2. Levantar los servicios de soporte** (Postgres, Redis, Ollama) — con Docker Compose,
solo esos tres:

```bash
docker compose up -d postgres redis ollama ollama-pull
```

O, si prefieres instalarlos nativamente: `ollama serve` + `ollama pull llama3.1:8b` +
`ollama pull nomic-embed-text` para Ollama, y Postgres/Redis instalados localmente.

**3. Configurar variables de entorno**

```bash
cp .env.example .env
# ajustar OLLAMA_BASE_URL, POSTGRES_DSN, REDIS_URL si usaste otros puertos/hosts
```

**4. Ejecutar la API**

```bash
uvicorn app.main:app --reload
```

### Probar que responde

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Documentación interactiva (Swagger) disponible en `http://localhost:8000/docs`.

## Tests

```bash
pytest
```

## Evaluación de calidad del agente (DeepEval + GEval)

Además de los tests funcionales, `evals/` mide la **calidad conversacional** del agente
con 9 métricas evaluadas por un LLM-juez ([DeepEval](https://github.com/confident-ai/deepeval)
+ `GEval`): correctitud, relevancia, completitud, empatía, seguridad, adherencia al rol,
descubrimiento de necesidades, calidad de la recomendación y fidelidad al contexto.

- `evals/casos/casos_prueba.py` — set de casos de ejemplo (flujo feliz, perfil
  incompleto, síntoma médico, preferencia "sin pollo", cliente preocupado, pregunta
  fuera de rol, multi-turno con precio real, pregunta irrelevante), cada uno con su
  contexto de referencia (datos reales del catálogo o la regla de negocio esperada).
- `evals/metrics.py` — las 9 métricas `GEval`. El juez reutiliza el mismo `LLM_PROVIDER`
  del `.env` (Ollama por defecto, sin costo); `EVAL_JUDGE_MODEL` permite usar un modelo
  distinto solo para juzgar sin tocar el modelo que sirve el chat real.
- `evals/run_evals.py` — corre cada caso contra el **agente real** (no respuestas
  precocinadas), mide las 9 métricas sobre cada uno, imprime el reporte en consola y lo
  guarda como JSON en `evals/reportes/`.

```bash
docker compose exec api python -m evals.run_evals
```

> Con un modelo local pequeño (ej. `llama3.1:8b`) esto puede tardar varios minutos: cada
> caso pasa por el agente completo (tool-calling incluido) y luego por 9 llamadas al
> juez. El primer `buscar_alimentos` de la corrida además calienta el cache de
> embeddings del catálogo.

## Roadmap

- [x] `app/core/config.py` — settings con Pydantic leyendo `.env` (incluye `LLM_PROVIDER`: ollama/openai/anthropic)
- [x] `app/api/v1/routes` — endpoint de chat (`POST /api/v1/chat`)
- [x] `app/memory/short_term` — memoria de sesión con el checkpointer de LangGraph sobre
      Redis (`langgraph-checkpoint-redis`): el agente persiste/recarga el estado del grafo
      por `thread_id == session_id`, con TTL de 30 min y refresh en cada lectura. Requiere
      Redis con RediSearch (`redis:8` / `redis-stack`)
- [x] `app/tools` — `buscar_alimentos` (semántica con Ollama + filtros duros + scoring),
      `consultar_disponibilidad`, `calcular_racion`, `derivar_veterinario`, sobre un
      **catálogo de muestra** de 20 SKUs (`data/catalogo/alimentos.json`) — pendiente
      reemplazar por el export real de 1,008 variantes
- [x] `deploy/docker` — Dockerfile + docker-compose para todo el stack
- [x] `app/tools/langchain_tools.py` — las tools conectadas al chat vía function-calling,
      usando `create_agent` de LangChain (`langchain==1.4.0`) sobre `ChatOllama` /
      `ChatOpenAI` / `ChatAnthropic` según `LLM_PROVIDER`
- [ ] `app/agent/graph` — grafo LangGraph propio (perfilar → buscar → recomendar |
      derivar) como maquina de estados explicita; hoy el agente decide libremente qué
      tool llamar (ReAct genérico vía `create_agent`), no sigue ese flujo fijo
- [ ] `app/memory/long_term` — perfil de cliente en Postgres
- [ ] `app/guardrails` — reglas de derivación y anclaje al catálogo forzadas en código
      (hoy dependen de que el LLM siga el system prompt, no de una validación dura)
- [x] `evals/` — 9 métricas de calidad conversacional (DeepEval + `GEval`), corridas
      contra el agente real; falta el "set dorado" de aserciones duras del blueprint
      (evals.py con asserts en Python, ej. "todo SKU citado existe en el catálogo")
- [ ] `app/tools/scoring.py: registrar_feedback` — mecanismo listo, pero sin ningún flujo
      que lo dispare al cerrar sesión todavía
