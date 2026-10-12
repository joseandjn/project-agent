# Diseño · Respuesta en streaming

Estado: **propuesta de diseño, pendiente de las [Preguntas abiertas](#preguntas-abiertas).**
No hay nada implementado.

Objetivo: que el cliente no espere varios segundos sin ver nada mientras el agente llama a
las tools.

Decisión ya tomada con el usuario: el streaming va en **una API nueva**
(`POST /api/v1/chat/stream`), para no afectar el funcionamiento actual de `/chat`.

Relacionado: [`observabilidad_langfuse.md`](observabilidad_langfuse.md) (mide la latencia
antes y después) y [`feedback_cliente.md`](feedback_cliente.md) (el evento final trae el
`mensaje_id` para votar).

---

## Punto de partida

- `POST /api/v1/chat` devuelve la respuesta completa en JSON (`ChatResponse`) cuando el
  agente termina.
- Los guardrails de salida actúan sobre el **mensaje terminado**:
  - `PIIMiddleware` redacta email y teléfono (`app/guardrails/pii.py`);
  - el anclaje de precios y SKUs de
    [`reglas_de_negocio_en_codigo.md`](reglas_de_negocio_en_codigo.md) revisa la respuesta
    completa.

---

## Decisiones

| # | Decisión | Alternativa descartada | Por qué |
|---|---|---|---|
| S1 | Streaming en un **endpoint nuevo** con SSE (`text/event-stream`). `/chat` queda igual. | Cambiar `/chat` | Decisión del usuario: no afectar a las integraciones actuales. |
| S2 | En la API nueva, los **guardrails de salida siguen aplicando**. Se envían en vivo los **eventos de progreso** y el texto final **ya verificado**, en partes. | Tokens crudos del modelo | Separar el endpoint protege a `/chat`, pero no al cliente que use el nuevo. Los tokens crudos llegan antes de la redacción de PII y del anclaje de precios: el cliente vería un teléfono sin redactar o un precio sin verificar. Ver pregunta abierta 1. |
| S3 | La lógica común de los dos endpoints se extrae a **una función de servicio**. | Duplicarla en cada ruta | Así `/chat` y `/chat/stream` no se desincronizan (perfil, corte por tarjeta, memoria). |

---

## Contrato (SSE)

Mismo body y autenticación que `/chat`. Eventos:

```
event: progreso   data: {"etapa": "buscando_alimentos"}
event: progreso   data: {"etapa": "consultando_precio"}
event: texto      data: {"delta": "Para Rocky te recomiendo…"}
event: texto      data: {"delta": "…"}
event: fin        data: {"mensaje_id": "…", "session_id": "…"}
event: error      data: {"detalle": "…"}
```

- Las etapas de progreso salen de los eventos de inicio de cada tool (`astream` del agente).
  El texto es un mapeo fijo de nombre de tool a etapa: nunca se envían los argumentos ni los
  resultados de la tool.
- El texto se envía **después** de que el agente termina y pasan los guardrails de salida
  (S2), dividido en partes para que se vea fluido.

---

## Comportamiento compartido con `/chat`

- La función de servicio común (S3) lee el perfil, aplica el corte por tarjeta, construye
  el agente, registra el turno y dispara la consolidación.
- La consolidación de memoria se dispara **cuando termina el stream**, no al empezar.
- Si el cliente cierra la conexión a mitad del stream, el turno igual se completa y queda en
  el checkpoint, como en `/chat`.
- Respuesta fija de tarjeta bloqueada: un solo evento `texto` y `fin`.

---

## Infraestructura

- nginx (cuando se configure el gateway): `proxy_buffering off` y un timeout de lectura
  mayor para esta ruta.
- CORS: el widget de la tienda tiene que poder abrir el stream. `EventSource` no permite
  enviar headers, así que el widget usa `fetch` con lectura del stream para mandar el
  Bearer.

---

## Pruebas

Integración con `httpx` leyendo el stream y un modelo falso:
- orden de eventos `progreso → texto → fin`;
- el `mensaje_id` del `fin` sirve para votar;
- un texto con email llega redactado;
- la consolidación se dispara al terminar;
- `/chat` sigue pasando sus tests sin cambios.

---

## Fases

1. Extraer la función de servicio común y pasar `/chat` a usarla, sin cambiar su
   comportamiento.
2. `/chat/stream` con SSE, eventos de progreso y texto verificado, y sus pruebas.
3. Configuración de nginx cuando exista el gateway.

---

## Preguntas abiertas

1. **Streaming del texto:** se recomienda progreso en vivo y texto ya verificado (S2). ¿Te
   sirve, o en la API nueva quieres el texto token por token aunque la redacción de PII y el
   anclaje de precios lleguen tarde?
2. **Widget de las tiendas:** ¿quién lo mantiene? Si cada tienda tiene el suyo, hay que
   documentarles cómo leer el stream con `fetch`.
