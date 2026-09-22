#!/usr/bin/env python3
"""
06_diagnostico_dossel.py — Diagnóstico do viés de dossel sobre manguezal (modo local)
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB — Caravelas (BA)

OBJETIVO
    Quantificar quanto do viés de dossel sobre manguezal (regra 6 do CLAUDE.md)
    é responsável pela área classificada como "isolada" na grade de
    conectividade hidráulica — usando o MDE local em RESOLUÇÃO PLENA, sem o
    teto de 20 m do pacote web (mesma motivação de 05_valida_cobertura_elevacao.py,
    aplicada agora à conectividade em vez de só à posição no terreno).

    Este script NÃO altera nenhum dado do projeto. Só lê e reporta.

ENTRADAS (leitores existentes, nenhum flood-fill reimplementado no item 2)
    MDE completo       : config.MDE_PROCESSADO         via slr_core.carregar_dem
    Máscara de água     : config.MASCARA_AGUA           via slr_core.carregar_mascara_agua
    Cobertura local     : dados/auxiliar/<arq_cobertura_local> via cobertura.carregar_cobertura
                           (produto de 04_prepara_cobertura.py, já alinhado pixel
                           a pixel ao MDE local)

SAÍDAS (saidas/, carimbadas com a data — nunca em dados_web/)
    diagnostico_dossel_<AAAAMMDD>.csv      : itens 1-5 empilhados (coluna "experimento")
    fig_diagnostico_dossel_<AAAAMMDD>.png  : painel 2x2, +1,00 m x +2,00 m,
                                              MDE original x mangue corrigido

USO
    python 06_diagnostico_dossel.py

Autor: Helio | Assistência: Claude
"""

from __future__ import annotations

import sys
from datetime import datetime

import numpy as np
import pandas as pd
from matplotlib import colors
from scipy import ndimage

import config
import src.cobertura as cob
import src.fonte_dados as fonte
import src.slr_core as core

# =============================================================================
# 1. PARÂMETROS CENTRALIZADOS
#    Regra do projeto: nenhum limiar numérico hardcodado dentro de função.
# =============================================================================

CONFIG_DOSSEL = {
    "cotas_m":          [0.5, 1.0, 1.5, 2.0, 3.0],
    "classe_mangue":    5,     # Mangue (LEGENDA_COL11)
    "classe_apicum":    32,    # Apicum — controle interno, sem dossel
    "classe_agua_mb":   33,    # Rio, Lago e Oceano — inclui corpos INTERIORES
    "offsets_teste_m":  [0.0, 1.0, 2.0, 2.4, 3.0],

    # Offset medido no pacote WEB (teto de 20 m) em 05/09/2026, para comparação
    # com o offset empírico calculado aqui a partir do MDE completo (item 1).
    # Ver docs/validacao_mapbiomas_laudo.md §4.4 e regra 6 do CLAUDE.md.
    "offset_web_referencia_m": 4.37 - 1.91,
    "divergencia_alerta_m":    0.3,   # acima disto, o teto de 20 m distorcia a estatística

    # Cotas do painel 2x2 (item 6 — figura)
    "cotas_fig_m": [1.0, 2.0],
    "figsize":     (11, 9),
    "dpi_fig":     200,

    # Cores da figura diagnóstica — deliberadamente DIFERENTES da paleta de
    # relatório em core.CONFIG_MAPA (isolada ali é roxo): aqui o pedido é
    # inundada azul, isolada âmbar, água preexistente cinza-azul, mangue
    # verde acinzentado por baixo.
    "cores_fig": {
        "mangue_fundo":       "#7E9B80",
        "agua_preexistente":  "#5C7A99",
        "isolada":            "#D9A441",
        "inundada":           "#1F6FEB",
    },
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
# 2. LEITURA DOS DADOS (MDE completo + máscara de água + cobertura local)
# =============================================================================

def carregar_dados() -> tuple[dict, np.ndarray, dict]:
    """Carrega MDE, máscara de água e cobertura, todos na mesma grade local."""
    if not config.MDE_PROCESSADO.exists():
        raise FileNotFoundError(
            f"MDE não encontrado: {config.MDE_PROCESSADO}. "
            "Rode 01_mapa_elevacao.py primeiro."
        )
    dem_dados = core.carregar_dem(str(config.MDE_PROCESSADO))

    if not config.MASCARA_AGUA.exists():
        raise FileNotFoundError(
            f"Máscara de água não encontrada: {config.MASCARA_AGUA}. "
            "Rode 01_mapa_elevacao.py primeiro (ele gera o MDE e a máscara juntos)."
        )
    mascara_agua = core.carregar_mascara_agua(str(config.MASCARA_AGUA))
    if mascara_agua is None:
        raise FileNotFoundError(
            f"Máscara de água não pôde ser lida: {config.MASCARA_AGUA}. "
            "Rode 01_mapa_elevacao.py de novo."
        )

    caminho_cob = config.DIR_AUXILIAR / fonte.CONFIG_FONTE["arq_cobertura_local"]
    cob_dados = cob.carregar_cobertura(str(caminho_cob))
    if cob_dados is None:
        raise FileNotFoundError(
            f"Cobertura local não encontrada em {caminho_cob}. "
            "Rode 04_prepara_cobertura.py primeiro."
        )

    dem = dem_dados["dem"]
    if dem.shape != mascara_agua.shape:
        raise ValueError(
            f"Grades diferentes: MDE {dem.shape} x máscara de água "
            f"{mascara_agua.shape}. Rode 01_mapa_elevacao.py de novo."
        )
    if dem.shape != cob_dados["classes"].shape:
        raise ValueError(
            f"Grades diferentes: MDE {dem.shape} x cobertura "
            f"{cob_dados['classes'].shape}. Rode 04_prepara_cobertura.py de "
            "novo — ele alinha a cobertura pixel a pixel ao MDE local."
        )

    _print(f"[DOSSEL] grade comum: {dem.shape[0]}x{dem.shape[1]} px "
           f"| res={dem_dados['res_x']:.0f}x{dem_dados['res_y']:.0f} m")
    return dem_dados, mascara_agua, cob_dados


# =============================================================================
# 3. ITEM 1 — OFFSET EMPÍRICO (mangue x apicum, MDE completo)
# =============================================================================

def offset_empirico(dem: np.ndarray, classes: np.ndarray) -> dict:
    """
    Mediana de elevação do mangue e do apicum no recorte local, e a diferença
    entre elas — candidato a offset de dossel a subtrair do mangue.

    Compara com o valor medido no pacote web (teto de 20 m): divergência
    acima de `CONFIG_DOSSEL["divergencia_alerta_m"]` significa que o teto
    estava distorcendo a estatística (cortando a cauda alta do mangue).
    """
    cfg = CONFIG_DOSSEL
    mask_mangue = (classes == cfg["classe_mangue"]) & np.isfinite(dem)
    mask_apicum = (classes == cfg["classe_apicum"]) & np.isfinite(dem)

    if not mask_mangue.any() or not mask_apicum.any():
        raise ValueError(
            "Mangue ou apicum ausente no recorte de cobertura — impossível "
            "calcular o offset empírico. Confira 04_prepara_cobertura.py."
        )

    med_mangue = float(np.median(dem[mask_mangue]))
    med_apicum = float(np.median(dem[mask_apicum]))
    offset = med_mangue - med_apicum
    valor_web = cfg["offset_web_referencia_m"]
    diferenca = offset - valor_web
    diverge = abs(diferenca) > cfg["divergencia_alerta_m"]

    _print(f"[DOSSEL] mediana mangue={med_mangue:.2f} m (n={int(mask_mangue.sum())} px) | "
           f"mediana apicum={med_apicum:.2f} m (n={int(mask_apicum.sum())} px) | "
           f"offset empírico={offset:.2f} m")
    _print(f"[DOSSEL] offset no pacote web (teto 20 m)={valor_web:.2f} m | "
           f"diferença={diferenca:+.2f} m | "
           + ("DIVERGE mais de 0,3 m — teto de 20 m distorcia a estatística"
              if diverge else "compatível (<= 0,3 m de diferença)"))

    return {
        "experimento": "offset_empirico",
        "mediana_mangue_m": round(med_mangue, 2),
        "mediana_apicum_m": round(med_apicum, 2),
        "offset_empirico_m": round(offset, 2),
        "offset_web_referencia_m": round(valor_web, 2),
        "diferenca_vs_web_m": round(diferenca, 2),
        "diverge_mais_0_3m": diverge,
    }


# =============================================================================
# 4. LINHA-PADRÃO DE TABELA (reutilizada pelos itens 2, 4 e 5)
# =============================================================================

def _linha_tabela(cota_m: float, est: dict, experimento: str) -> dict:
    """
    Uma linha "área abaixo / inundada / isolada / % isolada" a partir do
    dicionário devolvido por `slr_core.estatisticas_area`. `pct_isolada`
    segue a MESMA convenção do core (% da área emersa TOTAL, não só da
    área abaixo da cota) — não inventa uma segunda definição.
    """
    return {
        "experimento": experimento,
        "cota_m": cota_m,
        "area_abaixo_km2": round(est["area_bathtub_km2"], 3),
        "area_inundada_km2": round(est["area_inundada_km2"], 3),
        "area_isolada_km2": round(est["area_isolada_km2"], 3),
        "pct_isolada_da_area_emersa": round(est["pct_isolada"], 2),
    }


# =============================================================================
# 5. ITENS 2 + 3 — TABELA-BASE E ANEL DE BARREIRA
# =============================================================================

def tabela_base_e_anel(dem: np.ndarray, mask_oceano: np.ndarray,
                       mascara_agua: np.ndarray, classes: np.ndarray,
                       nodata_cob: int, area_pixel_m2: float,
                       cotas: list, experimento: str = "base_mde_original"
                       ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Item 2: para cada cota, com o MDE como está, reusa
    `slr_core.mascara_inundacao` (nenhum outro flood-fill escrito aqui).

    Item 3: para a mesma máscara já calculada, tabula por classe MapBiomas
    o "anel de barreira" — pixels ACIMA da cota que encostam na área
    isolada. É o que está segurando a água em cada cenário.
    """
    estrutura = np.ones((3, 3), dtype=bool)  # conexao_8, mesma malha do core
    linhas_base, linhas_anel = [], []

    for cota in cotas:
        masks = core.mascara_inundacao(
            dem, mask_oceano, cota,
            area_pixel_m2=area_pixel_m2, mascara_agua=mascara_agua,
        )
        est = core.estatisticas_area(masks, dem, area_pixel_m2)
        linhas_base.append(_linha_tabela(cota, est, experimento))

        isolada = masks["isolada"]
        n_anel = 0
        if isolada.any():
            dilatada = ndimage.binary_dilation(isolada, structure=estrutura)
            # "acima da cota" é dem > cota (estrito) — simétrico ao "abaixo"
            # do core, que usa dem <= cota.
            anel = dilatada & ~isolada & np.isfinite(dem) & (dem > cota)
            n_anel = int(anel.sum())

            codigos = np.unique(classes[anel & (classes != nodata_cob)])
            for cod in codigos:
                m = anel & (classes == cod)
                n = int(m.sum())
                if n == 0:
                    continue
                info = cob.classe(int(cod))
                linhas_anel.append({
                    "experimento": "anel_barreira",
                    "cota_m": cota,
                    "codigo_mapbiomas": int(cod),
                    "classe_mapbiomas": info["nome"],
                    "area_anel_km2": round(n * area_pixel_m2 / 1e6, 3),
                    "cota_mediana_anel_m": round(float(np.nanmedian(dem[m])), 2),
                })

        _print(f"[DOSSEL] {experimento} | cota={cota:.2f} m | "
               f"isolada={int(isolada.sum())} px | anel={n_anel} px")

    df_anel = pd.DataFrame(linhas_anel)
    if not df_anel.empty:
        df_anel = df_anel.sort_values(
            ["cota_m", "area_anel_km2"], ascending=[True, False], ignore_index=True
        )
    return pd.DataFrame(linhas_base), df_anel


# =============================================================================
# 6. ITEM 4 — VARREDURA DE OFFSET SOBRE O MANGUE
# =============================================================================

def varredura_offset(dem: np.ndarray, mask_oceano: np.ndarray,
                     mascara_agua: np.ndarray, classes: np.ndarray,
                     area_pixel_m2: float, cotas: list, offsets: list,
                     codigo_mangue: int) -> pd.DataFrame:
    """
    Para cada offset em `CONFIG_DOSSEL["offsets_teste_m"]`, subtrai o offset
    APENAS dos pixels de mangue e recomputa a tabela do item 2. Reporta,
    por cota, quantos km² de mangue passam a inundar em relação ao offset
    0,0 m (baseline, MDE como está).
    """
    a = area_pixel_m2 / 1e6
    mask_mangue = classes == codigo_mangue
    area_mangue_total_km2 = float((mask_mangue & np.isfinite(dem)).sum()) * a
    _print(f"[DOSSEL] área total de mangue no recorte local: "
           f"{area_mangue_total_km2:.1f} km²")

    linhas = []
    mangue_inundada_por_offset: dict[float, dict[float, float]] = {}

    for offset in offsets:
        dem_off = dem.copy()
        dem_off[mask_mangue] = dem_off[mask_mangue] - offset

        mangue_inundada_por_offset[offset] = {}
        for cota in cotas:
            masks = core.mascara_inundacao(
                dem_off, mask_oceano, cota,
                area_pixel_m2=area_pixel_m2, mascara_agua=mascara_agua,
            )
            est = core.estatisticas_area(masks, dem_off, area_pixel_m2)
            linha = _linha_tabela(cota, est, f"offset_mangue_{offset:.2f}m")

            area_mangue_inund = float((mask_mangue & masks["inundada"]).sum()) * a
            linha["offset_mangue_m"] = offset
            linha["area_mangue_inundada_km2"] = round(area_mangue_inund, 3)
            mangue_inundada_por_offset[offset][cota] = area_mangue_inund
            linhas.append(linha)

        _print(f"[DOSSEL] varredura offset={offset:.2f} m concluída "
               f"({len(cotas)} cotas)")

    df = pd.DataFrame(linhas)

    base = mangue_inundada_por_offset.get(0.0)
    if base is not None:
        df["delta_mangue_vs_offset0_km2"] = df.apply(
            lambda r: round(
                mangue_inundada_por_offset[r["offset_mangue_m"]][r["cota_m"]] - base[r["cota_m"]],
                3,
            ),
            axis=1,
        )
        _print("[DOSSEL] delta calculado contra offset=0,00 m (MDE como está)")
    else:
        _print("[DOSSEL] aviso: offset 0,00 m não está em offsets_teste_m — "
               "delta_mangue_vs_offset0_km2 não pôde ser calculado")

    return df


# =============================================================================
# 7. ITEM 5 — TESTE DE CONDUTO (classe 33 do MapBiomas)
# =============================================================================

def _mascara_inundacao_com_conduto(dem: np.ndarray, mask_oceano: np.ndarray,
                                   cota_m: float, mascara_agua: np.ndarray,
                                   classes: np.ndarray, codigo_conduto: int,
                                   area_pixel_m2: float) -> dict:
    """
    Variante de `slr_core.mascara_inundacao` só para o item 5: acrescenta a
    classe MapBiomas `codigo_conduto` (33 = Rio, Lago e Oceano) ao conjunto
    CANDIDATO da conectividade, mas NUNCA ao conjunto FONTE.

    Por que não reusar `slr_core.mascara_inundacao` diretamente: a função do
    motor não tem um parâmetro para separar "conduto extra" de "fonte de
    água" — colocar a classe 33 dentro de `mascara_agua` também a tornaria
    fonte, e essa classe inclui lagoas e açudes INTERIORES, sem ligação com
    o mar. Semear a inundação a partir deles inventaria maré onde não há
    caminho hidráulico real. Aqui a classe 33 só ajuda terreno já abaixo da
    cota a se CONECTAR através dela — nunca inicia a inundação sozinha.

    Espelha a lógica de `slr_core.mascara_inundacao` (conexao_8, semeadura
    pelas bordas) usando os mesmos parâmetros de `core.CONFIG_INUNDACAO`,
    para não divergir da convenção do resto do projeto.
    """
    cfg = core.CONFIG_INUNDACAO
    estrutura = (np.ones((3, 3), dtype=bool) if cfg["conexao_8"]
                else ndimage.generate_binary_structure(2, 1))

    valido = np.isfinite(dem)
    abaixo = valido & (dem <= cota_m)
    agua = mascara_agua.astype(bool)
    # ~agua evita contar em dobro pixel que já é água preexistente.
    conduto = valido & (classes == codigo_conduto) & ~agua

    candidato = abaixo | agua | conduto
    fonte = agua.copy()
    if cfg["semear_bordas"]:
        borda = np.zeros_like(fonte)
        borda[0, :] = borda[-1, :] = True
        borda[:, 0] = borda[:, -1] = True
        fonte |= borda

    rotulos, n_rot = ndimage.label(candidato, structure=estrutura)
    fonte_dilatada = ndimage.binary_dilation(fonte, structure=estrutura)
    rot_conectados = np.unique(rotulos[fonte_dilatada & (rotulos > 0)])
    rot_conectados = rot_conectados[rot_conectados > 0]

    lut = np.zeros(n_rot + 1, dtype=bool)
    lut[rot_conectados] = True
    conectada = lut[rotulos]
    isolada = abaixo & ~conectada
    inundada = abaixo & conectada

    _print(f"[DOSSEL] conduto | cota={cota_m:.2f} m | conduto_extra={int(conduto.sum())} px "
           f"| inundada={int(inundada.sum())} px | isolada={int(isolada.sum())} px")

    return {"inundada": inundada, "isolada": isolada, "abaixo": abaixo,
            "area_pixel_m2": area_pixel_m2}


def teste_conduto(dem: np.ndarray, mask_oceano: np.ndarray,
                  mascara_agua: np.ndarray, classes: np.ndarray,
                  area_pixel_m2: float, cotas: list,
                  codigo_conduto: int) -> pd.DataFrame:
    """Repete a tabela do item 2 com a classe 33 do MapBiomas como conduto."""
    linhas = []
    for cota in cotas:
        masks = _mascara_inundacao_com_conduto(
            dem, mask_oceano, cota, mascara_agua, classes, codigo_conduto, area_pixel_m2
        )
        est = core.estatisticas_area(masks, dem, area_pixel_m2)
        linhas.append(_linha_tabela(cota, est, "conduto_classe33"))
    return pd.DataFrame(linhas)


# =============================================================================
# 8. FIGURA — PAINEL 2x2 (MDE original x mangue corrigido, +1 m x +2 m)
# =============================================================================

def montar_figura(dem_dados: dict, mask_oceano: np.ndarray,
                  mascara_agua: np.ndarray, classes: np.ndarray,
                  offset_emp_m: float):
    """
    Painel 2x2: linhas = cotas de `CONFIG_DOSSEL["cotas_fig_m"]`,
    colunas = MDE original x mangue corrigido pelo offset empírico (item 1).
    Cores fixas em `CONFIG_DOSSEL["cores_fig"]`.
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    cfg = CONFIG_DOSSEL
    dem = dem_dados["dem"]
    res = dem_dados["res_x"]
    hs = core.hillshade(dem, res)

    mask_mangue = classes == cfg["classe_mangue"]
    dem_corrigido = dem.copy()
    dem_corrigido[mask_mangue] = dem_corrigido[mask_mangue] - offset_emp_m

    agua_preexistente = mask_oceano | mascara_agua.astype(bool)
    cores = cfg["cores_fig"]
    experimentos = [
        ("MDE original", dem),
        (f"Mangue -{offset_emp_m:.2f} m (offset empírico)", dem_corrigido),
    ]

    fig, eixos = plt.subplots(2, 2, figsize=cfg["figsize"], constrained_layout=True)
    fig.patch.set_facecolor("#FFFFFF")

    for col, (rotulo_exp, dem_exp) in enumerate(experimentos):
        for row, cota in enumerate(cfg["cotas_fig_m"]):
            ax = eixos[row, col]
            masks = core.mascara_inundacao(
                dem_exp, mask_oceano, cota,
                area_pixel_m2=dem_dados["area_pixel_m2"], mascara_agua=mascara_agua,
            )

            ax.imshow(np.where(np.isfinite(dem), hs, np.nan), cmap="gray",
                      vmin=0.0, vmax=1.0, interpolation="nearest")
            ax.imshow(np.ma.masked_where(~mask_mangue, mask_mangue),
                      cmap=colors.ListedColormap([cores["mangue_fundo"]]),
                      alpha=0.55, interpolation="nearest")
            ax.imshow(np.ma.masked_where(~agua_preexistente, agua_preexistente),
                      cmap=colors.ListedColormap([cores["agua_preexistente"]]),
                      alpha=0.85, interpolation="nearest")
            if masks["isolada"].any():
                ax.imshow(np.ma.masked_where(~masks["isolada"], masks["isolada"]),
                          cmap=colors.ListedColormap([cores["isolada"]]),
                          alpha=0.85, interpolation="nearest")
            ax.imshow(np.ma.masked_where(~masks["inundada"], masks["inundada"]),
                      cmap=colors.ListedColormap([cores["inundada"]]),
                      alpha=0.85, interpolation="nearest")

            ax.set_xticks([]); ax.set_yticks([])
            ax.set_title(f"{rotulo_exp}\ncota +{cota:.2f} m", fontsize=9)

    itens = [
        Patch(fc=cores["mangue_fundo"], label="Mangue (MapBiomas)"),
        Patch(fc=cores["agua_preexistente"], label="Água preexistente (oceano/estuário)"),
        Patch(fc=cores["isolada"], label="Isolada (sem conexão hidráulica)"),
        Patch(fc=cores["inundada"], label="Inundada (conectada ao mar)"),
    ]
    fig.legend(handles=itens, loc="lower center", ncol=4, fontsize=8,
              bbox_to_anchor=(0.5, -0.03))
    fig.suptitle("Diagnóstico do viés de dossel sobre manguezal — "
                "MDE original x mangue corrigido pelo offset empírico",
                fontsize=11, weight="bold")

    return fig


# =============================================================================
# EXECUÇÃO
# =============================================================================

def main():
    _print("=" * 78)
    _print("Diagnóstico do viés de dossel sobre manguezal (modo local, MDE completo)")
    _print("=" * 78)

    dem_dados, mascara_agua, cob_dados = carregar_dados()
    dem = dem_dados["dem"]
    mask_oceano = dem_dados["mask_oceano"]
    area_pixel_m2 = dem_dados["area_pixel_m2"]
    classes = cob_dados["classes"]
    nodata_cob = cob_dados["nodata"]
    cfg = CONFIG_DOSSEL

    config.DIR_SAIDAS.mkdir(parents=True, exist_ok=True)

    # --- item 1 ---------------------------------------------------------
    _print("-" * 78); _print("[1/5] Offset empírico (mangue x apicum)"); _print("-" * 78)
    resultado_offset = offset_empirico(dem, classes)
    df_offset = pd.DataFrame([resultado_offset])

    # --- itens 2 + 3 ------------------------------------------------------
    _print("-" * 78); _print("[2/5 + 3/5] Tabela-base e anel de barreira"); _print("-" * 78)
    df_base, df_anel = tabela_base_e_anel(
        dem, mask_oceano, mascara_agua, classes, nodata_cob,
        area_pixel_m2, cfg["cotas_m"],
    )

    # --- item 4 -------------------------------------------------------
    _print("-" * 78); _print("[4/5] Varredura de offset sobre o mangue"); _print("-" * 78)
    df_varredura = varredura_offset(
        dem, mask_oceano, mascara_agua, classes, area_pixel_m2,
        cfg["cotas_m"], cfg["offsets_teste_m"], cfg["classe_mangue"],
    )

    # --- item 5 -------------------------------------------------------
    _print("-" * 78); _print("[5/5] Teste de conduto (classe 33 do MapBiomas)"); _print("-" * 78)
    df_conduto = teste_conduto(
        dem, mask_oceano, mascara_agua, classes, area_pixel_m2,
        cfg["cotas_m"], cfg["classe_agua_mb"],
    )

    # --- export CSV (tabelas empilhadas) --------------------------------
    df_csv = pd.concat(
        [df_offset, df_base, df_anel, df_varredura, df_conduto],
        ignore_index=True, sort=False,
    )
    caminho_csv = core.exportar_tabela(df_csv, "diagnostico_dossel", pasta=str(config.DIR_SAIDAS))

    # --- figura ----------------------------------------------------------
    _print("-" * 78); _print("Figura: painel 2x2"); _print("-" * 78)
    fig = montar_figura(
        dem_dados, mask_oceano, mascara_agua, classes,
        resultado_offset["offset_empirico_m"],
    )
    caminho_fig = core.salvar_figura(
        fig, "fig_diagnostico_dossel", pasta=str(config.DIR_SAIDAS), dpi=cfg["dpi_fig"]
    )

    # --- resumo ------------------------------------------------------
    _print("=" * 78)
    _print("RESUMO")
    _print("=" * 78)
    _print(f"[DOSSEL] offset empírico = {resultado_offset['offset_empirico_m']:.2f} m "
           f"(web: {resultado_offset['offset_web_referencia_m']:.2f} m, "
           f"diferença {resultado_offset['diferenca_vs_web_m']:+.2f} m)")
    _print(f"[DOSSEL] tabela do item 4 (varredura de offset):")
    with pd.option_context("display.width", 200, "display.max_columns", None):
        _print(df_varredura.to_string(index=False))
    _print(f"[DOSSEL] CSV: {caminho_csv}")
    _print(f"[DOSSEL] Figura: {caminho_fig}")
    _print("=" * 78)
    _print("Concluído. Nenhum dado do projeto foi alterado.")
    _print("=" * 78)

    return df_varredura


if __name__ == "__main__":
    main()
