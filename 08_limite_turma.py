#!/usr/bin/env python3
"""
08_limite_turma.py — Projeto 26.09 (simulador NMRM Caravelas)

Gera `dados_web/limite_turma.geojson`: o contorno externo da UNIÃO das três
unidades de conservação com a área da turma (fechada pela isóbata de 500 m),
numa feição só, sem as linhas internas de sobreposição APA / RESEX / PARNA.

PROVENIÊNCIA (mesmo padrão de `07_mare_tpxo.py`)
    Script versionado, rodado à mão; o produto também é versionado. A
    dependência de geração é `shapely` (>= 2.0), listada em
    `requirements-geracao.txt` e NÃO em `requirements.txt`: o app publicado lê
    o produto com `json` da stdlib, nunca roda este script.

    Rodar:  pip install -r requirements-geracao.txt
            python 08_limite_turma.py

ENTRADAS (não são regeneradas aqui, só lidas)
    dados_web/ucs_turma.geojson       — CNUC 07/2026 (ICMBio/MMA)
    dados_web/area_turma.geojson      — área que a turma definiu
    dados_web/isobatas_turma.geojson  — só conferido (a 500 m deve fechar a
                                        área); não entra na união

VERIFICAÇÕES IMPRESSAS
    - quanto da união das UCs fica FORA de area_turma (km²). Acima de
      CONFIG_LIMITE["tol_ucs_fora_km2"] o script PARA: a premissa de que a
      área da turma contém as UCs caiu, e a camada única não faz sentido.
    - área esférica da união vs. `config.AREA_TURMA_KM2` (elipsoidal, canônico):
      aferição de método, não número publicável (aviso se > 1 %).

Autor: Helio | Assistência: Claude
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

import config

# =============================================================================
# CONFIG
# =============================================================================

CONFIG_LIMITE = {
    "dir_saida":          config.DIR_RAIZ / "dados_web",
    "raio_terra_m":       6_371_008.8,   # raio médio (IUGG)
    "tol_ucs_fora_km2":   1.0,           # UCs fora da área da turma: para acima disto
    "tol_area_rel":       0.01,          # divergência vs. config.AREA_TURMA_KM2 (1 %)
    "nome":               "Limite da área de trabalho da turma",
    "isobata_m":          500,
    "fontes": ("CNUC 07/2026 (ICMBio/MMA); "
               "Batimetria do Brasil CPRM/ANP 2013 / GEBCO 925 m"),
    "gerado_por":         "08_limite_turma.py",
    "casas_coord":        6,             # ~0,1 m; evita ruído de float no arquivo
}


# =============================================================================
# GEODÉSIA (numpy, sem pyproj)
# =============================================================================

def _area_anel_km2(coords) -> float:
    """
    Área de um anel em lon/lat (graus) sobre a esfera de raio R, pelo
    excesso esférico (Chamberlain & Duquette, 2007, forma de arestas
    ao longo de paralelos): A = R²/2 · |Σ (λ2-λ1)(2 + sen φ1 + sen φ2)|.
    Sem pyproj; a esfera erra ~0,3 % contra o elipsoide, bem dentro da
    tolerância de 1 % pedida contra AREA_TURMA_KM2.
    """
    c = np.asarray(coords, dtype=float)
    lon = np.radians(c[:, 0])
    lat = np.radians(c[:, 1])
    lon2, lat2 = np.roll(lon, -1), np.roll(lat, -1)
    dlon = (lon2 - lon + np.pi) % (2 * np.pi) - np.pi   # salto de antimeridiano
    soma = np.sum(dlon * (2.0 + np.sin(lat) + np.sin(lat2)))
    R = CONFIG_LIMITE["raio_terra_m"]
    return abs(soma) * R * R / 2.0 / 1e6


def area_poligono_km2(poligono) -> float:
    """Área geodésica de um shapely Polygon (exterior menos furos)."""
    a = _area_anel_km2(poligono.exterior.coords)
    for furo in poligono.interiors:
        a -= _area_anel_km2(furo.coords)
    return a


def area_km2(geom) -> float:
    if geom.is_empty:
        return 0.0
    if geom.geom_type == "Polygon":
        return area_poligono_km2(geom)
    return sum(area_km2(g) for g in geom.geoms)   # Multi* / coleção


def partes(geom) -> list:
    """Lista de Polygons de uma geometria (Polygon, MultiPolygon ou coleção)."""
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [p for g in geom.geoms for p in partes(g)]


# =============================================================================
# LEITURA
# =============================================================================

def ler_poligonos(caminho: Path) -> list:
    from shapely.geometry import shape
    with open(caminho, encoding="utf-8") as f:
        gj = json.load(f)
    return [shape(feicao["geometry"]) for feicao in gj["features"]]


def main() -> int:
    from shapely import unary_union
    from shapely.geometry import mapping
    import shapely

    print(f"[LIMITE] shapely {shapely.__version__}")
    dir_web = CONFIG_LIMITE["dir_saida"]

    ucs = ler_poligonos(dir_web / config.ARQ_UCS_TURMA)
    area_lista = ler_poligonos(dir_web / config.ARQ_AREA_TURMA)
    print(f"[LIMITE] entradas: {len(ucs)} UCs | {len(area_lista)} polígono(s) de área da turma")

    for i, uc in enumerate(ucs):
        print(f"[LIMITE]   UC {i + 1}: {area_km2(uc):,.1f} km² | válida={uc.is_valid}")
    for i, a in enumerate(area_lista):
        print(f"[LIMITE]   área da turma {i + 1}: {area_km2(a):,.1f} km² | "
              f"vértices={len(a.exterior.coords)} | válida={a.is_valid}")

    # ---- Verificação: as UCs cabem dentro da área da turma? -----------------
    area_turma = unary_union(area_lista).buffer(0)
    uniao_ucs = unary_union(ucs).buffer(0)
    fora = uniao_ucs.difference(area_turma)
    km2_fora = area_km2(fora)
    km2_ucs = area_km2(uniao_ucs)
    pct = 100 * km2_fora / km2_ucs if km2_ucs else 0.0
    print(f"[VERIFICA] união das UCs = {km2_ucs:,.1f} km² | "
          f"FORA de area_turma = {km2_fora:,.2f} km² ({pct:.2f}% das UCs)")
    if km2_fora > CONFIG_LIMITE["tol_ucs_fora_km2"]:
        print(f"[VERIFICA] PARADO: {km2_fora:,.2f} km² > tolerância de "
              f"{CONFIG_LIMITE['tol_ucs_fora_km2']:.1f} km². area_turma.geojson NÃO contém "
              "as UCs como se supunha; a premissa da camada única cai. Nada foi gravado.")
        for i, p in enumerate(partes(fora), 1):
            b = p.bounds
            print(f"[VERIFICA]   pedaço {i}: {area_km2(p):,.2f} km² | "
                  f"bbox lon [{b[0]:.3f}, {b[2]:.3f}] lat [{b[1]:.3f}, {b[3]:.3f}]")
        return 1

    # ---- União ----------------------------------------------------------------
    uniao = unary_union([*ucs, *area_lista]).buffer(0)
    pedacos = partes(uniao)
    print(f"[UNIAO] {len(pedacos)} parte(s) | válida={uniao.is_valid}")
    for i, p in enumerate(pedacos, 1):
        print(f"[UNIAO]   parte {i}: {area_km2(p):,.1f} km² | "
              f"furos={len(p.interiors)} | vértices={len(p.exterior.coords)}")
    # Partes menores NÃO são descartadas: ficam todas no arquivo.

    km2 = area_km2(uniao)
    ref = config.AREA_TURMA_KM2
    dif = (km2 - ref) / ref
    # AFERIÇÃO DE MÉTODO, não número publicável. Este polígono é o mesmo de
    # area_turma.geojson (a união o devolve inalterado), então a diferença
    # contra AREA_TURMA_KM2 NÃO é divergência de geometria: é a fórmula.
    # Excesso esférico (esfera R=6371008,8 m) é a menos precisa; o valor
    # elipsoidal de config.AREA_TURMA_KM2 é o canônico.
    print(f"[AREA] aferição de método: esfera (R={CONFIG_LIMITE['raio_terra_m']:,.1f} m) = "
          f"{km2:,.1f} km² | config.AREA_TURMA_KM2 (elipsoidal, canônico) = {ref:,.1f} km² "
          f"| diferença = {100 * dif:+.2f}%")
    print("[AREA] A diferença é de FÓRMULA (esfera x elipsoide), não de geometria. "
          "O valor canônico segue sendo config.AREA_TURMA_KM2; o esférico não deve "
          "ser citado.")
    if abs(dif) > CONFIG_LIMITE["tol_area_rel"]:
        print(f"[AREA] AVISO: diverge mais que {100 * CONFIG_LIMITE['tol_area_rel']:.0f}% "
              "— aí sim, conferir a geometria antes de usar o produto.")

    # ---- Conferência da isóbata de 500 m (informativa) -------------------------
    with open(dir_web / config.ARQ_ISOBATAS_TURMA, encoding="utf-8") as f:
        iso = json.load(f)
    n500 = sum(1 for ft in iso["features"]
               if int(round(abs(ft["properties"].get("prof", 0)))) == CONFIG_LIMITE["isobata_m"])
    print(f"[VERIFICA] isóbata de {CONFIG_LIMITE['isobata_m']} m: {n500} feição(ões) no arquivo")

    # ---- Gravação ---------------------------------------------------------------
    nd = CONFIG_LIMITE["casas_coord"]

    def _arredonda(o):
        if isinstance(o, (list, tuple)):
            return [_arredonda(x) for x in o]
        return round(float(o), nd)

    geom = mapping(uniao)
    geom = {"type": geom["type"], "coordinates": _arredonda(geom["coordinates"])}

    produto = {
        "type": "FeatureCollection",
        "name": "limite_turma",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4674"}},
        "features": [{
            "type": "Feature",
            "properties": {
                "nome":       CONFIG_LIMITE["nome"],
                "area_km2_aprox_esferica": round(km2, 1),
                "metodo_area": ("excesso esférico, R=6371008.8 m — aferição; "
                                "valor canônico em config.AREA_TURMA_KM2"),
                "n_ucs":      len(ucs),
                "isobata_m":  CONFIG_LIMITE["isobata_m"],
                "fontes":     CONFIG_LIMITE["fontes"],
                "gerado_em":  date.today().isoformat(),
                "gerado_por": CONFIG_LIMITE["gerado_por"],
            },
            "geometry": geom,
        }],
    }
    destino = dir_web / config.ARQ_LIMITE_TURMA
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(produto, f, ensure_ascii=False)
    print(f"[EXPORT] {destino} ({destino.stat().st_size / 1024:.1f} KB) | "
          f"{geom['type']} | área esférica aprox. {km2:,.1f} km² (aferição)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
