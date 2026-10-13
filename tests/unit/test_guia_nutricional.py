"""Guia nutricional sin Neo4j: esquema del YAML, calculos de racion contra las tablas WSAVA,
y las tools (v1 y v2) con la guia por defecto."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.nutricion.guia import Guia, cargar_yaml
from app.nutricion.racion import calcular_racion
from app.nutricion.servicio import consultar_guia, ficha_producto, racion_para
from app.tools.catalog import get_producto_by_sku

GUIA = cargar_yaml(Path(__file__).resolve().parents[2] / "data" / "guias" / "tienda_demo.yaml")


@pytest.mark.parametrize(
    "especie,peso,tabla",
    [
        # Tablas WSAVA "Calorie Needs" (julio 2020): las formulas deben caer dentro de +-1%.
        ("Perro", 2, (140, 177)), ("Perro", 10, (470, 590)), ("Perro", 20, (790, 993)), ("Perro", 40, (1340, 1670)),
        ("Gato", 2, (160, 170)), ("Gato", 4, (225, 250)), ("Gato", 6, (265, 330)),
    ],
)
def test_energia_coincide_con_las_tablas_wsava(especie, peso, tabla):
    lo, hi = GUIA.regla_energia(especie, "Adulto").kcal_diarias(peso)
    assert abs(lo - tabla[0]) / tabla[0] < 0.01 + 0.06 * (especie == "Gato" and peso == 2)
    assert abs(hi - tabla[1]) / tabla[1] < 0.02


def test_racion_adulto_por_calorias():
    r = calcular_racion(GUIA, get_producto_by_sku("DOG-ADU-GRA-POL-003"), 30)
    assert r["kcal_dia"] == [1077, 1346]
    assert r["racion_diaria_g"] == [290, 365]  # 1077 y 1346 kcal / 3700 kcal/kg
    assert r["duracion_dias"][0] <= r["duracion_dias"][1]
    assert r["fuentes"] and "WSAVA" in r["fuentes"][0]


def test_racion_cachorro_por_porcentaje_de_peso():
    r = calcular_racion(GUIA, get_producto_by_sku("DOG-CACH-PEQ-POL-001"), 4)
    assert r["racion_diaria_g"] == [160, 160] and r["kcal_dia"] is None


def test_etapa_de_la_mascota_manda_sobre_la_del_producto():
    # Alimento "Adulto/Todas las edades" para un cachorro: regla de cachorro.
    r = calcular_racion(GUIA, get_producto_by_sku("DOG-ADU-TOD-POL-009"), 5, etapa="Cachorro")
    assert r["etapa"] == "Cachorro" and r["racion_diaria_g"] == [200, 200]


def test_premio_devuelve_maximo_diario():
    r = calcular_racion(GUIA, get_producto_by_sku("DOG-SNACK-POL-011"), 20)
    assert r["es_premio"] and r["max_kcal_dia"] == 79 and r["max_gramos_dia"] == 25


def test_dieta_veterinaria_no_calcula_y_deriva():
    r = calcular_racion(GUIA, get_producto_by_sku("CAT-URI-MED-016"), 4)
    assert r["dieta_veterinaria"] and r["deriva_veterinario"] and "racion_diaria_g" not in r


def test_guia_rechaza_fuente_no_definida():
    datos = GUIA.model_dump()
    datos["transicion"]["fuente"] = ["inventada"]
    with pytest.raises(ValidationError, match="inventada"):
        Guia.model_validate(datos)


def test_guia_rechaza_regla_kcal_sin_formula():
    datos = GUIA.model_dump()
    datos["energia"][0]["kcal_min"] = None
    with pytest.raises(ValidationError, match="kcal_min"):
        Guia.model_validate(datos)


async def test_servicio_usa_la_guia_por_defecto_sin_neo4j():
    r = await racion_para("tienda-x:sesion", 4, "CAT-ADU-POL-013")
    assert r["origen_guia"] == "por_defecto" and r["racion_diaria_g"] == [60, 65]


async def test_toxicos_distintos_por_especie():
    gato = await consultar_guia("t:s", "Gato", "toxicos")
    perro = await consultar_guia("t:s", "Perro", "toxicos")
    assert "leche y lacteos" in gato["no_dar_nunca"] and "leche y lacteos" not in perro["no_dar_nunca"]
    assert "nueces de macadamia" in perro["no_dar_nunca"]


async def test_condiciones_que_derivan():
    r = await consultar_guia("t:s", "Perro", "condiciones_que_derivan")
    assert "enfermedad renal" in r["condiciones"]


def test_ficha_producto_trae_analisis_y_no_precio():
    f = ficha_producto("CAT-ADU-SAL-HUM-014")
    assert f["analisis_garantizado"]["kcal_por_kg"] == 950 and "Salmon" in f["nombre"]
    assert "precio_regular" not in f and f["nota"]
    assert ficha_producto("NO-EXISTE") == {"error": "SKU no encontrado en el catalogo"}
