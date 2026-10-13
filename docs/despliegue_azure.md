# Guía · Desplegar la demo en Azure

Guía paso a paso para publicar el backend en una **máquina virtual de Azure** con Docker
Compose, pensada para quien nunca usó un servicio en la nube. Tiempo estimado: **1 a 1,5
horas**.

Al terminar vas a tener:

- una URL pública con HTTPS, del tipo `https://vethis-demo.eastus2.cloudapp.azure.com`;
- Swagger en `https://…/docs` para probar el chat;
- trazas de la demo en Langfuse (entorno `demo`).

> El portal de Azure cambia sus pantallas de vez en cuando. Si un botón no se llama igual,
> busca el equivalente; la idea de cada paso no cambia.

---

## Cómo queda armado

```
Azure · grupo de recursos "vethis-demo-rg"
└── Máquina virtual Ubuntu 24.04 (Standard B2s: 2 vCPU, 4 GB)
    IP pública + nombre DNS: vethis-demo.<region>.cloudapp.azure.com
    Firewall (NSG): solo 22 (SSH, tu IP), 80 y 443
    └── Docker Compose (docker-compose.prod.yml)
        ├── caddy     ← único contenedor público: HTTPS automático (Let's Encrypt), 80/443
        ├── api       ← FastAPI (deploy/docker/Dockerfile)
        ├── postgres  ← pgvector/pgvector:pg16, con contraseña, sin puerto público
        └── redis     ← redis:8-alpine (RediSearch), con contraseña, sin puerto público

Servicios externos: OpenAI (chat + embeddings), Langfuse Cloud (trazas)
```

Es el mismo stack que corres en local, sin Ollama ni Neo4j: el chat y los embeddings usan
OpenAI (`LLM_PROVIDER=openai`, `EMBEDDING_PROVIDER=openai`).

Archivos del repo que se usan:

| Archivo | Para qué |
|---|---|
| `docker-compose.prod.yml` | El stack del servidor (sin puertos internos expuestos, con contraseñas y Caddy). |
| `deploy/caddy/Caddyfile` | HTTPS automático para el dominio de la demo. |
| `deploy/env.prod.example` | Plantilla del `.env` del servidor. |

> **Antes de empezar:** estos archivos y el cambio de embeddings tienen que estar en GitHub
> (`main`), porque el servidor clona el repo desde ahí.

---

## Paso 1 · Cuentas y límites de gasto (≈ 20 min)

### 1.1 Cuenta de Azure

1. Entra a <https://azure.microsoft.com/free> y crea la cuenta. Pide una tarjeta para
   verificar identidad. Las cuentas nuevas suelen traer crédito de prueba por un tiempo
   limitado: revisa las condiciones vigentes.
2. Entra al portal: <https://portal.azure.com>.

> **Si dice "No cumple los requisitos para obtener una cuenta gratuita"** (por ejemplo,
> porque esa cuenta, tarjeta o teléfono ya usó una prueba antes), elige **"Regístrese para
> obtener Azure con los precios de pago por uso"**. La guía es la misma; solo no hay crédito
> de prueba. Costo aproximado de la demo **por 48 horas y borrando todo al final: USD 2,50–3**
> (B2s ~USD 0,04/h + disco + IP; confirma en <https://azure.microsoft.com/pricing/calculator>).
> Si se olvida prendida, son ~USD 35–40 al mes: el presupuesto solo avisa, no corta.
>
> Si el portal muestra *"La cuenta de usuario seleccionada no existe en el inquilino
> Microsoft Services"*, el registro de Azure no terminó: complétalo y elige **Cuenta
> personal** al iniciar sesión. Si muestra *AADSTS50058*, el navegador bloquea las cookies de
> `login.microsoftonline.com`: permítelas o usa Edge o Chrome.

### 1.2 Alerta de presupuesto en Azure (hazlo primero)

En Azure es fácil dejar algo prendido y recibir una factura. Antes de crear nada:

1. En el buscador de arriba escribe **Budgets** (o **Cost Management → Budgets**).
2. **+ Add** → monto mensual, por ejemplo **USD 30**.
3. Alertas al **50 %** y al **90 %**, a tu email.

### 1.3 Límite de gasto en OpenAI

La API todavía no tiene rate limit: cualquiera con un token puede generar consumo.

1. <https://platform.openai.com> → **Settings → Limits** (o **Billing**): límite mensual de,
   por ejemplo, **USD 10**, con alerta al 50 %.
2. Crea una **API key solo para la demo** (**API keys → Create new secret key**, nombre
   `vethis-demo`). Así la puedes revocar sin afectar tu entorno local.

---

## Paso 2 · Crear la máquina virtual (≈ 15 min)

1. En el portal: **Create a resource → Virtual machine** (o busca "Virtual machines" →
   **+ Create → Azure virtual machine**).
2. Pestaña **Basics**:

   | Campo | Valor |
   |---|---|
   | Resource group | **Create new** → `vethis-demo-rg` |
   | Virtual machine name | `vethis-demo` |
   | Region | `East US 2`. Cualquier región sirve; las de EE. UU. suelen ser más baratas y Langfuse está en US. |
   | Availability options | No infrastructure redundancy required |
   | Image | **Ubuntu Server 24.04 LTS - x64 Gen2** |
   | Size | **Ver todos los tamaños** → buscar `B2` → **Standard_B2s** o **Standard_B2als_v2** (2 vCPU, 4 GiB, ~USD 27–38 al mes). El que propone el portal por defecto (p. ej. `Standard_D2s_v3`, ~USD 70) es más grande de lo necesario. No usar tamaños de 1–2 GiB. |
   | Authentication type | **SSH public key** |
   | Username | `azureuser` |
   | SSH public key source | Generate new key pair |
   | Key pair name | `vethis-demo-key` |
   | Public inbound ports | Allow selected ports |
   | Select inbound ports | **SSH (22), HTTP (80), HTTPS (443)** |

3. Pestaña **Disks**: deja el disco del sistema por defecto (Standard SSD, unos 30 GB).
4. Pestaña **Management** (opcional, recomendado): **Auto-shutdown** a una hora en la que
   no vayas a usar la demo. Apaga la máquina todos los días y ahorra costo; la prendes
   desde el portal cuando la necesites.
5. **Review + create → Create.**
6. Aparece **Generate new key pair → Download private key and create resource**. Se
   descarga `vethis-demo-key.pem`. **Guárdalo bien:** sin ese archivo no puedes entrar a la
   máquina.
7. Espera a que termine ("Your deployment is complete") → **Go to resource**.

> El **costo mensual estimado** del panel derecho es lo que costaría la VM prendida el mes
> entero (730 h). No se cobra por adelantado: se factura por el tiempo de uso.

### 2.0 Si aparece un error de cuota (`QuotaExceeded`)

Las suscripciones nuevas de pago por uso suelen tener **cuota 0** de vCPU para algunas
familias. El error se ve así:

```
No se pudo completar la operación porque supera la cuota de standardBsv2Family Cores
aprobada. ... Ubicación: eastus2, Límite actual: 0, ... Nuevo límite requerido: 2.
```

Opciones:

1. **Pedir el aumento (recomendado):** abre el link `https://aka.ms/ProdportalCRP/...` del
   propio mensaje, que viene con región, familia y límite **2** cargados → **Enviar**.
   Pedidos chicos suelen aprobarse solos en minutos; a veces se abre un caso de soporte y
   tarda horas. No tiene costo. Cuando quede aprobado, vuelve a **Revisar y crear**.
2. **Usar una familia o región con cuota:** portal → **Cuotas → Proceso**, filtra por
   suscripción y región (`East US 2`, `East US`, `Central US`) y busca una familia con límite
   de al menos 2: *Standard BS Family* (`Standard_B2s`), *Standard Bsv2 Family*
   (`Standard_B2als_v2`) o *Standard DASv5 Family* (`Standard_D2as_v5`, 8 GiB,
   ~USD 0,09/h). Si cambias de región, el dominio del paso 2.1 cambia
   (`vethis-demo.<region>.cloudapp.azure.com`).

Si el tamaño muestra *"no está disponible actualmente en <región> para la suscripción
(NotAvailableForSubscription)"*, elige otro tamaño de la tabla o cambia de región.

### 2.1 Nombre DNS (para el HTTPS)

1. En la página de la VM, en **Overview**, busca **DNS name** → **Not configured** (clic).
2. **DNS name label:** `vethis-demo` (si está tomado, otro: `vethis-demo-tunombre`).
3. **Save.** Tu dominio queda como `vethis-demo.eastus2.cloudapp.azure.com` (cambia según
   la región). **Anótalo:** es el `DOMAIN` del Paso 4.

### 2.2 Restringir el SSH a tu IP

1. En la VM: **Networking** (o **Network settings**) → regla de entrada **SSH (22)**.
2. **Source:** `My IP address` → **Save**.

### 2.3 Comprobar las reglas de HTTP y HTTPS

Caddy necesita los puertos **80** (Let's Encrypt valida el dominio por ahí y redirige a
HTTPS) y **443**. Si en el paso 2 no quedaron marcados:

1. En la VM → **Redes → Configuración de red → Crear regla de puerto → Regla de puerto de
   entrada**.
2. Origen **Any**, puertos de origen `*`, destino **Any**, **Servicio: HTTP**, acción
   **Permitir**, prioridad `310`, nombre `Allow-HTTP` → **Agregar**.
3. Repite con **Servicio: HTTPS**, prioridad `320`, nombre `Allow-HTTPS`.

Al final: **22** solo desde tu IP; **80** y **443** desde *Any*. No abras 5432, 6379 ni 8000.

Así solo tu conexión puede intentar entrar por SSH. Si cambias de red (otra casa, el
celular), vuelve a este paso.

---

## Paso 3 · Entrar al servidor e instalar Docker (≈ 10 min)

Desde la terminal de tu Mac:

```bash
chmod 400 ~/Downloads/vethis-demo-key.pem
ssh -i ~/Downloads/vethis-demo-key.pem azureuser@vethis-demo.eastus2.cloudapp.azure.com
```

La primera vez pregunta si confías en el servidor: escribe `yes`. Ahora estás **dentro de
la máquina virtual** (el prompt cambia a `azureuser@vethis-demo:~$`).

Instala Docker (script oficial) y da permiso a tu usuario:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit
```

Vuelve a entrar (el permiso se aplica en la nueva sesión) y comprueba:

```bash
ssh -i ~/Downloads/vethis-demo-key.pem azureuser@vethis-demo.eastus2.cloudapp.azure.com
docker run --rm hello-world
```

Tiene que imprimir `Hello from Docker!`.

---

## Paso 4 · Descargar el proyecto y configurar el `.env` (≈ 10 min)

Dentro del servidor:

```bash
git clone https://github.com/joseandjn/project-agent.git
cd project-agent
cp deploy/env.prod.example .env
```

Genera los secretos (corre el comando **3 veces**: Postgres, Redis y JWT):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Edita el `.env`:

```bash
nano .env
```

Completa:

| Variable | Valor |
|---|---|
| `DOMAIN` | El nombre DNS del paso 2.1, sin `https://` |
| `POSTGRES_PASSWORD` | Secreto 1 |
| `REDIS_PASSWORD` | Secreto 2 |
| `JWT_SECRET` | Secreto 3. **No uses el de tu entorno local.** |
| `OPENAI_API_KEY` | La key de la demo (paso 1.3) |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Las de tu proyecto de Langfuse. Si no quieres trazas de la demo: `LANGFUSE_ENABLED=false`. |

Guardar en `nano`: `Ctrl+O`, `Enter`, y salir con `Ctrl+X`.

Protege el archivo:

```bash
chmod 600 .env
```

> Guarda también estos valores en un gestor de contraseñas. No los pegues en el repo ni en
> chats.

---

## Paso 5 · Levantar la demo (≈ 10 min)

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

El primer build tarda unos minutos. Después revisa:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs api | tail -20
docker compose -f docker-compose.prod.yml logs caddy | grep -i certificate
```

Tiene que aparecer:

- en `ps`: `postgres` y `redis` **healthy**, `api` y `caddy` **Up**;
- en los logs de `api`:
  ```
  Running upgrade  -> 0001, tiendas y clientes
  Running upgrade 0001 -> 0002, perfiles de cliente
  Application startup complete.
  ```
- en los logs de `caddy`: `certificate obtained successfully`.

Desde el navegador de tu Mac: `https://<DOMAIN>/health` → `{"status":"ok"}`, con candado.

---

## Paso 6 · Crear la tienda de la demo (≈ 2 min)

La base del servidor está vacía. Dentro del servidor:

```bash
docker compose -f docker-compose.prod.yml exec api python -m scripts.crear_tienda "Tienda Demo"
```

**Copia la API key** que imprime (`vth_...`). Se muestra una sola vez; en la base solo queda
su hash. Es distinta de la de tu entorno local.

Puedes salir del servidor con `exit`.

---

## Paso 7 · Probar la demo (≈ 5 min)

Desde la terminal de tu Mac (reemplaza el dominio y la key):

```bash
URL=https://vethis-demo.eastus2.cloudapp.azure.com
KEY=vth_...

TOKEN=$(curl -s $URL/api/v1/auth/token \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"external_user_id":"u-demo"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s $URL/api/v2/chat -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"mensaje":"Hola, tengo un perro adulto de 30 kg, sin limite de presupuesto. Recomiendame un alimento y su precio"}'
```

O desde el navegador, en `https://<DOMAIN>/docs`:

1. `POST /api/v1/auth/token` → **Try it out**, header `X-API-Key` con tu key, body
   `{"external_user_id": "u-demo"}` → copia el `access_token`.
2. Botón **Authorize** (arriba a la derecha) → pega el token.
3. `POST /api/v2/chat` → **Try it out** → escribe un mensaje.

En Langfuse (us.cloud.langfuse.com → Tracing) aparece la traza `chat_v2` con el environment
**`demo`**.

---

## Paso 8 · (Opcional) El chat web

El chat de [`vethis-chat`](https://github.com/joseandjn/vethis-chat) (Next.js +
assistant-ui) se sirve en la misma URL: Caddy manda `/` al chat y `/api/v1`, `/api/v2`,
`/docs` y `/health` a la API. La API key de la tienda queda en el servidor; el navegador solo
recibe una cookie `httpOnly` con su token.

Dentro del servidor:

```bash
cd ~
git clone https://github.com/joseandjn/vethis-chat.git      # al lado de project-agent
cd project-agent
git pull

# API key de una tienda para el chat, directo al .env (no se muestra en pantalla)
KEY=$(docker compose -f docker-compose.prod.yml exec -T api python -m scripts.crear_tienda "Tienda Chat" | grep -o 'vth_[A-Za-z0-9_-]*')
echo "CHAT_API_KEY=$KEY" >> .env && unset KEY

docker compose -f docker-compose.prod.yml --profile chat up -d --build
```

Abre `https://<DOMAIN>/` en el navegador. Para actualizar después: `git pull` en
`~/vethis-chat` y en `~/project-agent`, y el mismo `up -d --build` con `--profile chat`.

---

## Paso 9 · (Opcional) Neo4j para la guía nutricional

Sin Neo4j, el asesor usa la guía por defecto (`data/guias/tienda_demo.yaml`, dentro de la
imagen). Con Neo4j, cada tienda tiene su guía activa y sus versiones
(`docs/guia_nutricional_neo4j.md`). Neo4j corre en la misma VM, sin puertos públicos y con la
memoria acotada (~650 MB en uso).

Dentro del servidor:

```bash
cd ~/project-agent
git pull

# Contraseña de Neo4j y URI interna, directo al .env (no se muestra en pantalla)
echo "NEO4J_URI=bolt://neo4j:7687" >> .env
echo "NEO4J_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" >> .env

docker compose -f docker-compose.prod.yml --profile chat --profile neo4j up -d --build

# Cargar la guía para cada tienda (los IDs salen de Postgres)
docker compose -f docker-compose.prod.yml exec postgres psql -U vethis -d vethis -c "select id, nombre from tiendas"
docker compose -f docker-compose.prod.yml exec api python -m scripts.cargar_guia --tienda <id> data/guias/tienda_demo.yaml
```

Desde ahí, usa siempre `--profile chat --profile neo4j` en los `up`.

---

## Actualizar la demo

Después de hacer `git push` desde tu Mac:

```bash
ssh -i ~/Downloads/vethis-demo-key.pem azureuser@<DOMAIN>
cd project-agent
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Las migraciones nuevas corren solas al arrancar la API. Los datos de Postgres se conservan
(están en un volumen de Docker).

---

## Costos y cómo apagarla

- **Mientras la VM está prendida** se cobra la máquina (B2s), el disco y la IP pública.
  Revisa **Cost Management → Cost analysis** cada tanto.
- **Apagar sin perder nada:** en la VM → **Stop**. Queda *Stopped (deallocated)* y deja de
  cobrarse la máquina; el disco y la IP siguen cobrándose, pero es poco. Al volver a
  prenderla (**Start**), los contenedores arrancan solos (`restart: unless-stopped`).
  > Si la apagas desde dentro con `sudo shutdown`, queda *Stopped* pero **se sigue cobrando**.
  > Apágala siempre desde el portal.
- **Borrar todo:** **Resource groups → `vethis-demo-rg` → Delete resource group.** Borra la
  VM, el disco, la IP y la red de una vez. Después revoca la API key de OpenAI de la demo.

---

## Limitaciones de la demo

- **Sin rate limit:** por eso los topes de gasto. Comparte la API key de la tienda solo con
  quien vaya a probar.
- **Derivaciones al veterinario:** se guardan como archivos (`data/derivaciones/`) dentro del
  contenedor y se pierden al reconstruirlo. Para la demo no importa.
- **Sin respaldos:** si borras la VM, se pierden la base y la tienda creada.
- **Datos de prueba:** la base del servidor es otra; no tiene los clientes ni perfiles de tu
  entorno local.
- **Datos personales:** las conversaciones viajan a OpenAI y a Langfuse (con email, teléfono y
  tarjeta enmascarados en Langfuse). Usa datos ficticios.
- **Actualizaciones del sistema:** Ubuntu instala los parches de seguridad automáticamente,
  pero no reinicia. Para una demo de semanas no es un problema.

---

## Si algo falla

| Síntoma | Causa probable | Qué revisar |
|---|---|---|
| `ssh: Permission denied (publickey)` | Archivo `.pem` o usuario equivocado | `chmod 400` al `.pem`, usuario `azureuser` |
| `ssh: Connection timed out` | La regla de SSH no incluye tu IP actual | Paso 2.2 |
| `permission denied ... docker.sock` | Falta volver a entrar después de `usermod` | Salir con `exit` y entrar de nuevo |
| `falta POSTGRES_PASSWORD en .env` (o `REDIS_PASSWORD`, `DOMAIN`) | Variable vacía | `nano .env` |
| `JWT_SECRET no esta configurado o tiene menos de 32 bytes` | Falta o es corto | `JWT_SECRET` en `.env` |
| Caddy no obtiene el certificado | DNS no configurado, o puertos 80/443 cerrados | Pasos 2.1 y 2.3, `logs caddy` |
| El navegador avisa que el sitio no es seguro | Todavía no hay certificado | Esperar 1–2 min y revisar `logs caddy` |
| `/chat` responde 500 | Ver el error en `logs api` | Muchas veces `OPENAI_API_KEY` o el límite de gasto alcanzado |
| `401` en `/auth/token` | API key equivocada (¿la de local?) | Usar la creada en el Paso 6 |
| El build se queda sin memoria | VM con menos de 4 GB | Tamaño B2s o mayor |
| `QuotaExceeded` al crear la VM | Cuota 0 de esa familia en la región | Paso 2.0 |
| `NotAvailableForSubscription` en el tamaño | Tamaño restringido en esa región | Otro tamaño de 4 GiB u otra región (paso 2.0) |

Para ver los logs en vivo: `docker compose -f docker-compose.prod.yml logs -f api` (salir con
`Ctrl+C`). Si algo no cierra, copia el error y lo revisamos.
