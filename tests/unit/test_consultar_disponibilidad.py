from app.tools.catalog import get_catalog
from app.tools.consultar_disponibilidad import consultar_disponibilidad


def test_consultar_disponibilidad_sku_existente_coincide_con_el_catalogo():
    producto_catalogo = get_catalog()[0]
    disponibilidad = consultar_disponibilidad(producto_catalogo["sku"])

    assert disponibilidad is not None
    assert disponibilidad.sku == producto_catalogo["sku"]
    assert disponibilidad.precio_regular == producto_catalogo["precio_regular"]
    assert disponibilidad.precio_por_kg == producto_catalogo["precio_por_kg"]
    assert disponibilidad.stock == producto_catalogo["stock"]
    assert disponibilidad.url_producto == producto_catalogo["url_producto"]


def test_consultar_disponibilidad_sku_inexistente_retorna_none():
    assert consultar_disponibilidad("SKU-QUE-NO-EXISTE") is None
