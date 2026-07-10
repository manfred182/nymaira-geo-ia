"""Todas las fuentes de informacion publica del gobierno colombiano.

Busca en portales oficiales de todas las entidades del estado colombiano
usando scraping de DuckDuckGo con site: restringido a cada fuente.
"""

from __future__ import annotations
import re
from urllib.parse import quote_plus
import httpx

# ── Todas las fuentes oficiales colombianas por sector ────────────

FUENTES: dict[str, list[tuple[str, str, str]]] = {
    # ── CATASTRAL / GEOESPACIAL / TERRITORIO ──────────────────
    "catastral": [
        ("IGAC - Datos Abiertos", "https://geoportal.igac.gov.co", "geoportal.igac.gov.co"),
        ("IGAC - Portal", "https://www.igac.gov.co", "igac.gov.co"),
        ("ICDE - Datos Geoespaciales", "https://datos.icde.gov.co", "datos.icde.gov.co"),
        ("SNRP - Matriculas", "https://www.supernotariado.gov.co", "supernotariado.gov.co"),
        ("SNR - Registro", "https://www.snr.gov.co", "snr.gov.co"),
        ("VUR - Ventanilla Unica de Registro (Notarias)", "https://www.vur.gov.co", "vur.gov.co"),
        ("ART - Agencia Renovacion del Territorio", "https://www.renovacionterritorio.gov.co", "renovacionterritorio.gov.co"),
        ("Cormacarena - Corp Ambiental (Meta)", "https://www.cormacarena.gov.co", "cormacarena.gov.co"),
        ("Gobernacion del Meta", "https://www.meta.gov.co", "meta.gov.co"),
        ("Alcaldia de Villavicencio", "https://www.villavicencio.gov.co", "villavicencio.gov.co"),
        ("Catastro Multiproposito", "https://www.catastromultiproposito.gov.co", "catastromultiproposito.gov.co"),
        ("DANE - Geografia y Censos", "https://www.dane.gov.co", "dane.gov.co"),
        ("Catastro Bogota", "https://www.catastrobogota.gov.co", "catastrobogota.gov.co"),
        ("Datos Abiertos Bogota", "https://datosabiertos.bogota.gov.co", "datosabiertos.bogota.gov.co"),
        ("IDECA - IDE Bogota", "https://www.ideca.gov.co", "ideca.gov.co"),
        ("RNMC - Medicion Catastral", "https://www.rnmc.gov.co", "rnmc.gov.co"),
        ("SNC - Sistema Nacional Catastral", "https://www.snc.gov.co", "snc.gov.co"),
    ],
    # ── AMBIENTAL / RECURSOS NATURALES ────────────────────────
    "ambiental": [
        ("IDEAM - Clima y Agua", "http://www.ideam.gov.co", "ideam.gov.co"),
        ("ANLA - Licencias Ambientales", "https://www.anla.gov.co", "anla.gov.co"),
        ("MinAmbiente", "https://www.minambiente.gov.co", "minambiente.gov.co"),
        ("SIAC - Info Ambiental", "https://www.siac.gov.co", "siac.gov.co"),
        ("PNN - Parques Nacionales", "https://www.parquesnacionales.gov.co", "parquesnacionales.gov.co"),
        ("Cormacarena - Corp Ambiental (Meta)", "https://www.cormacarena.gov.co", "cormacarena.gov.co"),
        ("CAR - Corp Autonomas Regionales", "https://www.car.gov.co", "car.gov.co"),
        ("ANH - Hidrocarburos", "https://www.anh.gov.co", "anh.gov.co"),
        ("ANM - Mineria", "https://www.anm.gov.co", "anm.gov.co"),
        ("UAESPNN - Unidad Parques", "https://www.uaespnn.gov.co", "uaespnn.gov.co"),
        ("FONAM - Fondo Ambiental", "https://www.fonam.gov.co", "fonam.gov.co"),
        ("MADS - Desarrollo Sostenible", "https://www.mads.gov.co", "mads.gov.co"),
    ],
    # ── PRODUCTIVO / AGRICOLA / RURAL ─────────────────────────
    "productiva": [
        ("UPRA - Planificacion Rural", "https://www.upra.gov.co", "upra.gov.co"),
        ("MinAgricultura", "https://www.minagricultura.gov.co", "minagricultura.gov.co"),
        ("ANT - Agencia Tierras", "https://www.ant.gov.co", "ant.gov.co"),
        ("ART - Agencia Renovacion del Territorio", "https://www.renovacionterritorio.gov.co", "renovacionterritorio.gov.co"),
        ("DNP - Planeacion Nacional", "https://www.dnp.gov.co", "dnp.gov.co"),
        ("MinVivienda", "https://www.minvivienda.gov.co", "minvivienda.gov.co"),
        ("ICA - Sanidad Agropecuaria", "https://www.ica.gov.co", "ica.gov.co"),
        ("Corpoica / AGROSAVIA", "https://www.agrosavia.co", "agrosavia.co"),
        ("FINAGRO - Financiamiento Rural", "https://www.finagro.com.co", "finagro.com.co"),
        ("Banco Agrario", "https://www.bancoagrario.gov.co", "bancoagrario.gov.co"),
        ("AUC - Unidad Costos", "https://www.auc.gov.co", "auc.gov.co"),
    ],
    # ── SOCIAL / SALUD / EDUCACION / TRABAJO ──────────────────
    "social": [
        ("MinSalud", "https://www.minsalud.gov.co", "minsalud.gov.co"),
        ("MinEducacion", "https://www.mineducacion.gov.co", "mineducacion.gov.co"),
        ("MinTrabajo", "https://www.mintrabajo.gov.co", "mintrabajo.gov.co"),
        ("MinCultura", "https://www.mincultura.gov.co", "mincultura.gov.co"),
        ("ICBF - Bienestar Familiar", "https://www.icbf.gov.co", "icbf.gov.co"),
        ("SENA - Formacion", "https://www.sena.edu.co", "sena.edu.co"),
        ("DPS - Prosperidad Social", "https://www.prosperidadsocial.gov.co", "prosperidadsocial.gov.co"),
        ("Colciencias / MinCiencias", "https://www.minciencias.gov.co", "minciencias.gov.co"),
        ("FOSYGA / ADRES", "https://www.adres.gov.co", "adres.gov.co"),
        ("MinDeporte", "https://www.mindeporte.gov.co", "mindeporte.gov.co"),
        ("MinIgualdad", "https://www.minigualdad.gov.co", "minigualdad.gov.co"),
    ],
    # ── ECONOMIA / HACIENDA / COMERCIO ────────────────────────
    "economica": [
        ("MinHacienda", "https://www.minhacienda.gov.co", "minhacienda.gov.co"),
        ("DIAN - Impuestos", "https://www.dian.gov.co", "dian.gov.co"),
        ("MinComercio", "https://www.mincomercio.gov.co", "mincomercio.gov.co"),
        ("SIC - Industria y Comercio", "https://www.sic.gov.co", "sic.gov.co"),
        ("Banco de la Republica", "https://www.banrep.gov.co", "banrep.gov.co"),
        ("Superfinanciera", "https://www.superfinanciera.gov.co", "superfinanciera.gov.co"),
        ("Supersociedades", "https://www.supersociedades.gov.co", "supersociedades.gov.co"),
        ("Supersalud", "https://www.supersalud.gov.co", "supersalud.gov.co"),
        ("Superservicios", "https://www.superservicios.gov.co", "superservicios.gov.co"),
        ("SuperTransporte", "https://www.supertransporte.gov.co", "supertransporte.gov.co"),
        ("SuperNotariado", "https://www.supernotariado.gov.co", "supernotariado.gov.co"),
        ("UGPP", "https://www.ugpp.gov.co", "ugpp.gov.co"),
    ],
    # ── INFRAESTRUCTURA / TRANSPORTE / TIC ────────────────────
    "infraestructura": [
        ("MinTransporte", "https://www.mintransporte.gov.co", "mintransporte.gov.co"),
        ("INVIAS - Vias Nacionales", "https://www.invias.gov.co", "invias.gov.co"),
        ("ANI - Concesiones", "https://www.ani.gov.co", "ani.gov.co"),
        ("Aerocivil", "https://www.aerocivil.gov.co", "aerocivil.gov.co"),
        ("MinTIC", "https://www.mintic.gov.co", "mintic.gov.co"),
        ("MinMinas", "https://www.minminas.gov.co", "minminas.gov.co"),
        ("AND - Agencia Digital", "https://www.and.gov.co", "and.gov.co"),
        ("RTVC - Radio Television", "https://www.rtvc.gov.co", "rtvc.gov.co"),
        ("Dimayor / Coldeportes", "https://www.mindeporte.gov.co", "mindeporte.gov.co"),
    ],
    # ── GOBIERNO / JUSTICIA / CONTROL ─────────────────────────
    "gobierno": [
        ("Datos Abiertos Colombia", "https://www.datos.gov.co", "datos.gov.co"),
        ("Gobierno Colombia", "https://www.gov.co", "gov.co"),
        ("Presidencia", "https://www.presidencia.gov.co", "presidencia.gov.co"),
        ("MinInterior", "https://www.mininterior.gov.co", "mininterior.gov.co"),
        ("MinJusticia", "https://www.minjusticia.gov.co", "minjusticia.gov.co"),
        ("Rama Judicial", "https://www.ramajudicial.gov.co", "ramajudicial.gov.co"),
        ("Registraduria", "https://www.registraduria.gov.co", "registraduria.gov.co"),
        ("Procuraduria", "https://www.procuraduria.gov.co", "procuraduria.gov.co"),
        ("Contraloria", "https://www.contraloria.gov.co", "contraloria.gov.co"),
        ("Defensoria del Pueblo", "https://www.defensoria.gov.co", "defensoria.gov.co"),
        ("MinRelaciones Exteriores", "https://www.cancilleria.gov.co", "cancilleria.gov.co"),
        ("MinDefensa", "https://www.mindefensa.gov.co", "mindefensa.gov.co"),
        ("Policia Nacional", "https://www.policia.gov.co", "policia.gov.co"),
        ("Ejercito Nacional", "https://www.ejercito.mil.co", "ejercito.mil.co"),
        ("Fiscalia", "https://www.fiscalia.gov.co", "fiscalia.gov.co"),
    ],
}


async def search_colombia(
    query: str,
    categoria: str = "catastral",
    num_por_fuente: int = 2,
) -> list[dict]:
    """Busca `query` en las fuentes oficiales de la `categoria` dada.

    Categorias: "catastral", "ambiental", "productiva", "social",
                "economica", "infraestructura", "gobierno", o "todas".
    """
    if categoria == "todas":
        fuentes = [f for v in FUENTES.values() for f in v]
    else:
        fuentes = FUENTES.get(categoria, FUENTES["gobierno"])

    results: list[dict] = []
    seen_urls: set[str] = set()

    for nombre, url_sitio, dominio in fuentes:
        site_query = f"{query} site:{dominio}"
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
                ddg_url = f"https://html.duckduckgo.com/html/?q={quote_plus(site_query)}"
                r = await client.get(ddg_url, headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                })
                if r.status_code == 200:
                    parsed = _parse_colombia_results(r.text, num_por_fuente)
                    for item in parsed:
                        url = item.get("url", "")
                        if url not in seen_urls:
                            item["source_name"] = nombre
                            item["source_url"] = url_sitio
                            item["categoria"] = categoria
                            seen_urls.add(url)
                            results.append(item)
        except Exception:
            pass

    return results


def _parse_colombia_results(html: str, max_num: int) -> list[dict]:
    """Extrae resultados del HTML de DuckDuckGo."""
    results: list[dict] = []

    # Regex parsing - mas robusto que HTMLParser para DDG
    for match in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]*)"[^>]*>([\s\S]*?)</a>',
        html,
    ):
        title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
        results.append({"title": title, "url": match.group(1), "snippet": ""})

    for i, match in enumerate(
        re.finditer(
            r'<span[^>]*class="result__snippet"[^>]*>([\s\S]*?)</span>',
            html,
        )
    ):
        if i < len(results):
            snippet = re.sub(r'<[^>]+>', '', match.group(1)).strip()
            results[i]["snippet"] = snippet

    return results[:max_num]


async def search_all_categories(query: str, num_por_fuente: int = 1) -> dict[str, list[dict]]:
    """Busca en todas las categorias y las agrupa."""
    result: dict[str, list[dict]] = {}
    for cat in ("catastral", "ambiental", "productiva", "social", "economica", "infraestructura", "gobierno"):
        result[cat] = await search_colombia(query, cat, num_por_fuente)
    return result
