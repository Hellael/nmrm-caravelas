#!/usr/bin/env python3
"""
05_valida_cobertura_elevacao.py — Cobertura MapBiomas x elevação FABDEM (modo local)
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB — Caravelas (BA)

Refaz, com o MDE COMPLETO (sem o teto artificial de +20 m do modo web), as
estatísticas de `docs/validacao_mapbiomas_laudo.md` §4.4: posição no terreno
de cada classe de cobertura, adjacência espacial e distância ao manguezal.
Existe para responder uma pergunta só: o viés de dossel sobre o mangue
(regra 6 do CLAUDE.md) se confirma fora da faixa achatada pelo clamp do MDE
leve, ou era artefato do teto?

ENTRADA
    MDE completo   : config.MDE_PROCESSADO (produto do 01_mapa_elevacao.py)
    Cobertura local: dados/auxiliar/<arq_cobertura_local> (produto do
                     04_prepara_cobertura.py, já alinhado pixel a pixel ao MDE)

SAÍDAS (saidas/, carimbadas com a data)
    elevacao_cobertura_<data>.csv     : item (a)+(b) — percentis e fração abaixo de cota
    adjacencia_cobertura_<data>.csv   : item (c) — vizinhança em janela 5x5 (150 m)
    distancia_manguezal_<data>.csv    : item (d) — distância euclidiana ao mangue

USO
    python 05_valida_cobertura_elevacao.py

Autor: Helio | Assistência: Claude
"""

from __future__ import annotations

import sys
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import ndimage

import config
import src.cobertura as cob
import src.fonte_dados as fonte
import src.slr_core as core

# =============================================================================
# 1. PARÂMETROS CENTRALIZADOS
# =============================================================================

CONFIG_VALIDACAO = {
    "percentis": [10, 25, 50, 75, 90],
    "niveis_corte_m": [0.5, 1.0, 2.0, 3.0],

    # 5x5 px a 30 m/px = 150 m de lado — mesma janela do §4.1 do laudo.
    "janela_adjacencia_px": 5,

    # (A, B): fração dos pixels de A que têm B na vizinhança da janela acima.
    "pares_adjacencia": [
        ("apicum", "mangue"),
        ("mangue", "apicum"),
        ("apicum", "restinga_herbacea"),
        ("restinga_herbacea", "apicum"),
        ("mangue", "silvicultura"),
        ("silvicultura", "mangue"),
        ("mangue", "campo_alagado"),
        ("campo_alagado", "mangue"),
    ],

    # Distância euclidiana até o pixel de mangue mais próximo, para estas classes.
    "classes_distancia_mangue": [
        "silvicultura", "apicum", "restinga_herbacea", "pastagem",
    ],
    "distancia_limiar_m": 150.0,
}

# Nome curto -> código oficial da legenda (src/cobertura.LEGENDA_COL11).
CODIGOS_CLASSE = {
    "formacao_florestal": 3,
    "mangue": 5,
    "silvicultura": 9,
    "campo_alagado": 11,
    "pastagem": 15,
    "apicum": 32,
    "restinga_arborea": 49,
    "restinga_herbacea": 50,
}


def _print(msg: str) -> None:
    """Print à prova de console cp1252 (Windows) — mesma rede de segurança
    de `slr_core._print` e `src/cobertura._print`."""
    try:
        print(msg)
    except UnicodeEncodeError:
        cod = getattr(sys.stdout, "encoding", None) or "ascii"
        print(msg.encode(cod, errors="replace").decode(cod, errors="replace"))


def _carimbo() -> str:
    return datetime.now().strftime("%Y%m%d")


# =============================================================================
# 2. LEITURA DOS DADOS (MDE completo + cobertura local, mesma grade)
# =============================================================================

def carregar_dados() -> tuple[dict, dict]:
    dem_dados = core.carregar_dem(str(config.MDE_PROCESSADO))

    caminho_cob = config.DIR_AUXILIAR / fonte.CONFIG_FONTE["arq_cobertura_local"]
    cob_dados = cob.carregar_cobertura(str(caminho_cob))
    if cob_dados is None:
        raise FileNotFoundError(
            f"Cobertura local não encontrada em {caminho_cob}. "
            "Rode 04_prepara_cobertura.py primeiro."
        )

    if dem_dados["dem"].shape != cob_dados["classes"].shape:
        raise ValueError(
            f"Grades diferentes: MDE {dem_dados['dem'].shape} x "
            f"cobertura {cob_dados['classes'].shape}. Rode 04_prepara_cobertura.py "
            "de novo — ele alinha a cobertura pixel a pixel ao MDE local."
        )

    _print(f"[VALIDA] grade comum: {dem_dados['dem'].shape[0]}x{dem_dados['dem'].shape[1]} px "
           f"| res={dem_dados['res_x']:.0f}x{dem_dados['res_y']:.0f} m")
    return dem_dados, cob_dados


# =============================================================================
# 3. (a)+(b) ELEVAÇÃO POR CLASSE E FRAÇÃO ABAIXO DE COTA
# =============================================================================

def elevacao_por_classe(dem: np.ndarray, classes: np.ndarray, nodata: int) -> pd.DataFrame:
    niveis = CONFIG_VALIDACAO["niveis_corte_m"]
    percentis = CONFIG_VALIDACAO["percentis"]

    codigos = np.unique(classes[classes != nodata])
    linhas = []
    for cod in codigos:
        info = cob.classe(int(cod))
        mask = classes == cod
        n_px = int(mask.sum())

        z = dem[mask]
        z_valido = z[np.isfinite(z)]
        pct_valido = 100.0 * z_valido.size / n_px if n_px else 0.0

        linha = {
            "Código": int(cod),
            "Classe": info["nome"],
            "n_px": n_px,
            "% z válido": round(pct_valido, 1),
        }
        if z_valido.size:
            for p, valor in zip(percentis, np.percentile(z_valido, percentis)):
                linha[f"p{p}_m"] = round(float(valor), 2)
        else:
            for p in percentis:
                linha[f"p{p}_m"] = np.nan

        # NaN comparado com qualquer cota dá False — pixel sem z válido não
        # entra na contagem de "abaixo da cota", exatamente como não deveria.
        for corte in niveis:
            linha[f"% abaixo de {corte:g} m"] = round(100.0 * float((z < corte).sum()) / n_px, 1)

        linhas.append(linha)
        _print(f"[ELEVACAO] {info['nome']:35s} | n={n_px:8d} px | "
               f"z_valido={pct_valido:5.1f}% | mediana={linha.get('p50_m', float('nan')):6.2f} m")

    return pd.DataFrame(linhas).sort_values("n_px", ascending=False, ignore_index=True)


# =============================================================================
# 4. (c) ADJACÊNCIA EM JANELA 5x5 (150 m)
# =============================================================================

def adjacencia(classes: np.ndarray) -> pd.DataFrame:
    janela = CONFIG_VALIDACAO["janela_adjacencia_px"]
    linhas = []

    # Cache de máscara "B na vizinhança" por classe B — cada uma é usada duas
    # vezes na lista de pares (uma como A, outra como B).
    vizinhanca_cache: dict[str, np.ndarray] = {}

    def _vizinhanca(nome_b: str) -> np.ndarray:
        if nome_b not in vizinhanca_cache:
            mask_b = classes == CODIGOS_CLASSE[nome_b]
            vizinhanca_cache[nome_b] = ndimage.maximum_filter(mask_b, size=janela)
        return vizinhanca_cache[nome_b]

    for nome_a, nome_b in CONFIG_VALIDACAO["pares_adjacencia"]:
        mask_a = classes == CODIGOS_CLASSE[nome_a]
        n_a = int(mask_a.sum())
        if n_a == 0:
            continue
        n_com_b = int((mask_a & _vizinhanca(nome_b)).sum())
        pct = 100.0 * n_com_b / n_a
        rotulo = f"{cob.nome_classe(CODIGOS_CLASSE[nome_a])} com {cob.nome_classe(CODIGOS_CLASSE[nome_b])} na vizinhança"
        linhas.append({
            "Classe A": cob.nome_classe(CODIGOS_CLASSE[nome_a]),
            "Classe B (vizinhança)": cob.nome_classe(CODIGOS_CLASSE[nome_b]),
            "% de A com B a <= 150 m": round(pct, 1),
        })
        _print(f"[ADJACENCIA] {rotulo}: {pct:.1f}%")

    return pd.DataFrame(linhas)


# =============================================================================
# 5. (d) DISTÂNCIA EUCLIDIANA AO MANGUE
# =============================================================================

def distancia_ao_mangue(classes: np.ndarray, res_x: float, res_y: float) -> pd.DataFrame:
    limiar = CONFIG_VALIDACAO["distancia_limiar_m"]
    mask_mangue = classes == CODIGOS_CLASSE["mangue"]

    # distance_transform_edt mede a partir dos pixels ONDE o array é zero —
    # por isso o `~mask_mangue`: distância de cada pixel até o mangue mais
    # próximo. `sampling` converte índice de pixel para metros nos dois eixos.
    dist_m = ndimage.distance_transform_edt(~mask_mangue, sampling=(res_y, res_x))

    linhas = []
    for nome in CONFIG_VALIDACAO["classes_distancia_mangue"]:
        mask = classes == CODIGOS_CLASSE[nome]
        d = dist_m[mask]
        if d.size == 0:
            continue
        mediana = float(np.median(d))
        p10 = float(np.percentile(d, 10))
        pct_perto = 100.0 * float((d <= limiar).sum()) / d.size
        linhas.append({
            "Classe": cob.nome_classe(CODIGOS_CLASSE[nome]),
            "mediana_m": round(mediana, 0),
            "p10_m": round(p10, 0),
            f"% a <= {limiar:g} m": round(pct_perto, 1),
        })
        _print(f"[DISTANCIA] {cob.nome_classe(CODIGOS_CLASSE[nome]):35s} | "
               f"mediana={mediana:8.0f} m | {pct_perto:5.1f}% a <= {limiar:g} m")

    return pd.DataFrame(linhas)


# =============================================================================
# EXECUÇÃO
# =============================================================================

def main():
    _print("=" * 78)
    _print("Validação cobertura MapBiomas x elevação FABDEM — MDE completo (modo local)")
    _print("=" * 78)

    dem_dados, cob_dados = carregar_dados()
    dem = dem_dados["dem"]
    classes = cob_dados["classes"]
    nodata = cob_dados["nodata"]

    config.DIR_SAIDAS.mkdir(parents=True, exist_ok=True)
    carimbo = _carimbo()

    df_elevacao = elevacao_por_classe(dem, classes, nodata)
    caminho_elevacao = config.DIR_SAIDAS / f"elevacao_cobertura_{carimbo}.csv"
    df_elevacao.to_csv(caminho_elevacao, index=False, encoding="utf-8-sig")
    _print(f"[SAIDA] {caminho_elevacao}")

    df_adjacencia = adjacencia(classes)
    caminho_adjacencia = config.DIR_SAIDAS / f"adjacencia_cobertura_{carimbo}.csv"
    df_adjacencia.to_csv(caminho_adjacencia, index=False, encoding="utf-8-sig")
    _print(f"[SAIDA] {caminho_adjacencia}")

    df_distancia = distancia_ao_mangue(classes, dem_dados["res_x"], dem_dados["res_y"])
    caminho_distancia = config.DIR_SAIDAS / f"distancia_manguezal_{carimbo}.csv"
    df_distancia.to_csv(caminho_distancia, index=False, encoding="utf-8-sig")
    _print(f"[SAIDA] {caminho_distancia}")

    # Veredito direto sobre a regra 6 do CLAUDE.md: com o MDE completo, o
    # mangue ainda aparece mais alto que o apicum?
    med_mangue = df_elevacao.loc[df_elevacao["Classe"] == "Mangue", "p50_m"]
    med_apicum = df_elevacao.loc[df_elevacao["Classe"] == "Apicum", "p50_m"]
    if len(med_mangue) and len(med_apicum):
        mm, ma = float(med_mangue.iloc[0]), float(med_apicum.iloc[0])
        _print("-" * 78)
        if mm > ma:
            _print(f"[VEREDITO] CONFIRMA o viés de dossel: mangue (mediana {mm:.2f} m) "
                   f"segue ACIMA do apicum ({ma:.2f} m) mesmo com o MDE completo, sem "
                   "o teto de +20 m. A regra 6 do CLAUDE.md continua de pé.")
        else:
            _print(f"[VEREDITO] NÃO confirma: mangue (mediana {mm:.2f} m) ficou abaixo "
                   f"ou igual ao apicum ({ma:.2f} m) com o MDE completo. Revisar a "
                   "regra 6 do CLAUDE.md antes de manter a restrição.")

    _print("=" * 78)
    _print("Concluído.")
    _print("=" * 78)


if __name__ == "__main__":
    main()
