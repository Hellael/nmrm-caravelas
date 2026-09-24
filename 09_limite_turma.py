#!/usr/bin/env python3
"""
09_limite_turma.py — Projeto 26.09 (simulador NMRM Caravelas)

Converte o shapefile da ÁREA DE ESTUDO DA TURMA, desenhado à mão no QGIS,
para `dados_web/limite_turma.geojson` — o arquivo que o app lê e que o modo
de uso Turma usa como recorte.

O QUE ESTE SCRIPT NÃO FAZ
    Não deriva, não simplifica e não recalcula a área. A geometria é a que o
    Helio traçou no QGIS a partir da batimetria (isóbata de 500 m) e das
    unidades de conservação; aqui ela só troca de formato, com as conferências
    abaixo. Se o traçado mudar, o certo é redesenhar no QGIS, substituir o
    shapefile em `dados_web/fonte_limite_turma/` e rodar isto de novo — nunca
    editar o GeoJSON na mão.

PROVENIÊNCIA
    O shapefile de origem é VERSIONADO junto (`dados_web/fonte_limite_turma/`,
    ~45 KB nos quatro arquivos). Ele é trabalho manual e insubstituível: se
    sumir, a definição da área de estudo some junto. Por isso ele não fica em
    `NMRM_DIR_DADOS` como o CNUC bruto do `08` — este mora no repositório.

    A dependência de geração é `pyshp` + `shapely`, listadas em
    `requirements-geracao.txt` e NÃO em `requirements.txt`: o app publicado lê
    o GeoJSON com `json` da stdlib e nunca roda este script.

    Rodar:  pip install -r requirements-geracao.txt
            python 09_limite_turma.py

CRS — POR QUE O RÓTULO É EPSG:4674 E NÃO EPSG:4326
    O shapefile vem em WGS 84 (EPSG:4326, conforme o .prj). As outras camadas
    vetoriais versionadas (`ucs_turma`, `isobatas_turma`) já são
    gravadas com o rótulo EPSG:4674 (SIRGAS 2000) e coordenadas em CRS84, sem
    transformação — ver §4 do CLAUDE.md. SIRGAS 2000 e WGS 84 diferem por
    poucos centímetros, muito abaixo do pixel de 30 m, e o resto do código
    (`core.mascara_recorte`, `core._path_geometria`, `folium`) assume esse
    rótulo para TODAS as camadas da turma. Gravar esta com outro rótulo criaria
    uma exceção silenciosa no meio do pipeline — pior que a diferença que ela
    corrigiria. NENHUMA coordenada é alterada aqui.

VERIFICAÇÕES IMPRESSAS (e quando o script PARA)
    - o .prj é geográfico em WGS 84 / SIRGAS 2000  -> PARA se for projetado;
    - toda feição é polígono                       -> PARA se não for;
    - geometria inválida é corrigida com buffer(0), e o script IMPRIME o
      motivo e o quanto a área mudou (acima de `tol_correcao_km2`, PARA);
    - feições inteiramente contidas em outra são DESCARTADAS, uma a uma, com
      área e bbox — é o caso de rascunho que sobrou dentro do polígono bom;
    - área esférica por feição e do total (aferição de método, não número
      publicável: a esfera erra ~0,3 % contra o elipsoide).

Autor: Helio (traçado no QGIS) | Assistência: Claude (conversão)
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

import config

# =============================================================================
# CONFIG — todo limiar numérico mora aqui (nunca hardcodado dentro de função)
# =============================================================================

CONFIG_LIMITE = {
    "dir_saida":        config.DIR_RAIZ / "dados_web",
    "subdir_fonte":     "fonte_limite_turma",
    "arq_fonte":        "simulador_nmrm_caravelas",   # sem extensão (pyshp)
    "raio_terra_m":     6_371_008.8,        # raio médio (IUGG)
    # buffer(0) em anel auto-interceptante corta a "orelha" do laço. Se isso
    # mudar mais que este tanto de área, não é ruído de digitalização — é
    # geometria quebrada de verdade, e aí ninguém deve seguir em frente.
    "tol_correcao_km2": 1.0,
    # Feições contidas em outra são descartadas. Abaixo desta fração de
    # sobreposição a feição é considerada "de fora" e o script PARA, porque
    # aí não é rascunho redundante, é pedaço de área que alguém perderia.
    "frac_contida_min": 0.999,
    "nome":             "Área de estudo da turma — Ecossistemas Marinhos Costeiros 2026.2",
    "fontes":           ("Traçado no QGIS por Helio Miranda a partir de: "
                         "Batimetria do Brasil CPRM/ANP 2013 (isóbata de 500 m) "
                         "e unidades de conservação do CNUC 07/2026 (ICMBio/MMA)"),
    "gerado_por":       "09_limite_turma.py",
    "casas_coord":      6,                  # ~0,1 m; evita ruído de float no arquivo
    "rotulo_crs":       "urn:ogc:def:crs:EPSG::4674",
}


# =============================================================================
# GEODÉSIA (numpy, sem pyproj)
# =============================================================================

def _area_anel_km2(coords) -> float:
    """
    Área de um anel em lon/lat (graus) sobre a esfera de raio R, pelo excesso
    esférico (Chamberlain & Duquette, 2007, forma de arestas ao longo de
    paralelos): A = R²/2 · |Σ (λ2-λ1)(2 + sen φ1 + sen φ2)|.
    Sem pyproj; a esfera erra ~0,3 % contra o elipsoide — serve para AFERIR,
    nunca para publicar.
    """
    c = np.asarray(coords, dtype=float)
    lon, lat = np.radians(c[:, 0]), np.radians(c[:, 1])
    lon2, lat2 = np.roll(lon, -1), np.roll(lat, -1)
    dlon = (lon2 - lon + np.pi) % (2 * np.pi) - np.pi   # salto de antimeridiano
    soma = np.sum(dlon * (2.0 + np.sin(lat) + np.sin(lat2)))
    R = CONFIG_LIMITE["raio_terra_m"]
    return abs(soma) * R * R / 2.0 / 1e6


def area_km2(geom) -> float:
    """Área geodésica de Polygon / MultiPolygon (exterior menos furos)."""
    if geom.is_empty:
        return 0.0
    if geom.geom_type == "Polygon":
        a = _area_anel_km2(geom.exterior.coords)
        for furo in geom.interiors:
            a -= _area_anel_km2(furo.coords)
        return a
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return sum(area_km2(g) for g in geom.geoms
                   if g.geom_type in ("Polygon", "MultiPolygon", "GeometryCollection"))
    return 0.0   # linha ou ponto que sobrou de uma interseção: área zero


def partes(geom) -> list:
    """Lista de Polygons de uma geometria."""
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [p for g in geom.geoms for p in partes(g)]


def _fmt_bbox(g) -> str:
    b = g.bounds
    return f"lon [{b[0]:.4f}, {b[2]:.4f}] lat [{b[1]:.4f}, {b[3]:.4f}]"


# =============================================================================
# LEITURA E CONFERÊNCIA
# =============================================================================

def conferir_prj(caminho: Path) -> None:
    """
    O .prj precisa ser geográfico (graus) num datum WGS 84 / SIRGAS 2000. Um
    shapefile projetado (UTM, por exemplo) passaria por aqui sem erro de
    sintaxe e sairia com coordenadas em METROS dentro de um GeoJSON rotulado
    em graus — o tipo de engano que só aparece quando o mapa fica vazio.
    """
    if not caminho.exists():
        print(f"[PRJ] AVISO: {caminho.name} não existe. Seguindo sob a suposição de "
              "coordenadas geográficas — confira o shapefile no QGIS.")
        return
    wkt = caminho.read_text(encoding="utf-8", errors="replace")
    print(f"[PRJ] {wkt.strip()[:110]}...")
    if "PROJCS" in wkt.upper():
        print("[PRJ] PARADO: o shapefile está PROJETADO (PROJCS). Este pipeline "
              "espera coordenadas geográficas em graus. Reprojete para EPSG:4326 "
              "no QGIS e rode de novo. Nada foi gravado.")
        sys.exit(1)
    datums_ok = ("WGS_1984", "WGS 84", "WGS84", "SIRGAS")
    if not any(d in wkt.upper().replace("_", "_") for d in
               [x.upper() for x in datums_ok]):
        print("[PRJ] AVISO: datum não reconhecido entre WGS 84 / SIRGAS 2000. "
              "As coordenadas NÃO são transformadas — confira antes de publicar.")


def ler_feicoes(base: Path) -> list:
    """Lê o shapefile e devolve [(indice, shapely geom)], já conferido."""
    import shapefile
    from shapely.geometry import shape

    leitor = shapefile.Reader(str(base))
    print(f"[LEITURA] {base.name}.shp | shapeType={leitor.shapeType} | "
          f"feições={len(leitor)} | campos={[f[0] for f in leitor.fields[1:]]}")
    print(f"[LEITURA] bbox do arquivo: "
          f"lon [{leitor.bbox[0]:.4f}, {leitor.bbox[2]:.4f}] "
          f"lat [{leitor.bbox[1]:.4f}, {leitor.bbox[3]:.4f}]")

    feicoes = []
    for i, forma in enumerate(leitor.shapes()):
        geom = shape(forma.__geo_interface__)
        if geom.geom_type not in ("Polygon", "MultiPolygon"):
            print(f"[LEITURA] PARADO: feição {i} é {geom.geom_type}, não polígono. "
                  "Nada foi gravado.")
            sys.exit(1)
        feicoes.append((i, geom))
    return feicoes


def corrigir(indice: int, geom):
    """
    Valida e, se preciso, corrige com buffer(0) — imprimindo o motivo e o
    quanto de área isso mexeu. Digitalização à mão no QGIS produz laço de anel
    com facilidade; o que não pode é a correção comer área de verdade.
    """
    from shapely.validation import explain_validity
    if geom.is_valid:
        print(f"[FEICAO {indice}] válida | {area_km2(geom):,.1f} km² | "
              f"{len(partes(geom))} parte(s) | {_fmt_bbox(geom)}")
        return geom

    antes = area_km2(geom)
    print(f"[FEICAO {indice}] INVÁLIDA: {explain_validity(geom)}")
    corrigida = geom.buffer(0)
    depois = area_km2(corrigida)
    delta = abs(depois - antes)
    print(f"[FEICAO {indice}] corrigida com buffer(0) | {antes:,.2f} -> {depois:,.2f} km² "
          f"(Δ {delta:,.3f} km²) | {len(partes(corrigida))} parte(s)")
    if delta > CONFIG_LIMITE["tol_correcao_km2"]:
        print(f"[FEICAO {indice}] PARADO: a correção mexeu {delta:,.2f} km², acima da "
              f"tolerância de {CONFIG_LIMITE['tol_correcao_km2']:.1f} km². Isso não é "
              "ruído de digitalização — conserte a geometria no QGIS. Nada foi gravado.")
        sys.exit(1)
    return corrigida


def descartar_contidas(feicoes: list) -> list:
    """
    Feição inteiramente dentro de outra não acrescenta área e só suja o
    desenho com um contorno interno. Descarta, dizendo qual e de que tamanho.
    Sobreposição PARCIAL não é descartada: aí o script PARA, porque duas
    feições que se cruzam pela metade são decisão de quem desenhou, não ruído.
    """
    frac = CONFIG_LIMITE["frac_contida_min"]
    manter, descartadas = [], []
    for i, g in feicoes:
        a = area_km2(g)
        dentro_de = None
        for j, outra in feicoes:
            if i == j:
                continue
            inter = area_km2(g.intersection(outra))
            if inter <= 0 or a <= 0:
                continue          # disjuntas: nada a decidir
            if inter / a >= frac:
                dentro_de = j     # ESTA feição cabe dentro da outra -> descarta
                break
            b = area_km2(outra)
            if b > 0 and inter / b >= frac:
                continue          # a OUTRA cabe dentro desta -> ela é que sai
            print(f"[SOBREPOSICAO] PARADO: feição {i} cruza a {j} em {inter:,.2f} km² "
                  f"({100 * inter / a:.1f}% da {i}, {100 * inter / b:.1f}% da {j}), sem "
                  "que uma contenha a outra. Sobreposição parcial é decisão de quem "
                  "desenhou — resolva no QGIS. Nada foi gravado.")
            sys.exit(1)
        if dentro_de is None:
            manter.append((i, g))
        else:
            descartadas.append((i, g, dentro_de))

    for i, g, j in descartadas:
        print(f"[DESCARTE] feição {i} ({area_km2(g):,.2f} km², {_fmt_bbox(g)}) está "
              f"inteiramente dentro da feição {j} — descartada (não muda a área).")
    if not manter:
        print("[DESCARTE] PARADO: sobrou zero feição. Nada foi gravado.")
        sys.exit(1)
    return manter


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    from shapely import unary_union
    from shapely.geometry import mapping
    import shapely

    cfg = CONFIG_LIMITE
    print(f"[LIMITE] shapely {shapely.__version__}")
    dir_fonte = cfg["dir_saida"] / cfg["subdir_fonte"]
    base = dir_fonte / cfg["arq_fonte"]

    if not (base.with_suffix(".shp")).exists():
        print(f"[LIMITE] PARADO: {base}.shp não encontrado. O shapefile de origem é "
              "versionado junto do repositório — se ele sumiu, recupere do git. "
              "Nada foi gravado.")
        return 1

    conferir_prj(base.with_suffix(".prj"))
    feicoes = [(i, corrigir(i, g)) for i, g in ler_feicoes(base)]
    feicoes = descartar_contidas(feicoes)

    limite = unary_union([g for _, g in feicoes]).buffer(0)
    pecas = partes(limite)
    km2 = area_km2(limite)
    n_vert = sum(len(p.exterior.coords) for p in pecas)
    n_furos = sum(len(p.interiors) for p in pecas)
    print(f"[LIMITE] {limite.geom_type} | {len(pecas)} parte(s) | {n_vert} vértices | "
          f"{n_furos} furo(s) | válido={limite.is_valid}")
    print(f"[AREA] {km2:,.1f} km² (esfera, R={cfg['raio_terra_m']:,.1f} m) — AFERIÇÃO. "
          "Para citar, recalcule no elipsoide; a esfera erra ~0,3 %.")
    print("[AREA] lembrete: estes km² são a EXTENSÃO do polígono, quase toda "
          "plataforma continental. Os km² que o simulador conta são só a TERRA "
          "que o MDE cobre dentro dele — número bem menor, e é o que a interface "
          "mostra.")

    # ---- Gravação -----------------------------------------------------------
    nd = cfg["casas_coord"]

    def _arredonda(o):
        if isinstance(o, (list, tuple)):
            return [_arredonda(x) for x in o]
        return round(float(o), nd)

    geom = mapping(limite)
    geom = {"type": geom["type"], "coordinates": _arredonda(geom["coordinates"])}

    produto = {
        "type": "FeatureCollection",
        "name": "limite_turma",
        "crs": {"type": "name", "properties": {"name": cfg["rotulo_crs"]}},
        "features": [{
            "type": "Feature",
            "properties": {
                "nome":       cfg["nome"],
                "area_km2_aprox_esferica": round(km2, 1),
                "metodo_area": ("excesso esférico, R=6371008.8 m — aferição, "
                                "não número publicável"),
                "n_vertices": n_vert,
                "fontes":     cfg["fontes"],
                "origem":     (f"{cfg['subdir_fonte']}/{cfg['arq_fonte']}.shp "
                               "(shapefile versionado neste repositório)"),
                "crs_origem": "EPSG:4326 (WGS 84); coordenadas não transformadas — "
                              "ver o cabeçalho de 09_limite_turma.py",
                "gerado_em":  date.today().isoformat(),
                "gerado_por": cfg["gerado_por"],
            },
            "geometry": geom,
        }],
    }
    destino = cfg["dir_saida"] / config.ARQ_LIMITE_TURMA
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(produto, f, ensure_ascii=False)
    print(f"[EXPORT] {destino} ({destino.stat().st_size / 1024:.1f} KB) | "
          f"{geom['type']} | {n_vert} vértices")
    return 0


if __name__ == "__main__":
    sys.exit(main())
