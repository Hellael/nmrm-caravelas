#!/usr/bin/env python3
"""
08_prepara_camadas_turma.py — Projeto NMRM Caravelas
Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB

Regenera `ucs_turma.geojson` (as 3 UCs da área de trabalho da turma) a partir
do CNUC bruto (`ucs_regiao.geojson`, 42 UCs da região) e COMPARA o resultado
com o arquivo versionado em `dados_web/`. Existe por proveniência (regra 3 do
CLAUDE.md): o script original que filtrou o CNUC nunca entrou no repositório.

O QUE FAZ
    1. Seleciona as 3 UCs por `cd_cnuc` (APA Ponta da Baleia/Abrolhos, RESEX
       Cassurubá, PARNA Marinho dos Abrolhos).
    2. Mantém 7 dos 13 campos do CNUC, na ordem do arquivo versionado.
    3. Simplifica a geometria (Douglas-Peucker, preservando topologia).
    4. Converte MultiPolygon de uma parte só em Polygon.
    5. Rotula o CRS como EPSG:4674 SEM transformar coordenada (ver NOTA).
    6. Grava em `saidas/ucs_turma_regerado.geojson` e compara com
       `dados_web/ucs_turma.geojson`: nº de feições, códigos, nomes, campos,
       vértices, coordenadas e área.

    NÃO sobrescreve `dados_web/ucs_turma.geojson`. A troca, se houver, é
    decisão de quem confere a comparação.

ENTRADA   DIR_AUXILIAR / config.ARQ_UCS_REGIAO      (CNUC 07/2026, ICMBio/MMA)
SAÍDA     DIR_SAIDAS  / ucs_turma_regerado.geojson

DEPENDÊNCIA DE GERAÇÃO
    `shapely` (>= 2.0) — está em `requirements-geracao.txt`, NÃO no
    `requirements.txt`: o app lê o produto com `json` da stdlib.

USO
    pip install -r requirements-geracao.txt
    python 08_prepara_camadas_turma.py

NOTA CIENTÍFICA (procedência declarada, regra 1)
    - A tolerância de simplificação foi obtida por AJUSTE REVERSO contra o
      arquivo versionado: reproduz as coordenadas da RESEX Cassurubá
      exatamente (2.482 -> 249 vértices). NÃO é a receita original.
    - O CRS do CNUC é CRS84 (WGS84); o arquivo versionado o rotula como
      EPSG:4674 (SIRGAS 2000) sem alterar nenhuma coordenada. A diferença
      entre os dois datums é centimétrica a decimétrica — irrelevante numa
      camada que é só visual e não entra em nenhuma conta —, mas o rótulo é
      uma decisão de apresentação, não uma reprojeção.
    - Com ~89 m de tolerância a RESEX serve para DESENHAR sobre o mapa; para
      definir setor de análise, use a geometria cheia de `ucs_regiao.geojson`.

Autor: Helio | Assistência: Claude
"""

import json
import sys

import numpy as np

import config

# =============================================================================
# PARÂMETROS
# =============================================================================

CONFIG_CAMADAS_TURMA = {
    # UCs da área de trabalho da turma, por código CNUC (o nome tem acento e
    # muda de grafia entre versões do cadastro; o código não).
    "codigos_ucs": ["0000.29.0306", "0000.00.1808", "0000.00.0185"],
    # Campos mantidos, NA ORDEM do arquivo versionado.
    "campos": ["cd_cnuc", "nome_uc", "esfera", "categoria", "ha_total",
               "municipio", "cria_ano"],
    # Ajuste reverso contra dados_web/ucs_turma.geojson — reproduz as
    # coordenadas exatamente; NÃO é a receita original.
    "TOLERANCIA_SIMPLIFICACAO_GRAUS": 0.0008,
    "preservar_topologia": True,
    "nome_colecao": "ucs_turma",
    "rotulo_crs": "urn:ogc:def:crs:EPSG::4674",
    "arq_saida": "ucs_turma_regerado.geojson",
    "dir_versionado": config.DIR_RAIZ / "dados_web",
    "raio_terra_m": 6_371_008.8,
    "tol_area_rel": 1e-9,          # "bate" = mesma área, a menos de ruído numérico
    "tol_coord_graus": 1e-12,
}


# =============================================================================
# GEOMETRIA
# =============================================================================

def _partes(geom) -> list:
    """Lista de Polygons de um Polygon/MultiPolygon."""
    return [geom] if geom.geom_type == "Polygon" else list(geom.geoms)


def _area_km2(geom) -> float:
    """Área em km² por projeção equiretangular local (aferição, não número citável)."""
    total = 0.0
    R = CONFIG_CAMADAS_TURMA["raio_terra_m"]
    for p in _partes(geom):
        for i, anel in enumerate([p.exterior, *p.interiors]):
            c = np.asarray(anel.coords)
            lat0 = np.radians(c[:, 1].mean())
            x = np.radians(c[:, 0]) * R * np.cos(lat0)
            y = np.radians(c[:, 1]) * R
            a = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
            total += a if i == 0 else -a
    return total / 1e6


def _coords(geom) -> list:
    return [[list(anel.coords) for anel in [p.exterior, *p.interiors]] for p in _partes(geom)]


def _n_vertices(geom) -> int:
    return sum(len(a) for p in _coords(geom) for a in p)


# =============================================================================
# GERAÇÃO
# =============================================================================

def regenerar(caminho_entrada) -> dict:
    from shapely.geometry import mapping, shape

    cfg = CONFIG_CAMADAS_TURMA
    with open(caminho_entrada, encoding="utf-8") as f:
        bruto = json.load(f)
    print(f"[ENTRADA] {caminho_entrada} | {len(bruto['features'])} feições | "
          f"CRS={bruto.get('crs', {}).get('properties', {}).get('name')}")

    por_codigo = {ft["properties"]["cd_cnuc"]: ft for ft in bruto["features"]}
    faltando = [c for c in cfg["codigos_ucs"] if c not in por_codigo]
    if faltando:
        raise KeyError(f"Códigos CNUC ausentes em {caminho_entrada}: {faltando}")

    feicoes = []
    for cod in cfg["codigos_ucs"]:
        ft = por_codigo[cod]
        geom = shape(ft["geometry"])
        n0 = _n_vertices(geom)
        simples = geom.simplify(cfg["TOLERANCIA_SIMPLIFICACAO_GRAUS"],
                                preserve_topology=cfg["preservar_topologia"])
        # MultiPolygon de uma parte só vira Polygon.
        if simples.geom_type == "MultiPolygon" and len(simples.geoms) == 1:
            simples = simples.geoms[0]
        print(f"[UC] {cod} | {ft['properties']['nome_uc']} | vértices {n0} -> "
              f"{_n_vertices(simples)} | {simples.geom_type}")
        feicoes.append({
            "type": "Feature",
            "properties": {k: ft["properties"][k] for k in cfg["campos"]},
            "geometry": mapping(simples),
        })

    return {
        "type": "FeatureCollection",
        "name": cfg["nome_colecao"],
        "crs": {"type": "name", "properties": {"name": cfg["rotulo_crs"]}},
        "features": feicoes,
    }


# =============================================================================
# COMPARAÇÃO
# =============================================================================

def comparar(novo: dict, caminho_versionado) -> bool:
    from shapely.geometry import shape

    cfg = CONFIG_CAMADAS_TURMA
    with open(caminho_versionado, encoding="utf-8") as f:
        velho = json.load(f)

    print(f"[COMPARA] versionado: {caminho_versionado}")
    ok = True

    def _checa(rotulo, condicao, detalhe=""):
        nonlocal ok
        ok = ok and bool(condicao)
        print(f"[COMPARA] {'OK ' if condicao else 'DIFERE'} | {rotulo} {detalhe}")

    _checa("nº de feições", len(novo["features"]) == len(velho["features"]),
           f"({len(novo['features'])} x {len(velho['features'])})")
    _checa("rótulo de CRS", novo["crs"] == velho["crs"])
    _checa("nome da coleção", novo["name"] == velho["name"])

    velho_por_cod = {f["properties"]["cd_cnuc"]: f for f in velho["features"]}
    for fn in novo["features"]:
        cod = fn["properties"]["cd_cnuc"]
        fv = velho_por_cod.get(cod)
        if fv is None:
            _checa(f"{cod} presente no versionado", False)
            continue
        nome = fn["properties"]["nome_uc"]
        _checa(f"{cod} nome/campos", fn["properties"] == fv["properties"]
               and list(fn["properties"]) == list(fv["properties"]), f"({nome})")

        gn, gv = shape(fn["geometry"]), shape(fv["geometry"])
        _checa(f"{cod} tipo de geometria", gn.geom_type == gv.geom_type,
               f"({gn.geom_type} x {gv.geom_type})")
        _checa(f"{cod} vértices", _n_vertices(gn) == _n_vertices(gv),
               f"({_n_vertices(gn)} x {_n_vertices(gv)})")

        iguais = False
        dif_max = float("nan")
        cn, cv = _coords(gn), _coords(gv)
        if (len(cn) == len(cv) and all(len(a) == len(b) for a, b in zip(cn, cv))
                and all(len(x) == len(y) for a, b in zip(cn, cv) for x, y in zip(a, b))):
            dif_max = max((abs(np.asarray(x) - np.asarray(y)).max()
                           for a, b in zip(cn, cv) for x, y in zip(a, b)), default=0.0)
            iguais = dif_max <= cfg["tol_coord_graus"]
        _checa(f"{cod} coordenadas", iguais, f"(dif. máx. = {dif_max:.3g}°)")

        an, av = _area_km2(gn), _area_km2(gv)
        rel = abs(an - av) / av if av else float("nan")
        _checa(f"{cod} área", rel <= cfg["tol_area_rel"],
               f"({an:,.1f} x {av:,.1f} km², dif. rel. {rel:.2e}; aferição equiretangular)")

    print(f"[COMPARA] RESULTADO: {'BATEM em tudo' if ok else 'HÁ DIFERENÇAS — não propor a troca'}")
    return ok


def main() -> int:
    cfg = CONFIG_CAMADAS_TURMA
    entrada = config.DIR_AUXILIAR / config.ARQ_UCS_REGIAO
    if not entrada.exists():
        print(f"[ERRO] {entrada} não encontrado. Esse caminho vem de config.DIR_AUXILIAR "
              "(segue a variável de ambiente NMRM_DIR_DADOS).")
        return 1

    novo = regenerar(entrada)

    config.DIR_SAIDAS.mkdir(parents=True, exist_ok=True)
    saida = config.DIR_SAIDAS / cfg["arq_saida"]
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(novo, f, ensure_ascii=False)
    print(f"[EXPORT] {saida} ({saida.stat().st_size / 1024:.1f} KB) — "
          "dados_web/ucs_turma.geojson NÃO foi tocado")

    bate = comparar(novo, cfg["dir_versionado"] / config.ARQ_UCS_TURMA)
    return 0 if bate else 2


if __name__ == "__main__":
    sys.exit(main())
