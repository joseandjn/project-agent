"""Validacion del voto (app/models/feedback.py), sin servicios."""

import uuid

import pytest
from pydantic import ValidationError

from app.models.feedback import FeedbackRequest

ID = uuid.uuid4()


def test_positivo_sin_motivo():
    assert FeedbackRequest(mensaje_id=ID, valor="positivo").motivo is None


def test_negativo_con_motivo():
    assert FeedbackRequest(mensaje_id=ID, valor="negativo", motivo="producto_no_adecuado").motivo == "producto_no_adecuado"


@pytest.mark.parametrize(
    "datos",
    [
        {"valor": "positivo", "motivo": "muy_caro"},  # motivo solo con negativo
        {"valor": "negativo", "motivo": "me_cae_mal"},  # fuera de la lista
        {"valor": "neutro"},
        {"valor": "negativo", "comentario": "x" * 501},
        {"valor": "negativo", "comentario": "pague con 4111 1111 1111 1111"},
    ],
)
def test_rechaza(datos):
    with pytest.raises(ValidationError):
        FeedbackRequest(mensaje_id=ID, **datos)


def test_comentario_redacta_email_y_telefono():
    req = FeedbackRequest(mensaje_id=ID, valor="negativo", comentario="  escribanme a ana@mail.com o al 987654321 ")
    assert req.comentario == "escribanme a [REDACTED_EMAIL] o al [REDACTED_TELEFONO_PE]"


def test_comentario_vacio_queda_en_none():
    assert FeedbackRequest(mensaje_id=ID, valor="negativo", comentario="   ").comentario is None
