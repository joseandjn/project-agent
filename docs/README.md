# docs/

Documentación de diseño y seguridad de `project-agent`.

| Archivo | Contenido |
|---|---|
| [`arquitectura.md`](arquitectura.md) | Diagrama de componentes (Mermaid) + secuencia de `POST /api/v1/chat` + tabla de contenedores. Marca lo implementado vs lo pendiente del blueprint. |
| [`vulnerabilidades.md`](vulnerabilidades.md) | Análisis manual del backend contra el **OWASP Agentic Security (ASI) Top 10**: severidad y "por qué" por categoría, con referencia a archivos, y remediación priorizada. |

Verificación automatizada de seguridad: `evals/red_team.py` (DeepTeam × OWASP ASI 2026) —
ver `cheatsheets/guardrails.md` §4.

El blueprint de 5 capas (editable) vive fuera del repo, en `../Asesor_de_ventas.html`.
