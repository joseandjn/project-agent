# VethisAgent

Backend del agente conversacional asesor de una tienda veterinaria (proyecto **Vethis**,
Curso de Agentes de IA — UTEC Posgrado). El agente ayuda al cliente a elegir el alimento
adecuado para su mascota (según especie, edad, peso, condición y presupuesto) y comparte
el link del producto en la tienda web, donde el cliente completa la compra.

Este repo es exclusivamente el **backend**: expone el agente como una API con FastAPI para
que cualquier tienda pueda integrarlo en su propio chat web (frontend).

> Estado actual: agente con tools, memoria de sesión en Redis, memoria de largo plazo por
> cliente en Postgres, guardrail de PII y autenticación por tienda (JWT propio). Pendiente
> principal: grafo LangGraph propio — ver [Roadmap](#roadmap).

## Stack (100% open source)

| Capa | Tecnología |
|---|---|
| API | FastAPI + Uvicorn |
| Orquestación del agente | LangGraph + LangChain |
| LLM y embeddings | Ollama (ej. `llama3.1:8b` para chat, `nomic-embed-text` para embeddings) |
| Memoria de sesión (corto plazo) | Redis |
| Memoria de cliente (largo plazo) + catálogo vectorizado | PostgreSQL + pgvector |
| Tiendas, clientes y migraciones | PostgreSQL + SQLAlchemy (asyncpg) + Alembic |
| Autenticación | JWT propio (PyJWT), emitido con la API key de cada tienda |
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
  min); largo plazo por cliente en Postgres (`app/memory/long_term/`): un perfil
  estructurado que se consolida cada 5 turnos y al quedar la sesión inactiva, y se agrega
  al system prompt — ver [Memoria de largo plazo](#memoria-de-largo-plazo).
- **Guardrails y evals**: guardrail de PII con `PIIMiddleware` de LangChain
  (`app/guardrails/pii.py`); reglas duras de derivación y anclaje al catálogo (pendientes);
  set dorado de pruebas (`evals/`).

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
│   ├── db/                           # Postgres: modelos SQLAlchemy, sesión async y migraciones Alembic
│   └── observability/                 # Langfuse / OTel
├── data/                                # catálogo, conocimiento, historial, memoria, derivaciones
├── etl/                                  # export catálogo → Pydantic → embeddings
├── graph_neo4j/                           # experimento aislado: catálogo como grafo (no lo usa el agente)
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
cp .env.example .env   # completar JWT_SECRET (obligatorio, ver Opción B paso 3)
docker compose up -d --build
```

Esto arranca 4 servicios:

| Servicio | Rol | Puerto |
|---|---|---|
| `postgres` | PostgreSQL + pgvector (tiendas, clientes, memoria de largo plazo; catálogo pendiente) | 5432 |
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
# JWT_SECRET es obligatorio (minimo 32 bytes); generarlo con:
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**4. Crear el esquema de Postgres** (en Docker lo hace el contenedor `api` al arrancar)

```bash
alembic upgrade head
```

**5. Ejecutar la API**

```bash
uvicorn app.main:app --reload
```

### Probar que responde

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Documentación interactiva (Swagger) disponible en `http://localhost:8000/docs`.

## Autenticación (integrar una tienda)

El backend emite **su propio JWT**, así que funciona con cualquier tienda sin depender de
su sistema de login. Diseño completo: [`docs/memoria_largo_plazo.md`](docs/memoria_largo_plazo.md).

**1. Registrar la tienda** (una vez). Imprime la API key, que **solo se muestra esta vez**:

```bash
python -m scripts.crear_tienda "Mi Tienda"
# en Docker: docker compose exec api python -m scripts.crear_tienda "Mi Tienda"
```

**2. El backend de la tienda pide un token** cuando el usuario abre el chat. La API key
nunca debe llegar al navegador:

```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "X-API-Key: vth_..." -H "Content-Type: application/json" \
  -d '{"external_user_id": "u-123"}'   # {} => sesión anónima
# {"access_token":"eyJ...","token_type":"bearer","expires_in":3600,"session_id":"..."}
```

**3. El widget de chat usa el token.** La sesión y el cliente salen del token, no del body:

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer eyJ..." -H "Content-Type: application/json" \
  -d '{"mensaje": "Hola, tengo un gato adulto de 4 kg"}'
```

**4. Renovar antes de que venza** (`JWT_TTL_SECONDS`, 1 h por defecto). Devuelve un token
nuevo con la misma sesión: `POST /api/v1/auth/refresh` con `Authorization: Bearer eyJ...`.

> **Cambio incompatible:** `POST /api/v1/chat` ya no acepta `session_id` ni `cliente_id`
> en el body y responde `401` sin un token válido.

### `POST /api/v2/chat` (agente compartido)

Mismo contrato, autenticación, memoria y guardrails que `/api/v1/chat`; cambia cómo se crea
el agente. v1 arma el agente en cada request (tools con la sesión en un closure y el perfil
pegado al system prompt, ~8.5 ms de CPU por request). v2 lo crea **una vez al arrancar**
(`app/services/agente.py`) y lo que cambia por turno viaja en el contexto
(`agent.ainvoke(..., context=Contexto(thread_id, perfil))`, `app/agent/contexto.py`), que el
LLM no ve:

- `derivar_veterinario` lee el `thread_id` con `ToolRuntime` (`runtime.context`);
- el bloque `<perfil_cliente>` lo agrega un middleware `@dynamic_prompt`.

`/api/v1/chat` no cambia. En Langfuse, las trazas de v2 se llaman `chat_v2`, para comparar.

## Memoria de largo plazo

Solo para clientes autenticados (token con `external_user_id`). El agente recuerda a cada
cliente entre sesiones mediante un **perfil estructurado** en Postgres: mascotas,
condiciones, proteínas a evitar, presupuesto, preferencias, productos consultados y
derivaciones. No se guarda la transcripción. Diseño: [`docs/memoria_largo_plazo.md`](docs/memoria_largo_plazo.md).

- **Cuándo se guarda:** cada `MEMORIA_CONSOLIDAR_CADA_N_TURNOS` turnos (5), en segundo plano,
  y cuando la sesión lleva `MEMORIA_INACTIVIDAD_SEGUNDOS` (25 min) sin mensajes, antes de
  que Redis la borre.
- **Cómo:** una llamada al LLM con salida estructurada (`app/memory/long_term/extractor.py`)
  actualiza el perfil. No es una tool del agente. Los SKUs y las derivaciones salen de las
  tool calls, no del LLM. La PII se redacta antes de guardar.
- **Uso:** el perfil se agrega al system prompt como bloque `<perfil_cliente>`, y el agente
  confirma los datos con el cliente antes de usarlos.
- **Privacidad:** `GET /api/v1/memoria` muestra el perfil del cliente del token y
  `DELETE /api/v1/memoria` lo borra junto con su historial de versiones.

**Elegir el modelo del extractor** (`MEMORIA_MODEL`): `evals/run_evals_memoria.py` corre 7
casos con aserciones duras (hechos, actualización, no inventar, envenenamiento, PII) y mide
la latencia:

```bash
python -m evals.run_evals_memoria --repeticiones 3
python -m evals.run_evals_memoria --modelo qwen2.5:14b   # otro modelo del mismo LLM_PROVIDER
```

**Migraciones:** el esquema vive en `app/db/models.py` y las migraciones en
`app/db/migrations/versions/`. Para un cambio nuevo:
`alembic revision --autogenerate --rev-id 0002 -m "descripcion"` y luego `alembic upgrade head`.

## Desplegar una demo

- **Azure (VM + Docker Compose):** [`docs/despliegue_azure.md`](docs/despliegue_azure.md), con
  `docker-compose.prod.yml` (solo Caddy expone 80/443 con HTTPS; Postgres y Redis con
  contraseña y sin puertos públicos) y `deploy/env.prod.example`.
- **Railway:** [`docs/despliegue_railway.md`](docs/despliegue_railway.md).

En la nube no se usa Ollama: `LLM_PROVIDER=openai` y `EMBEDDING_PROVIDER=openai`.

## Observabilidad (Langfuse Cloud)

Una traza por turno de `/chat` (llamadas al LLM con tokens y costo, tools con argumentos y
resultados, guardrails) y una por cada consolidación de memoria. Cada traza lleva
`session_id = {tienda}:{sesión}`, `user_id = cliente_id` (nada si es anónimo) y la tienda
como metadato y tag `tienda:<id>`, para filtrar y ver el costo por tienda. Diseño:
[`docs/observabilidad_langfuse.md`](docs/observabilidad_langfuse.md).

Para prenderlo: crear un proyecto en [Langfuse Cloud](https://cloud.langfuse.com) y en `.env`:

```bash
LANGFUSE_ENABLED=true
LANGFUSE_HOST=https://cloud.langfuse.com      # EU; US: https://us.cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

Apagado por defecto (tests y evals no envían nada). Antes de enviar, email, teléfono y
tarjeta se enmascaran. Si Langfuse no responde, el chat sigue funcionando.

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

## Red teaming de seguridad (DeepTeam + OWASP ASI 2026)

`evals/red_team.py` ataca al **agente real** con [DeepTeam](https://github.com/confident-ai/deepteam)
contra el framework **OWASP Top 10 for Agentic Applications (ASI) 2026**: por cada categoría
(ASI01–ASI10) DeepTeam genera ataques adversarios (prompt injection, roleplay, jailbreaking
multi-turno, context poisoning, Base64/ROT13…), los lanza contra `generate_reply`, y un
LLM-juez decide si el agente resistió o fue vulnerado. Reutiliza `EVAL_JUDGE_MODEL` /
`LLM_PROVIDER` para el simulador y el juez.

```bash
docker compose exec api python -m evals.red_team --categoria ASI_01   # una categoría
docker compose exec api python -m evals.red_team --full --intensidad 2 # las 10 (lento/caro)
```

Sin argumentos corre ASI01, ASI03 y ASI06 (las de mayor riesgo según
`docs/vulnerabilidades.md`). Genera un JSON (formato DeepTeam) y un reporte Markdown legible
en `evals/reportes/redteam_*.md`.

## Experimento: grafo de catálogo (Neo4j)

`graph_neo4j/` modela `data/catalogo/alimentos.json` como grafo (producto ↔ especie,
etapa, tamaño de raza, proteína, tipo de alimento, ingredientes) para explorar consultas
tipo "alternativas que comparten ingredientes pero sin pollo". Es un módulo **aislado**:
no lo importa `app/` y el servicio `neo4j` no es dependencia de `api` en
`docker-compose.yml`. Ver [`graph_neo4j/README.md`](graph_neo4j/README.md) para el
modelo completo y cómo correrlo.

```bash
docker compose up -d neo4j
python -m graph_neo4j.load_catalogo
python -m graph_neo4j.queries
```

## Roadmap

- [x] `app/core/config.py` — settings con Pydantic leyendo `.env` (incluye `LLM_PROVIDER`: ollama/openai/anthropic)
- [x] `app/api/v1/routes` — endpoint de chat (`POST /api/v1/chat`)
- [x] `app/api/v2/routes` — `POST /api/v2/chat` con el agente compartido (creado una vez en
      el lifespan; sesión y perfil por `context`, no por closure)
- [x] **Autenticación** (Fase 1 de `docs/memoria_largo_plazo.md`) — JWT propio emitido con
      la API key de cada tienda (`POST /api/v1/auth/token`, `/auth/refresh`); `/chat` exige
      Bearer y saca sesión/cliente del token; `thread_id = {tienda}:{sesión}`; tablas
      `tiendas` / `clientes` en Postgres con migraciones Alembic; `scripts/crear_tienda.py`
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
- [x] `app/observability` — trazas en Langfuse Cloud (SDK v4 sobre OpenTelemetry): una por
      turno de `/chat` y por consolidación de memoria, con sesión, cliente y tienda, PII
      enmascarada; apagado salvo `LANGFUSE_ENABLED=true`
- [ ] `app/agent/graph` — grafo LangGraph propio (perfilar → buscar → recomendar |
      derivar) como maquina de estados explicita; hoy el agente decide libremente qué
      tool llamar (ReAct genérico vía `create_agent`), no sigue ese flujo fijo
- [x] `app/memory/long_term` — perfil de cliente en Postgres (Fase 2 de
      `docs/memoria_largo_plazo.md`): extractor LLM con salida estructurada, consolidación
      cada 5 turnos + sweeper por inactividad, `GET`/`DELETE /api/v1/memoria`, eval del
      extractor (`evals/run_evals_memoria.py`)
- [~] `app/guardrails` — hecho: **guardrail de PII** (`app/guardrails/pii.py`, `PIIMiddleware`
      de LangChain): número de tarjeta ⇒ bloquea antes del agente; email y móvil peruano ⇒
      redactados en entrada/salida (no llegan al LLM ni al checkpointer). Pendiente: reglas
      de derivación y anclaje al catálogo forzadas en código (hoy dependen del system prompt)
- [x] `evals/` — 9 métricas de calidad conversacional (DeepEval + `GEval`), corridas
      contra el agente real; falta el "set dorado" de aserciones duras del blueprint
      (evals.py con asserts en Python, ej. "todo SKU citado existe en el catálogo")
- [ ] `app/tools/scoring.py: registrar_feedback` — mecanismo listo, pero sin ningún flujo
      que lo dispare al cerrar sesión todavía
