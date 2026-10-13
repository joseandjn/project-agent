# Rate limits

Estado: **implementado** (2026-10-12).

Objetivo: que nadie pueda saturar el servicio ni disparar el costo de LLM: un cliente que
manda mensajes en bucle, un bot que abre sesiones sin parar, o alguien que prueba API keys.

---

## Decisiones

| # | Decisión | Alternativa descartada | Por qué |
|---|---|---|---|
| L1 | Límites **en la app** (dependencias de FastAPI) con contadores en **Redis**. | Solo en el proxy (Caddy/nginx) | El proxy no sabe de sesiones, clientes ni tiendas: eso está en el JWT. Caddy además necesita un plugin compilado aparte para rate limit. Redis ya está y comparte los contadores entre réplicas de `api`. |
| L2 | Reglas por **sesión, cliente y tienda**; por **IP solo los intentos con API key inválida**. | Límite por IP para todo | Todo el tráfico de una tienda llega desde su servidor (y el de la demo, desde el contenedor del chat): muchos usuarios comparten IP. Un límite por IP bloquearía a todos juntos. |
| L3 | **Ventanas fijas** (`INCR` + `EXPIRE NX` en un pipeline atómico). | Ventana deslizante / token bucket | Simple, una ida a Redis por request y suficiente para frenar abuso. En el borde de dos ventanas se pueden pasar hasta 2× el límite durante unos segundos; es aceptable. |
| L4 | Los requests **rechazados también cuentan**. | Contar solo los aceptados | Quien insiste sigue bloqueado hasta que deja de insistir. |
| L5 | **Fail-open:** si Redis falla, el request pasa y se loguea. | Fail-closed (rechazar todo) | El limitador no puede ser la causa de una caída. Además, el chat ya depende de Redis (checkpointer): si Redis está caído, el chat falla por otro lado. |
| L6 | Un request **sin token válido no consume cupo** (primero 401, después el límite). | Contar todo | Si no, cualquiera podría agotar el cupo de una tienda sin credenciales. |

---

## Reglas

Todas configurables (`.env`); `0` desactiva una regla y `RATE_LIMIT_ENABLED=false` las
desactiva todas.

| Regla | Ruta | Por | Límite por defecto | Variable |
|---|---|---|---|---|
| `chat:sesion` | `/api/v1/chat`, `/api/v2/chat` | sesión | 10 / min | `RL_CHAT_SESION_POR_MINUTO` |
| `chat:cliente` | ídem | cliente (todas sus sesiones) | 20 / min | `RL_CHAT_CLIENTE_POR_MINUTO` |
| `chat:tienda` | ídem | tienda | 300 / min | `RL_CHAT_TIENDA_POR_MINUTO` |
| `chat:tienda:dia` | ídem | tienda | 10 000 / día (tope de costo de LLM) | `RL_CHAT_TIENDA_POR_DIA` |
| `token:tienda` | `/api/v1/auth/token` | tienda | 120 sesiones nuevas / min | `RL_TOKEN_TIENDA_POR_MINUTO` |
| `api_key_invalida:ip` | `/api/v1/auth/token` | IP | 10 intentos fallidos / min | `RL_API_KEY_INVALIDA_IP_POR_MINUTO` |
| `refresh:sesion` | `/api/v1/auth/refresh` | sesión | 10 / min | `RL_REFRESH_SESION_POR_MINUTO` |
| `feedback:sesion` | `/api/v1/feedback` | sesión | 30 / min | `RL_FEEDBACK_SESION_POR_MINUTO` |
| `memoria:cliente` | `/api/v1/memoria` | cliente | 20 / min | `RL_MEMORIA_CLIENTE_POR_MINUTO` |

Al pasarse: **429** con `Retry-After` (segundos hasta que se libera la ventana).

Con la IP bloqueada por API keys inválidas, **tampoco pasa una key válida** desde esa IP
durante el minuto: así no se pueden seguir probando keys.

---

## Refuerzos complementarios

- **Largo del mensaje:** `mensaje` de `/chat` tiene tope de **2000 caracteres** (422 si se
  pasa). Un mensaje enorme es costo de tokens y superficie de inyección.
- **Tamaño del body:** Caddy corta en **64 KB** (413), antes de llegar a la API.
- **IP real detrás de Caddy:** `FORWARDED_ALLOW_IPS="*"` en `docker-compose.prod.yml` hace que
  uvicorn tome la IP de `X-Forwarded-For`. Es seguro porque la API solo recibe tráfico de
  Caddy por la red interna (no publica puertos). **No** se pone en `docker-compose.yml`
  (local), donde la API está expuesta en el 8000 y cualquiera podría falsear el header.

---

## Implementación

| Pieza | Dónde |
|---|---|
| `Regla`, `consumir`, `excedido`, `LimiteExcedido` (429), `ip_cliente` | `app/core/rate_limit.py` |
| Dependencias por ruta (`limitar_chat`, `limitar_refresh`, `limitar_feedback`, `limitar_memoria`) | `app/api/v1/dependencies/rate_limit.py` |
| API key inválida por IP | `get_tienda_por_api_key` (`app/api/v1/dependencies/auth.py`) |
| Sesiones nuevas por tienda | `POST /auth/token` (`app/api/v1/routes/auth.py`) |
| Claves en Redis | `vethis:rl:{regla}:{sujeto}:{ventana}`, con TTL igual a la ventana |
| Tests | `tests/integration/test_rate_limit.py` (los demás tests corren con los límites apagados, `tests/conftest.py`) |

---

## Límites dentro de un turno

Los rate limits frenan muchos mensajes; esto frena **un** mensaje que hace que el agente
llame al modelo o a las tools en bucle (`app/guardrails/limites.py`, v1 y v2):

| Límite | Por defecto | Variable | Al pasarse |
|---|---|---|---|
| Llamadas al modelo por turno (`ModelCallLimitMiddleware`) | 8 (un turno con búsqueda, precios y ración usa ~4) | `AGENTE_MAX_LLAMADAS_MODELO` | Se corta el turno |
| Llamadas a tools por turno (`ToolCallLimitMiddleware`) | 12 | `AGENTE_MAX_LLAMADAS_TOOLS` | La tool se bloquea y el modelo sigue |
| `derivar_veterinario` por turno | 1 | — | Ídem (no escribe varias derivaciones) |
| Pasos del grafo (`recursion_limit`) | 150 | `AGENTE_MAX_PASOS` | Se corta el turno |
| Duración del turno | 60 s | `AGENTE_TIMEOUT_SEGUNDOS` | Se corta el turno |
| Timeout de cada request al proveedor | 30 s | `LLM_TIMEOUT_SEGUNDOS` | Reintenta |
| Reintentos por request | 2 | `LLM_MAX_REINTENTOS` | Error |
| Modelo de respaldo (`ModelFallbackMiddleware`) | desactivado | `LLM_FALLBACK_MODEL` (`"modelo"` o `"proveedor:modelo"`) | — |

- **Cuando se corta un turno**, se **borran de la sesión los mensajes de ese turno** (pudo
  quedar una tool call sin respuesta, que rompería el turno siguiente) y el cliente recibe un
  mensaje fijo en español. Por eso se usa `exit_behavior="error"`: el `"end"` de LangChain le
  respondería al cliente un texto en inglés.
- **Pasos del grafo:** cada llamada al modelo usa ~12 pasos (los middlewares de PII y de
  límites son nodos del grafo). Con un tope de 25 se cortaban los turnos normales; la
  configuración ahora valida al arrancar que `AGENTE_MAX_PASOS ≥ 15 × AGENTE_MAX_LLAMADAS_MODELO`.
- El límite de tools por sí solo no corta un bucle (con `"continue"` el modelo puede seguir
  pidiendo): lo corta el límite de llamadas al modelo.
- Tests: `tests/unit/test_limites.py` (modelo en bucle, lento, que deriva dos veces y que
  falla con respaldo; el turno siguiente al corte funciona).

---

## Lo que esto no cubre

- **El chat público de la demo** (`vethis-chat`): sus sesiones son anónimas y las crea el
  servidor del chat, así que alguien puede abrir sesiones nuevas para esquivar el límite por
  sesión. Lo frenan `token:tienda` y `chat:tienda`, pero agotando el cupo de la tienda (es un
  DoS para los demás usuarios de esa tienda). Siguiente paso: límite **por IP en el servidor
  del chat** (`app/api/*` de vethis-chat), que sí ve la IP de cada navegador.
- ~~**Bucles dentro de un turno**~~: resuelto, ver [Límites dentro de un turno](#límites-dentro-de-un-turno).
- **DDoS de red:** volumen que satura la VM antes de llegar a la app. Para eso hace falta un
  servicio delante (Azure DDoS Protection, Cloudflare).
