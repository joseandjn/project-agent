# Diseño · Feedback del cliente

Estado: **propuesta de diseño, pendiente de las [Preguntas abiertas](#preguntas-abiertas).**
No hay nada implementado.

Objetivo: que el cliente pueda votar cada respuesta (👍/👎, con un motivo opcional) para:

- encontrar las malas respuestas y convertirlas en casos de eval;
- alimentar el ranking de productos con una señal real, por tienda.

Depende de [`observabilidad_langfuse.md`](observabilidad_langfuse.md): el voto se envía a
Langfuse como *score* de la traza de esa respuesta, así cada 👎 lleva a la conversación
completa.

Decisión ya tomada con el usuario: **motivo opcional**.

---

## Punto de partida

| Pieza | Estado actual |
|---|---|
| `app/tools/scoring.py` | `registrar_feedback(sku, acierto)` y `calcular_confianza_feedback()` (Laplace). El ranking de `buscar_alimentos` le da peso 0.3, pero **nada llama a `registrar_feedback`**. |
| `data/scoring/feedback.json` | Común a todas las tiendas y sin control de escrituras simultáneas. |
| `POST /api/v1/chat` | `ChatResponse{respuesta, session_id}`, sin id de mensaje. |
| `docs/vulnerabilidades.md` (ASI06) | Pendiente: "el gate de solo feedback real". Hoy cualquier voto movería el ranking. |

---

## Decisiones

| # | Decisión | Alternativa descartada | Por qué |
|---|---|---|---|
| F1 | El feedback se guarda en **Postgres** (tabla nueva, migración de Alembic) **y** se envía a Langfuse como score. | Solo Langfuse / seguir con `feedback.json` | Postgres es la fuente de verdad, separada por tienda y consultable para el ranking. Langfuse sirve para analizar, ligado a la traza. |
| F2 | **Separar dos señales:** calidad de la respuesta y producto adecuado. Solo la segunda afecta el ranking. | Que todo 👎 baje el producto | Un 👎 por tono o por no entender no dice nada del producto. Mezclarlas ensucia el ranking y facilita envenenarlo (ASI06). |
| F3 | Los SKUs a los que aplica el feedback salen de las **tool calls del turno**, no de lo que diga el cliente. | El cliente indica el SKU | Es la misma regla que en la memoria (`datos_de_tools`): no se puede votar un producto que no se recomendó. |

---

## API

- `ChatResponse` suma `mensaje_id` (UUID que genera el backend). El evento final de
  `/chat/stream` (ver [`streaming.md`](streaming.md)) también lo trae.
- El `trace_id` de Langfuse se deriva del `mensaje_id`. El SDK permite fijar el id de la
  traza, así el feedback se liga a la traza sin guardar un mapeo.
- Endpoint nuevo `POST /api/v1/feedback` (requiere el Bearer JWT):

  ```json
  { "mensaje_id": "…", "valor": "positivo" | "negativo", "motivo": "producto_no_adecuado", "comentario": "…" }
  ```

  - `motivo` es **opcional** y de una lista cerrada. Propuesta inicial:
    - `producto_no_adecuado` → señal de producto, afecta el ranking;
    - `muy_caro` → señal de presupuesto, no del producto;
    - `no_entendi`, `no_era_lo_que_buscaba`, `otro` → señal de calidad de la respuesta.
  - `comentario` es texto libre opcional, de largo acotado y redactado con `redactar_pii`.
    **Nunca entra a un prompt** sin tratarlo como dato no confiable.
- El voto se puede cambiar: el último reemplaza al anterior.

---

## Validaciones

- El `mensaje_id` tiene que pertenecer al `thread_id` del token. Así no se puede votar un
  mensaje de otra sesión ni de otra tienda.
- **Un voto por mensaje** (unique `mensaje_id`).
- Las sesiones anónimas pueden votar la calidad. Para el ranking de productos, decidir si
  cuentan (pregunta abierta 1).

---

## Datos

Tabla `feedback_mensajes` (Alembic):
`id`, `tienda_id` (FK), `cliente_id` (FK, nullable), `thread_id`, `mensaje_id` (unique),
`valor`, `motivo`, `comentario`, `skus` (array, sacado de las tool calls del turno),
`creado_en`.

Para guardar los SKUs, el backend necesita conocer los SKUs del turno cuando el cliente vota.
Opciones:
- (a) guardarlos en Redis con TTL al responder, por `mensaje_id`;
- (b) leerlos del checkpoint del hilo cuando llega el voto.

Se recomienda la (a): es más simple y no depende de que la sesión siga viva.

---

## Cómo afecta el ranking

- `calcular_confianza_feedback()` lee de Postgres **por tienda** en lugar de
  `feedback.json`, con caché corto. Se mantiene el suavizado de Laplace y el peso 0.3.
- Solo cuentan los votos con motivo de producto: 👎 con `producto_no_adecuado` y 👍 sin
  motivo o de producto. Se cuenta un voto por cliente o sesión por SKU, para que nadie
  pueda inflarlo. Esto cierra el "gate de solo feedback real" pendiente en ASI06.
- `data/scoring/feedback.json` se migra una vez a la tabla y se retira.

---

## Uso para mejorar el agente

- En Langfuse, filtrar las trazas con 👎 por motivo, para revisarlas.
- Un script (`evals/desde_feedback.py`) arma borradores de casos de eval a partir de las
  respuestas con 👎. Una persona los revisa antes de sumarlos a `evals/casos/`.

---

## Pruebas

Integración contra Postgres:
- votar un mensaje propio → 201;
- votar un mensaje de otro hilo o de otra tienda → 404;
- el segundo voto reemplaza al primero;
- solo los motivos de producto cambian la confianza del SKU;
- los SKUs salen de las tool calls.

`/chat` mantiene sus tests sin cambios, salvo el campo nuevo `mensaje_id`.

---

## Fases

1. `mensaje_id` en `ChatResponse`, tabla y migración, `POST /feedback` y score en Langfuse.
2. Ranking por tienda desde Postgres y migración de `feedback.json`.
3. Script de borradores de eval a partir de los 👎.

---

## Preguntas abiertas

1. **Feedback anónimo:** ¿los votos de sesiones anónimas afectan el ranking de productos, o
   solo los de clientes identificados?
2. **Lista de motivos:** ¿la propuesta inicial alcanza, o la tienda quiere otros (por
   ejemplo, "no hay stock")?
