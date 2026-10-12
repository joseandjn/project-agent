# Guía · Desplegar la demo en Railway

Guía paso a paso para publicar el backend en internet, pensada para quien nunca usó un
servicio en la nube. Tiempo estimado: **1 hora**, sin contar la parte de código.

Al terminar vas a tener:

- una URL pública con HTTPS, del tipo `https://vethis-api-production.up.railway.app`;
- Swagger en `https://…/docs` para probar el chat;
- trazas de la demo en Langfuse (entorno `demo`).

> Railway cambia su interfaz y sus precios de vez en cuando. Si un botón no se llama igual,
> busca el equivalente; la idea de cada paso no cambia.

---

## Cómo queda armado

```
Proyecto en Railway "vethis-demo"
├── api       ← tu repo de GitHub (deploy/docker/Dockerfile) — única pieza pública, con HTTPS
├── postgres  ← imagen pgvector/pgvector:pg16 + disco (volumen)
└── redis     ← imagen redis:8-alpine, con contraseña
              (se hablan por la red privada de Railway: *.railway.internal)

Servicios externos que ya usas: OpenAI (chat + embeddings), Langfuse Cloud (trazas)
```

No se despliegan Ollama ni Neo4j: el chat y los embeddings usan OpenAI, y Neo4j es un
experimento aparte.

---

## Paso 0 · Cambios de código antes de desplegar (los hace Claude)

Estos cambios todavía **no están hechos**. Sin ellos la API no funciona en Railway:

- [x] **Embeddings configurables:** `buscar_alimentos` puede calcularlos con OpenAI
      (`EMBEDDING_PROVIDER=openai`, modelo `text-embedding-3-small`). En local se sigue
      usando Ollama.
- [ ] **Puerto:** que la API escuche en el puerto que asigna Railway (variable `PORT`). Hoy
      está fijo en 8000.
- [ ] (Opcional) **Página de chat** para la demo, si se decide hacerla.

Cuando estén en GitHub (`main`), sigue con el Paso 1.

---

## Paso 1 · Preparar las cuentas (≈ 15 min)

### 1.1 Railway

1. Entra a <https://railway.com> y elige **Login → GitHub**.
2. Autoriza a Railway a ver tus repositorios. Puedes darle acceso solo a
   `joseandjn/project-agent`.
3. Revisa el plan: hay un período de prueba con crédito y después un plan pago (Hobby).
   Para una demo alcanza el más chico.

### 1.2 Límite de gasto en OpenAI (importante)

La API todavía no tiene rate limit: cualquiera con un token puede generar consumo.

1. Entra a <https://platform.openai.com> → **Settings → Limits** (o **Billing**).
2. Pon un **límite mensual**, por ejemplo **USD 10**, y una alerta al 50 %.
3. Recomendado: crea una **API key nueva solo para la demo** (**API keys → Create new
   secret key**, nombre `vethis-demo`). Así la puedes revocar sin afectar tu entorno local.

### 1.3 Generar el secreto de los tokens

En tu terminal, desde la carpeta del proyecto:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Guarda el resultado: es el `JWT_SECRET` de la demo. **No uses el mismo que en local.**

Genera también una contraseña para Redis y otra para Postgres, con el mismo comando.

> Guarda estos valores en un gestor de contraseñas. No los pegues en el repo ni en chats.

---

## Paso 2 · Crear el proyecto y la base de datos Postgres (≈ 10 min)

1. En Railway: **New Project → Empty Project**. Renómbralo a `vethis-demo`
   (Settings del proyecto).
2. **+ Create → Docker Image** y escribe `pgvector/pgvector:pg16`.
3. Renombra el servicio a **`postgres`** (clic en el servicio → Settings → nombre). El
   nombre importa: es el que usa la red privada (`postgres.railway.internal`).
4. **Variables** del servicio `postgres`:

   | Variable | Valor |
   |---|---|
   | `POSTGRES_USER` | `vethis` |
   | `POSTGRES_PASSWORD` | la contraseña de Postgres del paso 1.3 |
   | `POSTGRES_DB` | `vethis` |
   | `PGDATA` | `/var/lib/postgresql/data/pgdata` |

5. **Volumen (disco):** clic derecho sobre el servicio (o Settings) → **Add Volume**, con
   *mount path* `/var/lib/postgresql/data`. Sin volumen, los datos se pierden en cada
   reinicio. `PGDATA` apunta a una subcarpeta porque Postgres no arranca si la carpeta
   montada no está vacía.
6. **No** generes un dominio público para este servicio.
7. Espera a que el despliegue quede en verde y revisa en **Logs** que aparezca
   `database system is ready to accept connections`.

---

## Paso 3 · Redis (≈ 5 min)

1. **+ Create → Docker Image** → `redis:8-alpine`.
2. Renombra el servicio a **`redis`**.
3. **Settings → Deploy → Custom Start Command**:

   ```
   redis-server --requirepass <CONTRASEÑA_REDIS> --appendonly yes
   ```

   Reemplaza `<CONTRASEÑA_REDIS>` por la del paso 1.3.
4. Opcional: un volumen en `/data`, para que las sesiones abiertas sobrevivan a un reinicio
   de Redis. Para una demo no es necesario: las sesiones duran 30 minutos.
5. **No** generes dominio público.
6. En **Logs** tiene que aparecer `Ready to accept connections`.

---

## Paso 4 · La API (≈ 15 min)

1. **+ Create → GitHub Repo** → `joseandjn/project-agent`, rama `main`.
2. Renombra el servicio a **`api`**.
3. **Variables** del servicio `api`. Puedes pegarlas todas juntas con **Raw Editor**:

   ```bash
   # Railway: dónde está el Dockerfile
   RAILWAY_DOCKERFILE_PATH=deploy/docker/Dockerfile

   # App
   ENVIRONMENT=demo
   ALLOWED_ORIGINS=*

   # LLM y embeddings
   LLM_PROVIDER=openai
   OPENAI_API_KEY=sk-...                     # la key de la demo (paso 1.2)
   OPENAI_CHAT_MODEL=gpt-4o-mini
   EMBEDDING_PROVIDER=openai                 # requiere el cambio del Paso 0

   # Datos (red privada de Railway)
   POSTGRES_DSN=postgresql+asyncpg://vethis:<CONTRASEÑA_POSTGRES>@postgres.railway.internal:5432/vethis
   REDIS_URL=redis://default:<CONTRASEÑA_REDIS>@redis.railway.internal:6379/0

   # Autenticación
   JWT_SECRET=<el del paso 1.3>
   JWT_TTL_SECONDS=3600

   # Langfuse (mismo proyecto; las trazas quedan con environment "demo")
   LANGFUSE_ENABLED=true
   LANGFUSE_HOST=https://us.cloud.langfuse.com
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   ```

   Reemplaza todo lo que está entre `< >` y los `...`.
4. **Settings → Networking → Generate Domain.** Railway te da la URL pública. Si te pide
   un puerto, deja el que propone (la API lee la variable `PORT`).
5. Railway construye la imagen. El primer build tarda unos minutos. En **Deploy Logs**
   tiene que aparecer:

   ```
   Running upgrade  -> 0001, ...
   Running upgrade 0001 -> 0002, ...
   Application startup complete.
   ```

   Las migraciones de Alembic corren solas al arrancar y crean las tablas.
6. Prueba en el navegador: `https://<tu-dominio>/health` → `{"status":"ok"}`.

---

## Paso 5 · Crear la tienda de la demo (≈ 10 min)

La base de la nube está vacía: hay que crear una tienda para tener una API key.

1. Instala la CLI de Railway en tu Mac:

   ```bash
   brew install railway
   ```

2. Inicia sesión y vincula la carpeta del proyecto:

   ```bash
   railway login
   railway link          # elige el proyecto vethis-demo y el servicio api
   ```

3. Abre una consola dentro del contenedor de la API y crea la tienda:

   ```bash
   railway ssh
   python -m scripts.crear_tienda "Tienda Demo"
   ```

4. **Copia la API key** que imprime (`vth_...`). Se muestra una sola vez; en la base solo
   queda su hash. Es distinta de la de tu entorno local.

---

## Paso 6 · Probar la demo (≈ 5 min)

Desde tu terminal (reemplaza el dominio y la key):

```bash
URL=https://<tu-dominio>
KEY=vth_...

TOKEN=$(curl -s $URL/api/v1/auth/token \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"external_user_id":"u-demo"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s $URL/api/v2/chat -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"mensaje":"Hola, tengo un perro adulto de 30 kg, sin limite de presupuesto. Recomiendame un alimento y su precio"}'
```

O desde el navegador, en `https://<tu-dominio>/docs`:

1. `POST /api/v1/auth/token` → **Try it out**, header `X-API-Key` con tu key, body
   `{"external_user_id": "u-demo"}` → copia el `access_token`.
2. Botón **Authorize** (arriba a la derecha) → pega el token.
3. `POST /api/v2/chat` → **Try it out** → escribe un mensaje.

Verifica en Langfuse (us.cloud.langfuse.com → Tracing) que aparezca la traza `chat_v2` con
el environment **`demo`**.

---

## Actualizar la demo

Cada `git push` a `main` vuelve a desplegar el servicio `api` automáticamente. Las
migraciones nuevas corren solas al arrancar.

---

## Costos y cómo apagarla

- **Railway:** consumo por CPU, memoria y disco de los 3 servicios. Revisa **Usage** en el
  proyecto y configura un **límite de gasto** (Settings de la cuenta → Usage Limits).
- **OpenAI:** queda limitado por el tope del paso 1.2.
- **Pausar:** en cada servicio, **Settings → Remove** del despliegue activo (o escalar a 0)
  deja de consumir CPU. Los volúmenes siguen guardando los datos.
- **Borrar todo:** Settings del proyecto → **Delete Project**. Después revoca la API key de
  OpenAI de la demo.

---

## Limitaciones de la demo

- **Sin rate limit:** por eso el tope de gasto en OpenAI. Comparte la API key de la tienda
  solo con quien vaya a probar.
- **Derivaciones al veterinario:** se guardan como archivos (`data/derivaciones/`) dentro
  del contenedor y **se pierden en cada despliegue**. Para la demo no importa.
- **Datos de prueba:** la base de la nube es otra; no tiene los clientes ni perfiles de tu
  entorno local.
- **Datos personales:** las conversaciones viajan a OpenAI y a Langfuse (con email,
  teléfono y tarjeta enmascarados en Langfuse). Usa datos ficticios en la demo.

---

## Si algo falla

| Síntoma | Causa probable | Qué revisar |
|---|---|---|
| El build falla con "Dockerfile not found" | Falta `RAILWAY_DOCKERFILE_PATH` | Variable del servicio `api` |
| `JWT_SECRET no esta configurado o tiene menos de 32 bytes` | Falta o es corto | Variable `JWT_SECRET` |
| Error de conexión a Postgres al arrancar | Contraseña, nombre del servicio o Postgres todavía arrancando | `POSTGRES_DSN`, que el servicio se llame `postgres`, Logs de `postgres` |
| `unknown command 'FT._LIST'` o error de índices de Redis | La imagen no es `redis:8` | Imagen del servicio `redis` |
| `NOAUTH Authentication required` | La contraseña de `REDIS_URL` no coincide con la del start command | Ambas |
| `/chat` responde 500 al buscar productos | Embeddings todavía con Ollama | Paso 0 y `EMBEDDING_PROVIDER=openai` |
| `401` en `/auth/token` | API key equivocada (¿la de local?) | Usar la creada en el Paso 5 |
| La URL no responde | Falta el dominio o el puerto | Settings → Networking del servicio `api` |

Si algo no cierra, copia el error de **Deploy Logs** y lo revisamos.
