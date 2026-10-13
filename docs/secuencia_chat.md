# Secuencia · Un mensaje del chat

Flujo completo de un mensaje desde el chat web (`vethis-chat`) hasta la respuesta del agente
por `POST /api/v2/chat`, y el voto 👍/👎 posterior. `/api/v1/chat` sigue el mismo flujo, con la
diferencia de que arma el agente en cada request.

![Secuencia de un mensaje del chat](img/secuencia_chat.png)

La imagen se generó desde el bloque Mermaid de abajo (fuente editable); para regenerarla:
`npx @mermaid-js/mermaid-cli -i secuencia.mmd -o docs/img/secuencia_chat.png -s 2 -b white`.

```mermaid
sequenceDiagram
    autonumber
    actor C as Cliente
    participant W as vethis-chat<br/>(Next.js)
    participant K as Caddy
    participant A as API FastAPI
    participant R as Redis
    participant P as PostgreSQL
    participant T as Clasificador<br/>de tema
    participant G as Agente<br/>(LangChain + LangGraph)
    participant L as OpenAI
    participant N as Neo4j
    participant F as Langfuse

    C->>W: escribe un mensaje
    W->>W: POST /api/chat (mismo origen)

    opt sin cookie o token por vencer (< 5 min)
        W->>K: POST /api/v1/auth/token (X-API-Key) o /auth/refresh
        K->>A: reenvía
        A->>R: rate limit (API key inválida por IP, sesiones por tienda)
        A->>P: valida la tienda · upsert del cliente
        A-->>W: JWT (tienda, sesión, cliente)
        W->>W: guarda el JWT en cookie httpOnly
    end

    W->>K: POST /api/v2/chat · Bearer JWT · {mensaje}
    K->>A: reenvía (HTTPS, body ≤ 64 KB)
    A->>A: valida JWT → tienda, sesión, cliente
    A->>R: rate limit (sesión, cliente, tienda/min y /día)
    alt límite excedido
        A-->>W: 429 + Retry-After
    end

    opt cliente identificado
        A->>P: lee el perfil (memoria de largo plazo)
    end
    A->>F: abre la traza "chat_v2" (id derivado del mensaje_id)
    A->>R: historial de la sesión (checkpoint)

    alt el mensaje trae un número de tarjeta
        A->>A: respuesta fija, no entra al agente
    else
        par clasificador y agente en paralelo
            A->>T: clasificar el último mensaje + contexto
            T->>L: salida estructurada (categoría)
            L-->>T: mascotas · conversacion · fuera de tema ...
        and
            A->>G: ainvoke(mensaje, contexto: sesión + perfil)
            G->>G: PII: redacta email/teléfono · prompt con el perfil
            loop hasta responder (máx. 8 llamadas al modelo, 60 s)
                G->>L: prompt + historial + tools
                L-->>G: tool calls o respuesta final
                opt tools pedidas por el modelo
                    G->>L: embeddings (buscar_alimentos)
                    G->>N: guía activa de la tienda (calcular_racion, consultar_guia)
                    G->>G: catálogo (consultar_disponibilidad, ver_ficha_producto)
                end
            end
            G->>R: guarda el checkpoint del turno
        end
        alt tema permitido (o el clasificador falló)
            G-->>A: respuesta del agente
        else fuera de tema · salud humana · malestar · riesgo
            A->>G: cancela el agente
            A->>R: borra el turno de la sesión (RemoveMessage)
            A->>A: respuesta fija (con líneas de ayuda si corresponde)
        end
    end

    A->>R: registra mensaje_id → sesión + SKUs del turno (TTL 24 h)
    A-->>W: {respuesta, session_id, mensaje_id}
    W-->>C: muestra la respuesta (markdown) + 👍/👎
    A-)F: envía la traza en segundo plano (PII enmascarada)

    opt cliente identificado y turno N (cada 5)
        A-)L: extractor de memoria (salida estructurada)
        A-)P: guarda una versión nueva del perfil
    end

    opt el cliente vota la respuesta
        C->>W: 👍 o 👎 (+ motivo opcional)
        W->>K: POST /api/v1/feedback · Bearer JWT
        K->>A: reenvía
        A->>R: rate limit · el mensaje_id es de esta sesión
        A->>P: guarda el voto (uno por mensaje)
        A-)F: score "feedback_cliente" en la traza del mensaje
        A-->>W: 204
    end
```

## Notas

- **La API key de la tienda** solo la usa el servidor de `vethis-chat`; el navegador ve
  una cookie `httpOnly` con el JWT.
- **El historial** vive en Redis por sesión (TTL 30 min). El chat solo manda el mensaje
  nuevo en cada turno.
- **Si una tool o el modelo se pasan de un límite** (llamadas, tiempo), el turno se borra de
  la sesión y el cliente recibe un mensaje fijo.
- **Si Neo4j no responde**, `calcular_racion` y `consultar_guia` usan la guía por defecto.
- **Consolidación por inactividad:** además del turno N, un proceso de fondo consolida las
  sesiones que llevan 25 minutos sin mensajes (no aparece en el diagrama).
