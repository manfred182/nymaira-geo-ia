# -*- coding: utf-8 -*-
"""
AjusteTopologico.pyt
--------------------
Herramienta de Python Toolbox para ArcGIS Pro y ArcMap (arcpy).

Corrige errores de topologia de un levantamiento de campo en una capa de
poligonos:
  1) Repara geometria (nulos, auto-intersecciones, orden de vertices).
  2) INTEGRATE: junta ("snap") vertices y bordes coincidentes dentro de una
     tolerancia, cerrando micro-vacios y resolviendo micro-solapes producto
     de la precision del GPS/estacion en campo.
  3) (Opcional) Rellena los vacios (gaps) que queden entre poligonos
     absorbiendolos hacia el predio vecino con el que comparten mayor borde,
     CONSERVANDO los atributos de los predios reales.

Compatible con Python 3 (ArcGIS Pro) y Python 2.7 (ArcMap 10.x).

Licencia requerida:
  - Integrate: ArcGIS Standard o superior.
  - Feature To Polygon / Eliminate (relleno de vacios): ArcGIS Advanced.
"""

import os
import arcpy


class Toolbox(object):
    def __init__(self):
        self.label = "Ajuste Topologico Catastral"
        self.alias = "topocatastro"
        self.tools = [AjusteTopologico]


class AjusteTopologico(object):

    def __init__(self):
        self.label = "Ajuste Topologico de Poligonos"
        self.description = ("Corrige gaps y solapes de una capa de poligonos "
                            "provenientes de un levantamiento de campo.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        p_in = arcpy.Parameter(
            displayName="Capa de poligonos de entrada",
            name="in_fc",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input")
        p_in.filter.list = ["Polygon"]

        p_out = arcpy.Parameter(
            displayName="Feature class de salida",
            name="out_fc",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output")

        p_tol = arcpy.Parameter(
            displayName="Tolerancia de ajuste (XY cluster)",
            name="tolerance",
            datatype="GPLinearUnit",
            parameterType="Required",
            direction="Input")
        p_tol.value = "0.05 Meters"

        p_gaps = arcpy.Parameter(
            displayName="Rellenar vacios (gaps) entre poligonos",
            name="fill_gaps",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        p_gaps.value = True

        p_maxarea = arcpy.Parameter(
            displayName=("Area maxima de vacio a rellenar "
                         "(unidades de mapa al cuadrado; 0 = sin limite)"),
            name="max_gap_area",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input")
        p_maxarea.value = 0

        return [p_in, p_out, p_tol, p_gaps, p_maxarea]

    def isLicensed(self):
        return True

    # ------------------------------------------------------------------ #
    def execute(self, parameters, messages):
        arcpy.env.overwriteOutput = True

        in_fc = parameters[0].valueAsText
        out_fc = parameters[1].valueAsText
        tolerance = parameters[2].valueAsText          # ej. "0.05 Meters"
        fill_gaps = parameters[3].value
        max_gap_area = parameters[4].value or 0

        scratch = arcpy.env.scratchGDB
        work = os.path.join(scratch, "topo_work")
        ftp = os.path.join(scratch, "topo_ftp")
        gaps_fc = os.path.join(scratch, "topo_gaps")
        merged = os.path.join(scratch, "topo_merged")

        def msg(txt):
            arcpy.AddMessage(txt)

        # 1) Copia de trabajo (no tocamos el original) -----------------
        msg("1/5  Copiando capa de entrada a un area de trabajo...")
        arcpy.management.CopyFeatures(in_fc, work)

        # 2) Reparar geometria -----------------------------------------
        msg("2/5  Reparando geometria...")
        arcpy.management.RepairGeometry(work, "DELETE_NULL")

        # 3) Integrate (snap de vertices/bordes coincidentes) ----------
        msg("3/5  Ajustando (Integrate) con tolerancia: {0}".format(tolerance))
        # Integrate modifica IN-PLACE la copia de trabajo.
        arcpy.management.Integrate([[work, 1]], tolerance)
        arcpy.management.RepairGeometry(work, "DELETE_NULL")

        gaps_rellenados = 0

        if fill_gaps:
            msg("4/5  Detectando y rellenando vacios (gaps)...")

            # Marcamos los predios reales con IS_GAP = 0
            self._add_flag(work, 0)

            # Reconstruimos el 'tejido' topologico: cada area cerrada
            # (incluidos los vacios) se vuelve un poligono.
            arcpy.management.FeatureToPolygon(work, ftp)

            ftp_lyr = "ftp_lyr"
            arcpy.management.MakeFeatureLayer(ftp, ftp_lyr)

            # Los poligonos cuyo centro cae dentro de un predio real son
            # predios; el resto (seleccion invertida) son los vacios.
            arcpy.management.SelectLayerByLocation(
                ftp_lyr, "HAVE_THEIR_CENTER_IN", work)
            arcpy.management.SelectLayerByAttribute(
                ftp_lyr, "SWITCH_SELECTION")

            # Filtro opcional por area maxima de vacio
            if max_gap_area and float(max_gap_area) > 0:
                arcpy.management.SelectLayerByAttribute(
                    ftp_lyr, "REMOVE_FROM_SELECTION",
                    '"Shape_Area" > {0}'.format(float(max_gap_area)))

            n_gaps = int(arcpy.management.GetCount(ftp_lyr)[0])
            msg("     Vacios encontrados a rellenar: {0}".format(n_gaps))

            if n_gaps > 0:
                # Exportamos solo los vacios y los marcamos IS_GAP = 1
                arcpy.management.CopyFeatures(ftp_lyr, gaps_fc)
                self._add_flag(gaps_fc, 1)

                # Unimos predios reales + vacios
                arcpy.management.Merge([work, gaps_fc], merged)

                # Eliminamos los vacios: se fusionan al vecino con el que
                # comparten mayor longitud de borde (el predio conserva
                # sus atributos porque el vacio NO esta seleccionado).
                mlyr = "merged_lyr"
                arcpy.management.MakeFeatureLayer(merged, mlyr)
                arcpy.management.SelectLayerByAttribute(
                    mlyr, "NEW_SELECTION", "IS_GAP = 1")
                arcpy.management.Eliminate(mlyr, out_fc, "LENGTH")
                gaps_rellenados = n_gaps
            else:
                arcpy.management.CopyFeatures(work, out_fc)

            # Limpiamos el campo auxiliar
            self._drop_flag(out_fc)
        else:
            msg("4/5  Relleno de vacios desactivado.")
            arcpy.management.CopyFeatures(work, out_fc)

        arcpy.management.RepairGeometry(out_fc, "DELETE_NULL")

        # 5) Reporte ----------------------------------------------------
        n_out = int(arcpy.management.GetCount(out_fc)[0])
        msg("5/5  Proceso terminado.")
        msg("     Poligonos en la salida: {0}".format(n_out))
        msg("     Vacios rellenados:      {0}".format(gaps_rellenados))
        msg("     Salida: {0}".format(out_fc))
        msg("")
        msg("SUGERENCIA: crea una topologia (Must Not Have Gaps / "
            "Must Not Overlap) y valida para confirmar que no quedaron "
            "errores residuales.")

        # Limpieza de intermedios
        for tmp in (work, ftp, gaps_fc, merged):
            if arcpy.Exists(tmp):
                try:
                    arcpy.management.Delete(tmp)
                except Exception:
                    pass

    # ------------------------------------------------------------------ #
    @staticmethod
    def _add_flag(fc, value):
        """Agrega y setea el campo auxiliar IS_GAP (compatible py2/py3)."""
        fields = [f.name for f in arcpy.ListFields(fc)]
        if "IS_GAP" not in fields:
            arcpy.management.AddField(fc, "IS_GAP", "SHORT")
        with arcpy.da.UpdateCursor(fc, ["IS_GAP"]) as cur:
            for row in cur:
                row[0] = value
                cur.updateRow(row)

    @staticmethod
    def _drop_flag(fc):
        fields = [f.name for f in arcpy.ListFields(fc)]
        if "IS_GAP" in fields:
            try:
                arcpy.management.DeleteField(fc, "IS_GAP")
            except Exception:
                pass
