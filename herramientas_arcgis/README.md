# Ajuste Topológico Catastral (ArcGIS Pro / ArcMap)

Herramienta en **Python Toolbox** (`AjusteTopologico.pyt`) para corregir errores
de topología de un levantamiento de campo dentro de **una misma capa de polígonos**:
cierra vacíos (gaps), ajusta bordes coincidentes y absorbe los slivers producto
de la precisión del GPS/estación.

## Qué hace (flujo interno)

1. **Copia de trabajo** — nunca modifica tu capa original.
2. **Repair Geometry** — corrige geometrías nulas, auto-intersecciones y orden de vértices.
3. **Integrate** — hace *snap* de vértices/bordes que deberían ser coincidentes
   dentro de la **tolerancia** que indiques. Aquí se cierran los micro-vacíos y
   se resuelven los micro-solapes típicos de campo.
4. **Relleno de vacíos (opcional)** — reconstruye el tejido topológico, detecta
   los polígonos "vacío" (los que no corresponden a ningún predio) y los
   fusiona al predio vecino con el que comparten mayor borde.
   **Los predios reales conservan sus atributos** (ID, matrícula, etc.).
5. **Reporte** — cantidad de polígonos de salida y vacíos rellenados.

## Instalación

### ArcGIS Pro
1. En el panel **Catálogo** → clic derecho en **Toolboxes** → **Add Toolbox**.
2. Navega y selecciona `AjusteTopologico.pyt`.
3. Se despliega la herramienta **Ajuste Topológico de Polígonos**.

### ArcMap (10.x)
1. Abre **ArcToolbox** → clic derecho → **Add Toolbox**.
2. Selecciona `AjusteTopologico.pyt`.

## Parámetros

| Parámetro | Descripción |
|-----------|-------------|
| **Capa de polígonos de entrada** | Tu levantamiento (feature class o capa de polígonos). |
| **Feature class de salida** | Dónde se guarda el resultado limpio (recomendado: dentro de una File GDB). |
| **Tolerancia de ajuste (XY cluster)** | Distancia máxima para "pegar" vértices/bordes. Empieza pequeño, p. ej. `0.05 Meters` (5 cm) y sube con cuidado. **No la pongas muy alta** o colapsará detalle real. |
| **Rellenar vacíos** | Si se activa, absorbe los gaps hacia predios vecinos. |
| **Área máxima de vacío a rellenar** | En unidades de mapa al cuadrado (p. ej. m²). `0` = sin límite. Úsalo para NO rellenar huecos legítimos grandes (patios internos, zonas no levantadas). |

## Recomendaciones de uso

- **Empieza con una tolerancia baja** (2–5 cm) y revisa el resultado antes de subirla.
  En catastro una tolerancia excesiva une predios que no deben unirse.
- Trabaja siempre sobre una **File Geodatabase** y guarda copia del original.
- Verifica que la capa esté en un **sistema proyectado** (metros), p. ej.
  MAGNA-SIRGAS / Origen Nacional, para que la tolerancia en metros tenga sentido.
- **Después de correr la herramienta**, crea una **Topología** en un Feature Dataset
  con las reglas *Must Not Have Gaps* y *Must Not Overlap*, y valida para confirmar
  que no quedaron errores residuales.

## Licencia de ArcGIS requerida

- `Integrate` → **Standard** o superior.
- `Feature To Polygon` y `Eliminate` (relleno de vacíos) → **Advanced (ArcInfo)**.
  Si solo tienes Basic/Standard, desactiva *Rellenar vacíos*: aún obtendrás el
  ajuste por *Integrate*.
