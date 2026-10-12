# Arquitectura de componentes · VethisAgent

Estado real del repo `project-agent` (backend del asesor de tienda veterinaria).
GitHub y varios editores renderizan Mermaid directo; si no, pegá el bloque en
<https://mermaid.live>.

- **Línea sólida / nodo blanco** = implementado y corriendo hoy.
- **Línea punteada / nodo gris** = diseñado en el blueprint, aún no en el código.

---

## Diagrama de componentes

```mermaid
flowchart TB
    subgraph cliente["Cliente"]
        web["Sitio web de la tienda<br/>widget de chat — fuera de este repo"]
        tback["Backend de la tienda<br/>guarda la API key — fuera de este repo"]
    end

    subgraph apic["Contenedor api · FastAPI + uvicorn"]
        direction TB
        authr["POST /api/v1/auth/token — /auth/refresh<br/>app/api/v1/routes/auth.py"]
        jwtdep["get_auth_context — valida JWT<br/>app/api/v1/dependencies/auth.py"]
        route["POST /api/v1/chat<br/>app/api/v1/routes/chat.py<br/>agente armado en cada request"]
        routev2["POST /api/v2/chat<br/>app/api/v2/routes/chat.py<br/>agente compartido (app/services/agente.py)<br/>sesión y perfil en context=Contexto"]
        health["GET /health"]
        gen["generate_reply(mensaje, thread_id)<br/>app/services/llm_client.py"]
        precheck["Pre-chequeo de tarjeta<br/>app/guardrails/pii.py"]

        subgraph agente["Agente — LangChain create_agent (ReAct)"]
            direction TB
            mw["PIIMiddleware<br/>email/tel: redact — tarjeta: block"]
            model["Chat model<br/>get_chat_model() según LLM_PROVIDER"]
            subgraph tools["Tools — build_tools(thread_id)"]
                direction LR
                t1["buscar_alimentos"]
                t2["consultar_disponibilidad"]
                t3["calcular_racion"]
                t4["derivar_veterinario"]
            end
        end

        cp["AsyncShallowRedisSaver<br/>checkpointer — thread_id = tienda:sesión — TTL 30 min"]

        subgraph longmem["Memoria de largo plazo — app/memory/long_term"]
            direction TB
            cons["consolidar(thread_id)<br/>cada 5 turnos (background) — sweeper por inactividad"]
            extr["extraer_perfil<br/>LLM con salida estructurada + PII + SKUs de tool calls"]
            memr["GET / DELETE /api/v1/memoria"]
        end
    end

    subgraph prov["Proveedor de LLM — LLM_PROVIDER"]
        direction TB
        ollama["Ollama — self-hosted<br/>llama3.1:8b (chat) — nomic-embed-text (embeddings)"]
        openai["OpenAI API<br/>gpt-4o-mini"]
        anthropic["Anthropic API<br/>claude-sonnet-5"]
    end

    subgraph datos["Datos"]
        direction TB
        redis[("Redis 8 + RediSearch<br/>memoria de sesión")]
        fs["Ficheros data/<br/>catálogo — conocimiento<br/>derivaciones/DER-*.json — scoring/feedback.json"]
        pg[("PostgreSQL + pgvector<br/>tiendas — clientes — perfiles (Alembic)")]
    end

    obs["Langfuse Cloud — servicio externo<br/>una traza por turno y por consolidación<br/>PII enmascarada — LANGFUSE_ENABLED"]

    subgraph pend["Pendiente (blueprint, sin código)"]
        direction TB
        lg["Grafo LangGraph explícito<br/>perfilar → buscar → recomendar / derivar"]
        gw["Gateway nginx — CI Jenkins — canary"]
        etl["ETL de catálogo<br/>export BD → Pydantic → embeddings"]
    end

    tback -->|"X-API-Key + external_user_id"| authr
    authr -->|"valida key / upsert cliente"| pg
    authr -->|"JWT"| tback
    tback -->|"JWT"| web
    web -->|"HTTP — Bearer JWT + mensaje"| route
    route --> jwtdep
    web -->|"HTTP — Bearer JWT + mensaje"| routev2
    routev2 --> jwtdep
    routev2 -->|"mismo agente, creado en el lifespan"| agente
    web -.-> gw -.-> route
    route --> gen
    gen --> precheck
    precheck -->|"sin tarjeta"| agente
    precheck -->|"tarjeta detectada: corta"| gen

    mw --> model
    model -->|"tool calling"| tools
    model ==>|"chat"| ollama
    model -.->|"si LLM_PROVIDER"| openai
    model -.->|"si LLM_PROVIDER"| anthropic

    agente <-->|"carga / guarda estado del grafo"| cp
    cp <--> redis

    t1 -->|"embeddings del query"| ollama
    t1 --> fs
    t2 --> fs
    t3 --> fs
    t4 -->|"escribe derivación"| fs

    route -->|"traza del turno + callbacks del agente"| obs
    cons -->|"traza de la consolidación"| obs
    agente -.-> lg
    fs -.-> etl
    route -->|"lee perfil → system prompt"| pg
    route -->|"turno N"| cons
    cons -->|"lee mensajes del checkpoint"| redis
    cons --> extr
    extr -->|"chat"| ollama
    cons -->|"guarda versión"| pg
    memr --> pg

    classDef pendiente fill:#f4f4f4,stroke:#999,stroke-dasharray:4,color:#555;
    class lg,gw,etl pendiente;
```

---

## Flujo de una petición `POST /api/v1/chat`

```mermaid
sequenceDiagram
    autonumber
    participant W as Sitio web
    participant R as chat.py
    participant G as generate_reply
    participant P as Guardrail PII
    participant A as Agente
    participant CP as Checkpointer
    participant RE as Redis
    participant M as Chat model
    participant T as Tools
    participant FS as data/

    W->>R: Authorization: Bearer JWT + mensaje
    alt JWT ausente, inválido o vencido
        R-->>W: 401
    end
    Note over R: get_auth_context: tienda, sesión y cliente salen del token
    opt cliente autenticado
        R->>R: leer_perfil(cliente_id) desde Postgres
    end
    R->>G: generate_reply(mensaje, thread_id, perfil)
    G->>P: contiene_numero_de_tarjeta(mensaje)?
    alt hay número de tarjeta
        P-->>W: respuesta fija (no entra al agente ni a Redis)
    else sin tarjeta
        G->>A: ainvoke(messages, thread_id)
        A->>CP: cargar último checkpoint de la sesión
        CP->>RE: GET checkpoint del thread_id
        RE-->>A: historial del grafo
        Note over A,M: PIIMiddleware redacta email/teléfono antes del modelo
        A->>M: prompt + historial + tools
        M->>T: tool call (p. ej. buscar_alimentos)
        T->>FS: catálogo / conocimiento / feedback
        T-->>M: resultado
        M-->>A: respuesta final
        A->>CP: guardar estado nuevo (redactado)
        CP->>RE: SET checkpoint del thread_id (TTL 30 min)
        A-->>G: último mensaje
        G-->>W: respuesta, session_id
    end
    opt cliente autenticado y turno N sin consolidar
        R-)R: BackgroundTask consolidar(thread_id) → extractor → perfil en Postgres
    end
```

---

## Despliegue (`docker-compose.yml`)

| Contenedor | Imagen | Rol | Puerto |
|---|---|---|---|
| `vethis-api` | build local (`python:3.11-slim`) | backend FastAPI; al arrancar corre `alembic upgrade head` | 8000 |
| `vethis-redis` | `redis:8-alpine` | memoria de sesión (checkpointer, necesita RediSearch) | 6379 |
| `vethis-ollama` | `ollama/ollama` | embeddings (y chat si `LLM_PROVIDER=ollama`) | 11434 |
| `vethis-ollama-pull` | `ollama/ollama` | job de un solo uso: descarga los modelos | — |
| `vethis-postgres` | `pgvector/pgvector:pg16` | tiendas y clientes (autenticación), perfiles de cliente (memoria de largo plazo) | 5432 |

Sin gateway, sin CI, sin orquestador: todo en una máquina con `docker compose`.
