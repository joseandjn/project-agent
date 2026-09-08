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
    end

    subgraph apic["Contenedor api · FastAPI + uvicorn"]
        direction TB
        route["POST /api/v1/chat<br/>app/api/v1/routes/chat.py"]
        health["GET /health"]
        gen["generate_reply(mensaje, session_id)<br/>app/services/llm_client.py"]
        precheck["Pre-chequeo de tarjeta<br/>app/guardrails/pii.py"]

        subgraph agente["Agente — LangChain create_agent (ReAct)"]
            direction TB
            mw["PIIMiddleware<br/>email/tel: redact — tarjeta: block"]
            model["Chat model<br/>get_chat_model() según LLM_PROVIDER"]
            subgraph tools["Tools — build_tools(session_id)"]
                direction LR
                t1["buscar_alimentos"]
                t2["consultar_disponibilidad"]
                t3["calcular_racion"]
                t4["derivar_veterinario"]
            end
        end

        cp["AsyncShallowRedisSaver<br/>checkpointer — thread_id = session_id — TTL 30 min"]
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
        pg[("PostgreSQL + pgvector<br/>memoria de largo plazo")]
    end

    subgraph pend["Pendiente (blueprint, sin código)"]
        direction TB
        lg["Grafo LangGraph explícito<br/>perfilar → buscar → recomendar | derivar"]
        obs["Observabilidad<br/>Langfuse — OpenTelemetry"]
        gw["Gateway nginx — CI Jenkins — canary"]
        etl["ETL de catálogo<br/>export BD → Pydantic → embeddings"]
        longmem["Memoria de largo plazo<br/>perfil de cliente"]
    end

    web -->|"HTTP — mensaje, session_id"| route
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

    gen -.-> obs
    agente -.-> lg
    fs -.-> etl
    longmem -.-> pg
    gen -.-> longmem

    classDef pendiente fill:#f4f4f4,stroke:#999,stroke-dasharray:4,color:#555;
    class lg,obs,gw,etl,longmem,pg pendiente;
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

    W->>R: mensaje, session_id
    R->>G: generate_reply(mensaje, session_id)
    G->>P: contiene_numero_de_tarjeta(mensaje)?
    alt hay número de tarjeta
        P-->>W: respuesta fija (no entra al agente ni a Redis)
    else sin tarjeta
        G->>A: ainvoke(messages, thread_id = session_id)
        A->>CP: cargar último checkpoint de la sesión
        CP->>RE: GET checkpoint de session_id
        RE-->>A: historial del grafo
        Note over A,M: PIIMiddleware redacta email/teléfono antes del modelo
        A->>M: prompt + historial + tools
        M->>T: tool call (p. ej. buscar_alimentos)
        T->>FS: catálogo / conocimiento / feedback
        T-->>M: resultado
        M-->>A: respuesta final
        A->>CP: guardar estado nuevo (redactado)
        CP->>RE: SET checkpoint de session_id (TTL 30 min)
        A-->>G: último mensaje
        G-->>W: respuesta, session_id
    end
```

---

## Despliegue (`docker-compose.yml`)

| Contenedor | Imagen | Rol | Puerto |
|---|---|---|---|
| `vethis-api` | build local (`python:3.11-slim`) | backend FastAPI | 8000 |
| `vethis-redis` | `redis:8-alpine` | memoria de sesión (checkpointer, necesita RediSearch) | 6379 |
| `vethis-ollama` | `ollama/ollama` | embeddings (y chat si `LLM_PROVIDER=ollama`) | 11434 |
| `vethis-ollama-pull` | `ollama/ollama` | job de un solo uso: descarga los modelos | — |
| `vethis-postgres` | `pgvector/pgvector:pg16` | memoria de largo plazo — **levanta pero la app no se conecta** | 5432 |

Sin gateway, sin CI, sin orquestador: todo en una máquina con `docker compose`.
