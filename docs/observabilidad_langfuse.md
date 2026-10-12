# Diseño · Observabilidad con Langfuse

Estado: **implementado** (fases 1 y 2, salvo los eventos de reglas de negocio, que todavía
no existen). Quedan abiertas las [Preguntas abiertas](#preguntas-abiertas) 1–3; ninguna
bloquea el uso.

Objetivo: ver qué hace el agente en cada turno (qué tools llamó, con qué argumentos, qué
devolvieron), cuánto cuesta cada turno y cada tienda, y dónde falla.

Es la base de otras dos mejoras: [`feedback_cliente.md`](feedback_cliente.md) (el voto se
guarda como *score* de la traza) y [`streaming.md`](streaming.md) (mide la espera que
percibe el cliente). Va primero.

Decisión ya tomada con el usuario: **Langfuse Cloud**.

---

## Punto de partida

| Pieza | Estado actual |
|---|---|
| `requirements.txt` | `langfuse==2.51.3` (SDK v2, sin usar), `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`. |
| `app/core/config.py` / `.env.example` | `LANGFUSE_HOST=http://localhost:3000` (pensado para self-hosted), `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`. |
| `docs/arquitectura.md` | Langfuse / OpenTelemetry figura como **pendiente**. |

---

## Decisiones

| # | Decisión | Alternativa descartada | Por qué |
|---|---|---|---|
| O1 | **Langfuse Cloud**, región elegida según dónde estén las tiendas (EU o US). | Self-hosted | Langfuse v3+ self-hosted necesita Postgres, ClickHouse, Redis y almacenamiento tipo S3. Es mucha operación para el tamaño actual. |
| O2 | Actualizar al **SDK actual de Langfuse** (v4 al escribir esto, basado en OpenTelemetry) y su integración con LangChain (callback handler). | Seguir con el SDK v2 | La v2 está discontinuada. Las versiones nuevas usan OpenTelemetry, que ya está en las dependencias. |
| O3 | **Enmascarar datos personales antes de enviar** a Langfuse, con la función `mask` del cliente y `redactar_pii` (`app/guardrails/pii.py`). | Enviar el texto tal cual | Con Cloud, el contenido sale a un tercero. El email y el teléfono ya se redactan en el agente, pero el bloque `<perfil_cliente>` y los mensajes viajan en las trazas. |
| O4 | Si Langfuse no está configurado o falla, **el chat sigue funcionando** sin trazas. | Fallar el request | La observabilidad no puede tirar el producto. El SDK envía en segundo plano y en lotes. |

---

## Qué se traza

- **Una traza por turno** de `/chat` (y de `/chat/stream`, cuando exista), con las llamadas
  al LLM, las tools (argumentos y resultados), los tokens, el costo y la latencia de cada
  paso.
- **Atributos de la traza**, sacados del `AuthContext`, nunca del body:
  - `session_id` = `thread_id` (`{tienda_id}:{session_id}`), que agrupa la conversación;
  - `user_id` = `cliente_id` (UUID interno, no el `external_id` de la tienda); nada si la
    sesión es anónima;
  - `tienda_id` como metadato o tag, para filtrar y calcular el costo por tienda;
  - `release` / versión del prompt, para comparar antes y después de un cambio.
- **Trazas propias para la memoria:** el extractor (`consolidar`) y el sweeper, con la
  misma `session_id`, para medir lo que cuesta la memoria de largo plazo.
- **Intervenciones de los guardrails** (PII, y las reglas de negocio de
  [`reglas_de_negocio_en_codigo.md`](reglas_de_negocio_en_codigo.md) cuando existan) como
  eventos de la traza.

---

## Dónde se conecta

```
app/observability/langfuse.py   # cliente singleton, mask, flush/shutdown, helpers de atributos
app/services/llm_client.py      # el callback handler en el config de agent.ainvoke / astream
app/memory/long_term/*.py       # spans del extractor y del sweeper
app/main.py                     # lifespan: crear el cliente; al apagar, flush
```

---

## Configuración

- `LANGFUSE_HOST` pasa a la URL de Cloud de la región elegida.
- `LANGFUSE_ENABLED` (por defecto `false` en tests y evals; ver pregunta abierta 3).
- `LANGFUSE_SAMPLE_RATE` (por defecto `1.0`), por si el volumen crece.
- Opcional: `LANGFUSE_ENVIRONMENT` (`local`, `docker`, `prod`).

---

## Privacidad

- **Enmascarado (O3):** la función `mask` redacta email, teléfono y tarjeta de todo lo que se
  envía.
- **Borrado:** `DELETE /api/v1/memoria` hoy borra el perfil, pero las trazas del cliente
  siguen en Langfuse. Opciones:
  - una retención corta configurada en el proyecto de Langfuse;
  - borrar las trazas por `user_id` con la API de Langfuse cuando el cliente pide el
    borrado.

  Ver pregunta abierta 2.
- `docs/vulnerabilidades.md` y `docs/arquitectura.md` se actualizan: Langfuse pasa a ser un
  servicio externo que recibe datos.

---

## Pruebas

- Unitarias de `mask` y de los atributos de la traza (con el cliente deshabilitado o falso).
- Una prueba de que el chat responde aunque Langfuse falle o no esté configurado.

---

## Fases

1. ✅ SDK actualizado (`langfuse==4.15.6`), cliente con `mask` y trazas de `/chat` con
   atributos por tienda, sesión y cliente.
2. ✅ Trazas de la memoria: cada `consolidar` (disparado por turnos o por el sweeper) es una
   traza `consolidar_memoria` con la llamada al extractor. Los middlewares de PII aparecen
   como pasos de la traza. Los eventos de las reglas de negocio se suman cuando existan.
3. ✅ Documentación: `README.md`, `arquitectura.md`, `vulnerabilidades.md`, `.env.example`.

---

## Implementación

| Pieza | Dónde |
|---|---|
| Cliente singleton, `enmascarar`, `trazar`, `callbacks`, `cerrar_langfuse` | `app/observability/langfuse.py` |
| Traza `chat` por turno (entrada y salida) | `app/api/v1/routes/chat.py` |
| Callbacks del agente (LLM, tools, middlewares) | `app/services/llm_client.py` (`generate_reply`) |
| Traza `consolidar_memoria` + callbacks del extractor | `app/memory/long_term/consolidacion.py`, `extractor.py` |
| Inicio y flush al apagar | `app/main.py` (lifespan) |
| Settings | `LANGFUSE_ENABLED`, `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_SAMPLE_RATE`; el `environment` de Langfuse es `ENVIRONMENT` |
| Tests | `tests/unit/test_observabilidad.py`: exportador de OpenTelemetry en memoria, sin red |

**Desvío respecto del diseño:** `LANGFUSE_ENVIRONMENT` no se agregó; se reutiliza
`ENVIRONMENT`, que ya existía. La versión del release se puede pasar con la variable
`LANGFUSE_RELEASE`, que el SDK lee sola.

---

## Preguntas abiertas

1. **Región de Langfuse Cloud:** ¿EU o US? Depende de dónde estén las tiendas y de qué
   exige la ley de datos personales que aplique (en Perú, la Ley 29733).
2. **Retención de trazas:** ¿cuánto tiempo se guardan? ¿Se borran las trazas de un cliente
   cuando pide `DELETE /memoria`?
3. **¿Trazar también los evals y el red team?** Útil para comparar modelos, pero mezcla
   datos de prueba con datos reales. Si se hace, que sea en otro proyecto o entorno de
   Langfuse.
