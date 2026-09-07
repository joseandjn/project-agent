# Guías de nutrición (placeholder)

> **Importante:** estos porcentajes son una heurística simplificada de referencia para el
> proyecto de curso, **no** están validados por un veterinario. El blueprint original exige
> que esta guía la valide el veterinario de la tienda antes de usarse en producción
> (`app/tools/calcular_racion.py` implementa esta tabla; reemplazar por las cifras reales
> antes de un uso productivo).

## Ración diaria como % del peso corporal

| Etapa de vida | % peso corporal / día |
|---|---|
| Cachorro / Kitten | 4.0% |
| Adulto | 2.5% |
| Senior | 2.0% |
| Todas las edades (sin dato de etapa) | 2.5% |

Fórmula usada por `calcular_racion`:

```
racion_diaria_kg = peso_mascota_kg * porcentaje_segun_etapa
duracion_dias    = peso_empaque_kg / racion_diaria_kg
costo_mensual    = racion_diaria_kg * 30 * precio_por_kg
```

Estos valores no consideran nivel de actividad, condición corporal ni kcal/kg real del
producto (dato que el catálogo de muestra no incluye). Son solo para tener el cálculo
funcionando de punta a punta en el proyecto.
