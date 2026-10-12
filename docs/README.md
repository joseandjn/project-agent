# docs/

Documentación de diseño y seguridad de `project-agent`.

| Archivo | Contenido |
|---|---|
| [`arquitectura.md`](arquitectura.md) | Diagrama de componentes (Mermaid) + secuencia de `POST /api/v1/chat` + tabla de contenedores. Marca lo implementado vs lo pendiente del blueprint. |
| [`memoria_largo_plazo.md`](memoria_largo_plazo.md) | **Propuesta de diseño**: autenticación con JWT propio (agnóstica a la tienda) + memoria de largo plazo por cliente en Postgres (cuándo consolidar, extractor LLM, esquema, privacidad). |
| [`demanda_no_atendida.md`](demanda_no_atendida.md) | **Propuesta pendiente**: registrar y contar por tienda los productos que los clientes piden y no están en el catálogo, para decidir qué tener en stock; búsqueda en internet solo en segundo plano, fuera del chat. |
| [`guia_nutricional_neo4j.md`](guia_nutricional_neo4j.md) | **Propuesta pendiente**: guía nutricional por tienda como grafo en Neo4j (formato canónico + aprobación veterinaria, ontología, separación entre tiendas, tools del agente) y preguntas abiertas. |
| [`observabilidad_langfuse.md`](observabilidad_langfuse.md) | **Propuesta de diseño**: trazas por turno con Langfuse Cloud (costo por tienda, memoria, guardrails), enmascarado de PII y retención. Base de feedback y streaming. |
| [`feedback_cliente.md`](feedback_cliente.md) | **Propuesta de diseño**: 👍/👎 por respuesta con motivo opcional, guardado en Postgres y como score en Langfuse; solo los motivos de producto afectan el ranking por tienda. |
| [`streaming.md`](streaming.md) | **Propuesta de diseño**: `POST /api/v1/chat/stream` con SSE (progreso en vivo + texto ya verificado), sin cambiar `/chat`. |
| [`reglas_de_negocio_en_codigo.md`](reglas_de_negocio_en_codigo.md) | **Propuesta de diseño**: presupuesto, derivación al veterinario y anclaje de precios/SKUs garantizados por el backend (middlewares), no solo por el prompt. Incluye la causa del caso S/ 149.25. |
| [`vulnerabilidades.md`](vulnerabilidades.md) | Análisis manual del backend contra el **OWASP Agentic Security (ASI) Top 10**: severidad y "por qué" por categoría, con referencia a archivos, y remediación priorizada. |

Verificación automatizada de seguridad: `evals/red_team.py` (DeepTeam × OWASP ASI 2026) —
ver `cheatsheets/guardrails.md` §4.

El blueprint de 5 capas (editable) vive fuera del repo, en `../Asesor_de_ventas.html`.
