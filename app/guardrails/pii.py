"""Guardrail de datos personales (PII) sobre el chat, con el middleware `PIIMiddleware`
de LangChain (herramienta lista, no una regla escrita a mano).

- **Numero de tarjeta -> BLOQUEA.** El chat no es un canal de pago: la compra se completa
  en la tienda web. Se chequea *antes* de correr el agente (`contiene_numero_de_tarjeta`)
  para que el numero no entre al grafo ni quede en el checkpointer de Redis; el
  `PIIMiddleware("credit_card", strategy="block")` queda ademas como red de seguridad.
- **Email y telefono (movil peruano) -> REDACTA** en entrada y salida. El asesor no
  necesita el dato para recomendar alimento; asi no llega al LLM ni se persiste en Redis.

Doc: https://docs.langchain.com/oss/python/langchain/middleware/built-in
"""

from typing import List

from langchain.agents.middleware import AgentMiddleware, PIIMiddleware
from langchain.agents.middleware.pii import detect_credit_card

# Movil peruano: 9 digitos que empiezan en 9, con prefijo +51 / 51 opcional.
_TELEFONO_PE = r"(?:\+?51[\s-]?)?9\d{8}"


def contiene_numero_de_tarjeta(texto: str) -> bool:
    """True si el texto trae algo que parece un numero de tarjeta (validado con Luhn).
    Usa el mismo detector que `PIIMiddleware("credit_card")`."""
    return bool(detect_credit_card(texto))


def build_pii_guardrail() -> List[AgentMiddleware]:
    """Middlewares de PII para pasar a `create_agent(..., middleware=...)`."""
    return [
        PIIMiddleware(
            "email",
            strategy="redact",
            apply_to_input=True,
            apply_to_output=True,
        ),
        PIIMiddleware(
            "telefono_pe",
            detector=_TELEFONO_PE,
            strategy="redact",
            apply_to_input=True,
            apply_to_output=True,
        ),
        PIIMiddleware("credit_card", strategy="block", apply_to_input=True),
    ]
