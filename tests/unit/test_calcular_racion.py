from app.tools.calcular_racion import calcular_racion


def test_calcular_racion_perro_cachorro():
    resultado = calcular_racion(peso_mascota_kg=4.0, sku="DOG-CACH-PEQ-POL-001")

    assert resultado is not None
    assert resultado.sku == "DOG-CACH-PEQ-POL-001"
    # 4kg * 4% (cachorro) = 0.16kg/dia = 160g/dia
    assert resultado.racion_diaria_g == 160.0
    # empaque de 3kg / 0.16kg por dia
    assert resultado.duracion_dias == 19
    # 0.16kg/dia * 30 dias * S/18.5 por kg
    assert resultado.costo_mensual == 88.8


def test_calcular_racion_sku_inexistente_retorna_none():
    assert calcular_racion(peso_mascota_kg=4.0, sku="SKU-QUE-NO-EXISTE") is None


def test_calcular_racion_a_mayor_peso_mayor_racion():
    chico = calcular_racion(peso_mascota_kg=2.0, sku="DOG-CACH-PEQ-POL-001")
    grande = calcular_racion(peso_mascota_kg=8.0, sku="DOG-CACH-PEQ-POL-001")

    assert chico.racion_diaria_g < grande.racion_diaria_g
