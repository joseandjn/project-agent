from app.tools.catalog import get_catalog, get_producto_by_sku


def test_get_catalog_no_esta_vacio():
    catalogo = get_catalog()
    assert len(catalogo) > 0


def test_get_catalog_tiene_los_campos_esperados():
    producto = get_catalog()[0]
    campos_esperados = {
        "sku",
        "nombre",
        "presentacion",
        "especie",
        "etapa",
        "tipo_alimento",
        "proteina_principal",
        "peso_kg",
        "precio_por_kg",
        "precio_regular",
        "disponible",
        "stock",
        "url_producto",
        "documento_busqueda",
    }
    assert campos_esperados.issubset(producto.keys())


def test_get_producto_by_sku_encuentra_un_sku_existente():
    catalogo = get_catalog()
    sku_existente = catalogo[0]["sku"]
    producto = get_producto_by_sku(sku_existente)
    assert producto is not None
    assert producto["sku"] == sku_existente


def test_get_producto_by_sku_retorna_none_si_no_existe():
    assert get_producto_by_sku("SKU-QUE-NO-EXISTE") is None
