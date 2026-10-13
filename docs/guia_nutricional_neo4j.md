# Diseño · Guía nutricional por tienda en Neo4j

Estado: **Fase 1 implementada** (2026-10-13), con una guía de demo basada en la WSAVA. Ver
[Implementación (Fase 1)](#implementación-fase-1). Fases 2 (extractor desde PDF) y 3
(cruces con el catálogo en las tools) pendientes.

Objetivo: que cada tienda tenga **su propia guía nutricional** (aprobada por su
veterinario), guardada como grafo en Neo4j. El agente la consulta según la tienda del token,
en vez de usar valores escritos en el código.

---

## Punto de partida

| Pieza | Estado actual |
|---|---|
| `data/conocimiento/guias_nutricion.md` | Placeholder con 4 porcentajes de ración por etapa (cachorro 4 %, adulto 2,5 %, senior 2 %) y las fórmulas de ración, duración y costo. Sin validar por un veterinario. |
| `app/tools/calcular_racion.py` | Repite esos porcentajes en `PORCENTAJE_DIARIO_POR_ETAPA`, escritos en el código. Iguales para todas las tiendas. |
| `graph_neo4j/` | Experimento aislado: el catálogo como grafo (`Producto`, `Especie`, `Etapa`, `TamanoRaza`, `Proteina`, `Ingrediente`). El agente no lo usa y no distingue tiendas. |
| Tiendas | Ya existen en Postgres (`tiendas`, UUID) y el `tienda_id` viaja en el JWT (`AuthContext.tienda_id`). |

---

## Recomendación

### 1. No convertir la guía directo a grafo con un LLM

Conviene pasar por un **formato canónico intermedio** que el veterinario revise y apruebe
antes de cargarlo:

```mermaid
flowchart TD
    A["Guía de la tienda<br/>(PDF / Word / Markdown / Excel)"] -->|"extractor LLM con salida estructurada<br/>(como el de memoria)"| B
    T["Plantilla YAML<br/>completada por la tienda"] --> B
    B["Guía canónica YAML/JSON<br/>validada con Pydantic · estado: borrador<br/>cada regla cita su fuente"] -->|"revisión y aprobación<br/>del veterinario de la tienda"| C
    C["Carga idempotente a Neo4j<br/>versión nueva de la guía"] -->|"activación: se mueve GUIA_ACTIVA<br/>la versión anterior queda para auditoría"| D
    D["Tools del agente<br/>consultas Cypher fijas y parametrizadas"]
```

**Por qué:**

- **Es contenido clínico.** Un porcentaje mal extraído o una contraindicación inventada
  dañan a una mascota. El blueprint exige que el veterinario de la tienda valide la guía. Un
  YAML se puede revisar, comparar entre versiones y guardar en git; un grafo generado
  directo por un LLM, no.
- **Ontología fija para todas las tiendas.** `LLMGraphTransformer` (LangChain) o el LLM
  Graph Builder de Neo4j crean nodos y relaciones distintos según el documento. Con
  tiendas diferentes, los grafos no se podrían consultar igual. Con un esquema fijo, el
  agente usa las mismas consultas para cualquier tienda.
- **Dos formas de entrada.** Una tienda ordenada completa la plantilla YAML y no hace
  falta el LLM. El extractor solo se usa para documentos libres.

### 2. Ontología propuesta

```
(:Tienda {id})-[:GUIA_ACTIVA]->(:Guia {version, estado, aprobada_por, fecha})
(:Tienda)-[:TIENE_GUIA]->(:Guia)                                    # todas las versiones

(:Guia)-[:DEFINE]->(:ReglaRacion {pct_peso_min, pct_peso_max, kcal_kg?})
    (:ReglaRacion)-[:PARA_ESPECIE]->(:Especie)
    (:ReglaRacion)-[:PARA_ETAPA]->(:Etapa)
    (:ReglaRacion)-[:PARA_TAMANO]->(:TamanoRaza)

(:Guia)-[:DEFINE]->(:ReglaCondicion {deriva_veterinario})-[:SOBRE]->(:Condicion {nombre})
    (:ReglaCondicion)-[:EVITAR]->(:Proteina | :Ingrediente | :Nutriente)
    (:ReglaCondicion)-[:PRIORIZAR]->(:Nutriente)                     # con rango en la relación

(:Guia)-[:DEFINE]->(:ReglaTransicion {dias, pasos})

(cualquier regla)-[:SUSTENTADA_EN]->(:Fuente {seccion, pagina, texto})   # trazabilidad
```

`Especie`, `Etapa`, `TamanoRaza`, `Proteina` e `Ingrediente` son **los mismos nodos** del
grafo del catálogo (`graph_neo4j/load_catalogo.py`). Esa es la ventaja de Neo4j: una sola
consulta responde *"productos aptos para un perro senior con enfermedad renal según la guía
de la tienda X"*, recorriendo condición → qué evitar → ingredientes → productos.

### 3. Separación entre tiendas

- La imagen es **Neo4j Community**, que admite **una sola base de datos de usuario**. Una
  base por tienda requiere Enterprise (de pago).
- Cada guía cuelga de su `(:Tienda {id})`, y **todas las consultas arrancan desde ese
  nodo**. El `tienda_id` sale del JWT, igual que en la memoria; nunca lo elige el LLM.
- Las reglas son de cada guía. Los nodos de vocabulario (especie, proteína, etc.) se
  comparten entre tiendas.
- **Versiones:** una versión nueva se carga como `borrador`. Activarla es mover
  `GUIA_ACTIVA` en una transacción: el cambio es atómico y volver atrás es trivial.

### 4. Cómo la usa el agente

Con **tools deterministas**, no con text2cypher (`GraphCypherQAChain`). Si el LLM arma el
Cypher, una inyección de prompt podría leer la guía de otra tienda.

- `calcular_racion` lee la `ReglaRacion` de la guía activa de la tienda, en lugar de
  `PORCENTAJE_DIARIO_POR_ETAPA`.
- Tool nueva `consultar_guia(especie, etapa, condiciones)`: devuelve qué evitar, qué
  priorizar y si corresponde derivar al veterinario. Así la derivación deja de depender
  solo del prompt (riesgo abierto de ASI01 en `vulnerabilidades.md`).
- `tienda_id` se pasa al construir las tools (`build_tools`), no como argumento que el LLM
  pueda completar.

### 5. Operación

- **Neo4j pasa a ser dependencia de producción** del servicio `api` (hoy es un experimento
  aislado). Hay que planear respaldo (volumen `neo4j_data`) y monitoreo.
- **Respaldo funcional:** si Neo4j no responde, o la tienda todavía no tiene guía activa, el
  agente usa la guía genérica actual, lo registra en logs y lo aclara en la respuesta.

---

## Antes de decidir

- **¿Hace falta Neo4j?** Para la guía de hoy (4 porcentajes) alcanza con una tabla en
  Postgres. Neo4j se justifica si las guías van a tener **condiciones, contraindicaciones e
  ingredientes cruzados con el catálogo**; ahí las consultas de varios saltos son su fuerte.
- **Costo operativo:** un tercer almacén (Redis + Postgres + Neo4j) que respaldar, migrar y
  monitorear.

---

## Fases propuestas

1. ✅ **Ontología y carga:** esquema Pydantic de la guía canónica, carga idempotente,
   `python -m scripts.cargar_guia --tienda <id> guia.yaml`, una guía de demo basada en la
   WSAVA y `calcular_racion` leyendo del grafo (con respaldo a la guía por defecto). Incluye
   también `consultar_guia` y `ver_ficha_producto` (adelantados de la Fase 3).
2. **Extractor y aprobación:** de PDF/Markdown a YAML borrador con citas a la fuente, más el
   flujo de revisión y activación. Evals con aserciones duras, como `evals/run_evals_memoria.py`.
3. **`consultar_guia`:** condiciones y derivación, conectadas al grafo del catálogo.

---

## Implementación (Fase 1)

**Decisiones de la demo (2026-10-13):** una sola guía (Tienda Demo), basada en el WSAVA
Global Nutrition Toolkit; ambiente controlado, sin revisión veterinaria. Las respuestas a
las preguntas abiertas para la demo: formato = plantilla YAML; contenido = energía, premios,
tóxicos, condición corporal, cómo elegir, transición y condiciones que derivan; aprobación =
un script que corremos nosotros.

**La guía** (`data/guias/tienda_demo.yaml`): cada regla cita su fuente. De la WSAVA
(resumido, no copiado): energía diaria de adultos con las fórmulas NRC 2006 que la WSAVA cita
(perro 1,2–1,5 × 70 × peso^0,75; gato entre 130 × peso^0,4 y 100 × peso^0,67, comprobadas
contra sus tablas), premios < 10 % de las calorías, tóxicos por especie, riesgos de premios,
condición corporal 1–9 (ideal 4–5) y cómo elegir un alimento. Marcado `demo` (sin fuente
veterinaria): ración de cachorros (4 % del peso), transición en 7 días, condiciones que
derivan y "si la condición corporal no es ideal, derivar".

**Catálogo:** cada producto tiene un **análisis garantizado de demo**
(`data/catalogo/alimentos.json`, `analisis`: proteína, grasa, fibra, humedad, kcal/kg;
premios y dietas veterinarias marcados). Valores verosímiles de una marca ficticia.

| Pieza | Dónde |
|---|---|
| Esquema y validación (fuentes citadas definidas, reglas coherentes) | `app/nutricion/guia.py` |
| Ración: kcal de la guía ÷ kcal/kg del producto (adultos), % del peso (cachorros), máximo diario (premios), "lo define el veterinario" (dietas veterinarias) | `app/nutricion/racion.py` |
| Grafo: carga, versiones, `GUIA_ACTIVA`, vocabulario compartido con el catálogo | `app/nutricion/grafo.py`, `scripts/cargar_guia.py` |
| Lectura por tienda con caché y guía por defecto si Neo4j no responde | `app/nutricion/repo.py` (`NEO4J_URI`, `GUIA_POR_DEFECTO`, `GUIA_CACHE_SEGUNDOS`) |
| Tools `calcular_racion`, `consultar_guia`, `ver_ficha_producto` (la tienda sale del `thread_id`, nunca del LLM) | `app/nutricion/servicio.py`, `app/tools/langchain_tools.py` |
| Tests | `tests/unit/test_guia_nutricional.py`, `tests/integration/test_guia_neo4j.py` |
| Eval contra el agente real | `python -m evals.run_evals_nutricion` |

**Lectura:** el nodo `Guia` guarda también el contenido canónico validado (JSON). El agente
lee la versión activa de su tienda en una consulta y la valida con Pydantic; los nodos de
reglas (enlazados a `Especie`, `Etapa`, `Ingrediente`, `Condicion`, `Fuente`) sirven para
consultas cruzadas, p. ej. productos de gato con algún ingrediente prohibido para gatos.

**Catálogo y guía comparten vocabulario:** el borrado de `graph_neo4j/load_catalogo.py` ahora
solo elimina productos y nodos huérfanos, para no romper las reglas de las guías.

**Eval (`evals/run_evals_nutricion.py`, gpt-4o-mini):** 8 casos con aserciones duras (tool
usada y dato de la guía en la respuesta), dos de ellos de la prueba con amigos de la demo.
Primera corrida 2/8: el agente decía no tener información nutricional, respondía de memoria y
pedía el peso antes de responder preguntas generales. Tras ajustar el prompt (disparadores
por tipo de pregunta y pedir solo los datos necesarios) y aceptar SKU o nombre en las tools:
**14/16** (2 repeticiones). Los 2 fallos responden con el dato correcto pero de memoria, sin
consultar la guía.

**Despliegue:** en local, `docker-compose.yml` pasa `NEO4J_URI` a la API. En la demo de Azure
(`docker-compose.prod.yml`) Neo4j es el perfil opcional `neo4j`, sin puertos públicos y con
la memoria acotada (~600 MB en uso); se activa con `NEO4J_URI` y `NEO4J_PASSWORD` en el `.env` y
`COMPOSE_PROFILES=chat,neo4j` (paso 9 de `docs/despliegue_azure.md`). Sin `NEO4J_URI` la API usa la guía por
defecto, con el mismo contenido.

---

## Preguntas abiertas

1. **¿En qué formato mandan las tiendas sus guías?** PDF, Word, Excel, o les damos una
   plantilla.
2. **¿Qué contenido van a tener, además de la ración?** Condiciones, contraindicaciones,
   transición de alimento, kcal por producto. De esto depende si Neo4j vale la pena.
3. **¿Quién aprueba la guía y por dónde?** Un script que corremos nosotros, o un endpoint de
   administración para cada tienda.
