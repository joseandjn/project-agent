# Cheatsheet · Guardrails y memoria de sesión

Cómo probar e inspeccionar el guardrail de PII y la memoria de corto plazo (checkpointer de
Redis). Ejecutá todo desde `project-agent/`.

---

## 1 · Guardrail de PII (`app/guardrails/pii.py`)

Middleware `PIIMiddleware` de LangChain enchufado en `create_agent`. Reglas:

| Dato | Estrategia | Dónde se corta |
|---|---|---|
| Número de tarjeta | `block` | pre-chequeo en `generate_reply` **antes** del agente (+ middleware como red de seguridad) |
| Email | `redact` entrada + salida | `PIIMiddleware("email")` |
| Móvil peruano (`(+51)?9XXXXXXXX`) | `redact` entrada + salida | `PIIMiddleware("telefono_pe", detector=…)` |

### Probarlo por la API

```bash
SID="pii-$(date +%s)"

# email + teléfono -> el agente NO los ve (redactados)
curl -s -XPOST localhost:8000/api/v1/chat -H 'Content-Type: application/json' \
  -d "{\"mensaje\":\"escribime a ana@mail.com o al 987654321, tengo un perro adulto de 12 kg\",\"session_id\":\"$SID\"}" \
  | python3 -m json.tool

# número de tarjeta -> respuesta fija, no entra al grafo ni a Redis
curl -s -XPOST localhost:8000/api/v1/chat -H 'Content-Type: application/json' \
  -d "{\"mensaje\":\"pago con 4539 1488 0343 6467\",\"session_id\":\"$SID\"}" \
  | python3 -m json.tool
```

### Verificar que NO quedó PII cruda en Redis

```bash
docker compose exec -T redis sh -c '
  redis-cli --scan | while read k; do
    t=$(redis-cli type "$k")
    if [ "$t" = "ReJSON-RL" ]; then redis-cli JSON.GET "$k"; else redis-cli get "$k"; fi
  done' 2>/dev/null \
  | grep -oE "ana@mail\.com|987654321|4539|REDACTED_[A-Z_]+" | sort | uniq -c
# esperado: solo REDACTED_EMAIL / REDACTED_TELEFONO_PE
```

### Tests

```bash
docker compose exec api python -m pytest -q tests/unit/test_guardrails.py
# o local:
.venv/bin/python -m pytest -q tests/unit/test_guardrails.py
```

### Agregar una regla nueva

En `app/guardrails/pii.py`, dentro de `build_pii_guardrail()`:

```python
# tipo built-in (email, credit_card, ip, mac_address, url)
PIIMiddleware("ip", strategy="mask", apply_to_input=True),

# tipo propio con regex o función detectora
PIIMiddleware("dni_pe", detector=r"\b\d{8}\b", strategy="redact", apply_to_input=True),
```

Estrategias: `block` · `redact` (`[REDACTED_TIPO]`) · `mask` (`****1234`) · `hash` (`<tipo_hash:…>`).
Después: `docker compose up -d --build api`.

---

## 2 · Memoria de corto plazo (checkpointer de Redis)

`AsyncShallowRedisSaver` de `langgraph-checkpoint-redis` — guarda **solo el último
checkpoint** por sesión, con `thread_id == session_id` y TTL de 30 min (refresh en lectura).
Necesita Redis con RediSearch (imagen `redis:8`).

### Ver / inspeccionar sesiones

```bash
docker compose exec redis redis-cli DBSIZE
docker compose exec redis redis-cli --scan --pattern 'checkpoint*'

# TTL de la sesión <SID>
docker compose exec redis sh -c \
  'redis-cli --scan --pattern "checkpoint:<SID>*" | head -1 | xargs -I{} redis-cli TTL "{}"'

# contenido del último checkpoint de una sesión (mensajes del estado del grafo)
docker compose exec redis sh -c \
  'redis-cli --scan --pattern "checkpoint:<SID>*" | head -1 | xargs -I{} redis-cli JSON.GET "{}"' \
  | python3 -m json.tool

# confirmar que el módulo de búsqueda está cargado (si falta -> "unknown command FT.*")
docker compose exec redis redis-cli MODULE LIST | grep -A1 search
```

### Borrar memoria

```bash
docker compose exec redis redis-cli FLUSHDB          # todas las sesiones
# una sola sesión:
docker compose exec redis sh -c \
  'redis-cli --scan --pattern "*<SID>*" | xargs -r redis-cli DEL'
```

### Probar que la memoria funciona (multi-turno)

```bash
SID="mem-$(date +%s)"
curl -s -XPOST localhost:8000/api/v1/chat -H 'Content-Type: application/json' \
  -d "{\"mensaje\":\"tengo un gato adulto de 4 kg llamado Miso\",\"session_id\":\"$SID\"}" >/dev/null
curl -s -XPOST localhost:8000/api/v1/chat -H 'Content-Type: application/json' \
  -d "{\"mensaje\":\"que datos tenes de mi gato?\",\"session_id\":\"$SID\"}" | python3 -m json.tool
# la respuesta debe mencionar "Miso" y "4 kg"
```

---

## 3 · Correr las evals (calidad conversacional)

Las evals corren contra el agente real (con guardrail + checkpointer):

```bash
docker compose exec api python -m evals.run_evals --caso fuera-de-rol-descuento   # 1 caso
docker compose exec api python -m evals.run_evals                                 # los 8
```

Reportes en `evals/reportes/*.json` (carpeta montada, quedan en el host).

---

## 4 · Red teaming de seguridad (DeepTeam × OWASP ASI 2026)

`evals/red_team.py` ataca al agente real con ataques adversarios por cada categoría del
OWASP Top 10 for Agentic Applications 2026. **Consume tokens del `LLM_PROVIDER`** (simulador
+ agente + juez): empezá por una categoría.

```bash
# una categoría (recomendado para empezar) — ASI_01 .. ASI_10
docker compose exec api python -m evals.red_team --categoria ASI_01

# el default (sin flags): ASI_01, ASI_03, ASI_06 (las de mayor riesgo)
docker compose exec api python -m evals.red_team

# las 10 categorías, más cobertura por vulnerabilidad (lento y caro)
docker compose exec api python -m evals.red_team --full --intensidad 2
```

Flags: `--intensidad N` (ataques por tipo de vulnerabilidad, default 1),
`--max-concurrent N` (paralelismo, default 3).

Salida en `evals/reportes/` (montado al host):
- `<timestamp>.json` — formato DeepTeam (CVSS, todos los test cases).
- `redteam_<timestamp>.md` — reporte legible: resumen, tabla por categoría y por ataque, y
  el detalle de cada caso donde el agente **fue vulnerado** (entrada del ataque + respuesta
  del agente + motivo del juez).

> Necesita Redis arriba (el agente usa el checkpointer) y credenciales del `LLM_PROVIDER`.
> El mapeo ASI → riesgo del proyecto está en `docs/vulnerabilidades.md`.
