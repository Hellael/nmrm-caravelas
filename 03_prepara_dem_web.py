#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
03_prepara_dem_web.py — Projeto 26.09 (NMRM Caravelas)

Gera a versao leve dos dados para publicacao do simulador na web,
MANTENDO a resolucao original de 30 m.

Etapas:
    0. Leitura (DEM + mascara d'agua + cobertura MapBiomas local, se existir)
    1. Recorte da extensao para a planicie costeira
    1b. Mascara de caminho hidraulico (canais MapBiomas classe 33)
    2. Clamp do terreno alto (acima do teto, tudo vira o teto)
    3. Conversao float32 (m) -> int16 (cm)
    4. Escrita comprimida (DEFLATE + predictor=2)
    5. Raster(s) de limiar de conexao hidraulica (pre-computados, com e sem canais)
    6. Validacao hipsometrica recorte x extensao completa

Entrada  : DEM 30 m + mascara d'agua produzidos por 01_mapa_elevacao.py
           + cobertura MapBiomas local produzida por 04_prepara_cobertura.py (opcional)
Saida    : dados_web/ com os rasters + metadados.json

v1.4 — canais do MapBiomas (classe 33, "Rio, Lago e Oceano") passam a
funcionar como CAMINHO hidraulico, nao como fonte: ver
`src.slr_core.CONFIG_INUNDACAO["caminhos_canais"]` para o conceito e a
salvaguarda de cota. Este script gera DOIS rasters de limiar — um sem
canais (comportamento anterior, preservado) e um com — para a interface
poder mostrar os dois números lado a lado.

Autor: Helio | FAOC/DOB - UERJ
"""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")  # precisa vir antes de importar src.slr_core (ver 01_mapa_elevacao.py)
import rasterio
from rasterio.windows import Window
from scipy import ndimage

import config
import src.slr_core as core

# =============================================================================
# CONFIGURACAO — todo parametro numerico fica aqui
# =============================================================================

CONFIG = {
    # --- Arquivos de entrada (dentro de NMRM_DIR_DADOS) ---
    "arq_dem": "processado/caravelas_fabdem_utm24s_30m.tif",
    "arq_agua": "processado/caravelas_mascara_agua_utm24s_30m.tif",
    # Margem d'água real (v1.4b), produto do 01_mapa_elevacao.py: fica como
    # terra na área mas conduz conexão. Camada OPCIONAL só por compatibilidade
    # com dados locais gerados antes da v1.4b — se faltar, os dois rasters de
    # limiar saem sem essa correção (avisado no console).
    "arq_margem": "processado/caravelas_mascara_margem_utm24s_30m.tif",
    # Cobertura MapBiomas local, produto do 04_prepara_cobertura.py, já
    # alinhada pixel a pixel ao MDE (config.DIR_AUXILIAR). Camada OPCIONAL:
    # se faltar, este script gera só o raster de limiar SEM canais.
    "arq_cobertura_local": "caravelas_mapbiomas_col11_2025_utm24s_30m.tif",

    # --- Saida (dentro do repositorio, para versionar no GitHub) ---
    "dir_saida": "dados_web",

    # --- Recorte -------------------------------------------------------------
    # None  -> deriva automaticamente do terreno baixo conectado ao oceano
    # tupla -> (xmin, ymin, xmax, ymax) em metros, EPSG:31984
    "bbox_manual": None,
    "bbox_elev_max_m": 25.0,   # cota usada para delimitar a planicie costeira
    "bbox_buffer_km": 5.0,     # folga adicionada em cada lado

    # --- Clamp ---------------------------------------------------------------
    # Terreno acima deste valor vira exatamente este valor.
    # ATENCAO: cria um TETO. Cenarios acima dele ficam sem sentido fisico.
    "clamp_m": 20.0,

    # --- Raster de limiar ----------------------------------------------------
    "limiar_nivel_max_m": 20.0,   # ate onde pre-computar
    "limiar_passo_fino_cm": 5,    # passo abaixo de limiar_troca_passo_m
    "limiar_passo_grosso_cm": 25, # passo acima
    # 5.5 m cobre toda a cota alcancavel pela interface: slider NMRM ate 3.0 m
    # + sobrelevacao meteorologica ate 2.0 m + folga. A consulta e' limiar <=
    # cota_cm; com passo grosso (25 cm) nessa faixa, uma cota de 4.60 m daria o
    # mesmo resultado que 4.50 m em silencio, e a curva ali vale ~161 km2/m.
    "limiar_troca_passo_m": 5.5,   # era 3.0

    # --- Conectividade hidraulica -------------------------------------------
    # 4 = vizinhanca de aresta (conservador) | 8 = inclui diagonais
    # DEVE ser igual ao usado em 02_simulador_nmrm.py
    # slr_core.mascara_inundacao usa conexao_8=True (np.ones((3,3))) por padrao,
    # e 02_simulador_nmrm.py nao sobrescreve esse default -> vizinhanca 8.
    "conectividade": 8,

    # --- Semeadura de bordas ----------------------------------------------
    # slr_core.mascara_inundacao semeia agua tambem pelas BORDAS do recorte
    # quando CONFIG_INUNDACAO["semear_bordas"] e True (padrao, e valor usado
    # pela interface). O raster de limiar TEM de ser gerado com o mesmo valor,
    # senao nao reproduz o flood-fill em tempo real.
    "semear_bordas": True,

    # --- Canais MapBiomas como caminho hidraulico (v1.4) ---------------------
    # Lidos de slr_core.CONFIG_INUNDACAO para NUNCA duplicar o numero: se
    # alguem mudar a cota de salvaguarda ou a lista de classes ali, este
    # script tem que acompanhar sem precisar de segunda edicao.
    "classes_caminho": core.CONFIG_INUNDACAO["classes_caminho"],
    "caminho_cota_max_m": core.CONFIG_INUNDACAO["caminho_cota_max_m"],

    # --- Codificacao ---------------------------------------------------------
    "nodata_saida": -32768,       # sentinela int16
    "fator_escala": 100.0,        # metros -> centimetros
    "nunca_alaga": 32767,         # valor do limiar para pixel que nunca conecta

    # --- Compressao ----------------------------------------------------------
    "compressao": "DEFLATE",
    "predictor": 2,
    "nivel_zlib": 9,
    "tamanho_bloco": 512,

    # --- Validacao -----------------------------------------------------------
    # Valor de referencia calculado na extensao completa, modo local.
    # v1.4/v1.4b: recalculado duas vezes.
    #   v1.3 -> v1.4  (Parte 1, mascara de agua na grade nativa com
    #                  Resampling.max): 70.6 -> 58.5 km2. Motivo da queda:
    #                  margem/canal que antes ficava com cota artificialmente
    #                  baixa (bilinear misturando o 0.0 da agua antes do teste
    #                  de mascara) contava como "terreno baixo" nessa
    #                  comparacao; com a mascara corrigida, esses pixels
    #                  passaram a ser reconhecidos como agua e sairam da conta
    #                  de terra (mascara agressiva demais: Resampling.max).
    #   v1.4 -> v1.4b (agua_area por Resampling.average, limiar 0.5, no lugar
    #                  do Resampling.max cru): 58.5 -> 59.8 km2. Motivo da
    #                  subida: agua_area e' menos agressiva — so sai da terra
    #                  o pixel com MAIORIA de agua real; pixels de margem
    #                  (< 50% de agua) voltam a contar como terra (e a
    #                  conduzir conexao via agua_margem).
    # Medido em 16/09/2026, ver print "[1] Referencia 'area abaixo de 2 m'".
    "ref_area_abaixo_2m_km2": 59.8,
    "tolerancia_validacao": 0.02,  # 2 %
}

ESTRUTURA = ndimage.generate_binary_structure(2, 1 if CONFIG["conectividade"] == 4 else 2)


# =============================================================================
# UTILITARIOS
# =============================================================================

def log(etapa, msg):
    print(f"[{etapa}] {msg}", flush=True)


def tamanho_mb(caminho):
    return Path(caminho).stat().st_size / (1024 ** 2)


def memoria_mb(arr):
    return arr.nbytes / (1024 ** 2)


def resolver_dir_dados():
    d = os.environ.get("NMRM_DIR_DADOS")
    if not d:
        sys.exit("ERRO: variavel de ambiente NMRM_DIR_DADOS nao definida.")
    d = Path(d)
    if not d.exists():
        sys.exit(f"ERRO: NMRM_DIR_DADOS aponta para caminho inexistente: {d}")
    return d


def _transforms_iguais(t1, t2, tol=1e-6):
    return all(abs(float(a) - float(b)) < tol for a, b in zip(t1, t2))


def verificar_alinhamento_cobertura_web(dir_saida, transform_novo):
    """
    Se a janela do recorte mudar (por exemplo, por causa da Parte 1 — a
    máscara de água na grade nativa altera o que conta como "terreno baixo
    conectado ao oceano" e pode deslocar o recorte automático), o
    `cobertura_web.tif` gerado por `04_prepara_cobertura.py` na execução
    anterior fica desalinhado do novo `dem_30m_web.tif`. Só avisa — não
    regenera nem apaga nada aqui.
    """
    cam_cob_web = Path(dir_saida) / "cobertura_web.tif"
    if not cam_cob_web.exists():
        return
    with rasterio.open(cam_cob_web) as src:
        transform_cob = src.transform
    if not _transforms_iguais(transform_cob, transform_novo):
        log("AVISO", f"{cam_cob_web.name} existe mas tem transform DIFERENTE "
                     "do novo dem_30m_web.tif — a janela do recorte mudou. "
                     "Rode `python 04_prepara_cobertura.py` de novo para realinhar "
                     "a cobertura à nova grade antes de publicar.")


def perfil_saida(base, dtype, nodata, altura, largura, transform):
    """Perfil rasterio padronizado: comprimido, com tiles e predictor."""
    p = base.copy()
    p.update(
        driver="GTiff",
        dtype=dtype,
        nodata=nodata,
        height=altura,
        width=largura,
        transform=transform,
        count=1,
        compress=CONFIG["compressao"],
        predictor=CONFIG["predictor"],
        zlevel=CONFIG["nivel_zlib"],
        tiled=True,
        blockxsize=CONFIG["tamanho_bloco"],
        blockysize=CONFIG["tamanho_bloco"],
        BIGTIFF="IF_SAFER",
    )
    return p


# =============================================================================
# NUCLEO — inundacao conectada
# =============================================================================

def inundacao_conectada(dem_cm, mascara_agua, valido, nivel_cm,
                        semear_bordas=True, caminho=None):
    """
    Retorna mascara booleana dos pixels inundados E hidraulicamente
    conectados ao oceano no nivel de mar informado (em cm).

    Logica IDENTICA a slr_core.mascara_inundacao (modo conectado):
      - a agua entra no proprio conjunto rotulado (candidato = abaixo | agua),
        nao so como vizinho externo, para propagar por canais;
      - `caminho` (opcional): pixels de canal MapBiomas entram em `candidato`
        (conduzem) mas NUNCA em `fonte` (nao injetam agua sozinhos) — mesmo
        conceito caminho != fonte de slr_core.mascara_caminho;
      - a fonte de conexao e' a mascara d'agua MAIS, se semear_bordas, as
        quatro bordas do recorte (evita confinamento artificial quando o
        recorte corta a planicie);
      - um componente conecta se a fonte DILATADA o alcanca.

    `semear_bordas` deve casar com CONFIG_INUNDACAO["semear_bordas"] usado
    pela interface, senao o raster de limiar diverge do flood-fill.
    """
    candidato = (valido & (dem_cm <= nivel_cm)) | mascara_agua
    if caminho is not None:
        candidato = candidato | caminho

    fonte = mascara_agua.copy()
    if semear_bordas:
        fonte[0, :] = fonte[-1, :] = True
        fonte[:, 0] = fonte[:, -1] = True

    rotulos, n = ndimage.label(candidato, structure=ESTRUTURA)
    if n == 0:
        return np.zeros(dem_cm.shape, dtype=bool)

    fonte_dilatada = ndimage.binary_dilation(fonte, structure=ESTRUTURA)
    rot = np.unique(rotulos[fonte_dilatada & (rotulos > 0)])
    rot = rot[rot > 0]

    # Lookup table e' bem mais rapido que np.isin em arrays grandes
    tabela = np.zeros(n + 1, dtype=bool)
    tabela[rot] = True
    return tabela[rotulos]


# =============================================================================
# ETAPA 0 — leitura
# =============================================================================

def carregar_cobertura_local(shape_dem, transform_dem):
    """
    Lê a cobertura MapBiomas local (produto do 04_prepara_cobertura.py),
    já alinhada à grade do MDE. Camada OPCIONAL: se o arquivo não existir,
    devolve None e o resto do script segue gerando só o limiar sem canais.

    Se o arquivo EXISTIR mas não bater shape/transform com o MDE, aborta com
    erro claro — nunca reamostra a cobertura em silêncio (dado categórico).
    """
    caminho = config.DIR_AUXILIAR / CONFIG["arq_cobertura_local"]
    if not caminho.exists():
        log("0", f"cobertura MapBiomas ausente em {caminho} — este raster de "
                 "canais NÃO será gerado. Rode 04_prepara_cobertura.py para "
                 "habilitar canais como caminho hidráulico.")
        return None

    with rasterio.open(caminho) as src:
        cobertura = src.read(1)
        transform_cob = src.transform

    if cobertura.shape != shape_dem:
        sys.exit(f"ERRO: cobertura {cobertura.shape} != MDE {shape_dem}. "
                 f"Rode 04_prepara_cobertura.py de novo para realinhar à grade atual.")
    if not _transforms_iguais(transform_cob, transform_dem):
        sys.exit("ERRO: transform da cobertura difere do MDE.\n"
                 f"  cobertura: {tuple(transform_cob)}\n"
                 f"  MDE      : {tuple(transform_dem)}\n"
                 "  Rode 04_prepara_cobertura.py de novo para realinhar à grade atual.")

    log("0", f"Cobertura MapBiomas: {caminho.name} | {cobertura.shape[0]}x{cobertura.shape[1]} px")
    return cobertura


def etapa_0_ler(dir_dados):
    cam_dem = dir_dados / CONFIG["arq_dem"]
    cam_agua = dir_dados / CONFIG["arq_agua"]

    for c in (cam_dem, cam_agua):
        if not c.exists():
            sys.exit(f"ERRO: arquivo nao encontrado: {c}\n"
                     f"      Ajuste CONFIG['arq_dem'] / CONFIG['arq_agua'].")

    with rasterio.open(cam_dem) as src:
        dem_m = src.read(1).astype(np.float32)
        perfil = src.profile
        nodata_ent = src.nodata
        res = src.res
        transform_dem = src.transform

    with rasterio.open(cam_agua) as src:
        agua = src.read(1)
        if src.shape != dem_m.shape:
            sys.exit(f"ERRO: grades incompativeis. DEM {dem_m.shape} x agua {src.shape}")
        agua = agua.astype(bool)

    log("0", f"DEM lido        : {dem_m.shape[0]} x {dem_m.shape[1]} px "
             f"({dem_m.size / 1e6:.1f} Mpx) | res {res[0]:.1f} m")
    log("0", f"Arquivo original: {tamanho_mb(cam_dem):.1f} MB em disco | "
             f"{memoria_mb(dem_m):.1f} MB em RAM (float32)")
    log("0", f"Nodata entrada  : {nodata_ent}")
    log("0", f"Pixels de agua  : {agua.sum() / 1e6:.2f} Mpx "
             f"({100 * agua.mean():.1f} %)")

    # Mascara de validade — nodata NUNCA pode ser tratado como terreno
    if nodata_ent is None:
        valido = np.isfinite(dem_m)
        log("0", "AVISO: nodata nao declarado no arquivo. Usando apenas isfinite().")
    else:
        valido = np.isfinite(dem_m) & (dem_m != nodata_ent)

    n_invalido = (~valido).sum()
    log("0", f"Pixels invalidos: {n_invalido / 1e6:.2f} Mpx "
             f"({100 * n_invalido / dem_m.size:.1f} %) — excluidos de todo calculo")

    cam_margem = dir_dados / CONFIG["arq_margem"]
    if cam_margem.exists():
        with rasterio.open(cam_margem) as src:
            margem = src.read(1).astype(bool)
        if margem.shape != dem_m.shape:
            sys.exit(f"ERRO: grades incompativeis. DEM {dem_m.shape} x margem {margem.shape}")
        log("0", f"Pixels de margem: {margem.sum() / 1e6:.2f} Mpx "
                 f"({100 * margem.mean():.1f} %) — fica terra na area, conduz conexao")
    else:
        margem = None
        log("0", "AVISO: caravelas_mascara_margem_*.tif ausente — rode "
                 "01_mapa_elevacao.py (v1.4b) de novo para habilitar a margem "
                 "d'agua real como caminho hidraulico.")

    cobertura = carregar_cobertura_local(dem_m.shape, transform_dem)

    return dem_m, agua, valido, perfil, res, cobertura, margem


# =============================================================================
# ETAPA 1 — recorte
# =============================================================================

def etapa_1_recortar(dem_m, agua, valido, perfil, res, cobertura=None, margem=None):
    area_px_km2 = (res[0] * res[1]) / 1e6

    if CONFIG["bbox_manual"] is not None:
        xmin, ymin, xmax, ymax = CONFIG["bbox_manual"]
        inv = ~perfil["transform"]
        col_min, lin_max = inv * (xmin, ymin)
        col_max, lin_min = inv * (xmax, ymax)
        l0, l1 = int(np.floor(lin_min)), int(np.ceil(lin_max))
        c0, c1 = int(np.floor(col_min)), int(np.ceil(col_max))
        log("1", "Recorte MANUAL (CONFIG['bbox_manual'])")
    else:
        log("1", f"Derivando recorte: terreno < {CONFIG['bbox_elev_max_m']:.0f} m "
                 f"conectado ao oceano...")
        t0 = time.time()
        alvo = inundacao_conectada(
            dem_m, agua, valido, np.float32(CONFIG["bbox_elev_max_m"]),
            semear_bordas=CONFIG["semear_bordas"],
        )
        log("1", f"  flood-fill de delimitacao em {time.time() - t0:.1f} s | "
                 f"{alvo.sum() / 1e6:.2f} Mpx alvo")

        linhas = np.where(alvo.any(axis=1))[0]
        colunas = np.where(alvo.any(axis=0))[0]
        if linhas.size == 0:
            sys.exit("ERRO: nenhum pixel conectado ao oceano. Verifique a mascara d'agua.")

        buf = int(np.ceil(CONFIG["bbox_buffer_km"] * 1000 / res[0]))
        l0 = max(0, linhas[0] - buf)
        l1 = min(dem_m.shape[0], linhas[-1] + 1 + buf)
        c0 = max(0, colunas[0] - buf)
        c1 = min(dem_m.shape[1], colunas[-1] + 1 + buf)
        log("1", f"  buffer aplicado : {CONFIG['bbox_buffer_km']:.1f} km ({buf} px)")

    l0, c0 = max(0, l0), max(0, c0)
    l1, c1 = min(dem_m.shape[0], l1), min(dem_m.shape[1], c1)

    janela = Window(c0, l0, c1 - c0, l1 - l0)
    transform_novo = rasterio.windows.transform(janela, perfil["transform"])

    dem_r = dem_m[l0:l1, c0:c1].copy()
    agua_r = agua[l0:l1, c0:c1].copy()
    valido_r = valido[l0:l1, c0:c1].copy()
    cobertura_r = cobertura[l0:l1, c0:c1].copy() if cobertura is not None else None
    margem_r = margem[l0:l1, c0:c1].copy() if margem is not None else None

    largura_km = (c1 - c0) * res[0] / 1000
    altura_km = (l1 - l0) * res[1] / 1000
    reducao = dem_m.size / dem_r.size

    log("1", f"Janela          : linhas {l0}:{l1} | colunas {c0}:{c1}")
    log("1", f"Recorte         : {dem_r.shape[0]} x {dem_r.shape[1]} px "
             f"({dem_r.size / 1e6:.2f} Mpx) = {largura_km:.0f} x {altura_km:.0f} km")
    log("1", f"Reducao         : {reducao:.1f}x menos pixels | "
             f"{memoria_mb(dem_r):.1f} MB em RAM (float32)")

    if reducao < 1.5:
        log("1", "AVISO: recorte pouco efetivo. Considere bbox_manual ou "
                 "reduzir bbox_elev_max_m.")

    # --- Validacao hipsometrica: o recorte perdeu terreno baixo? -------------
    def area_abaixo(dem, val, cota):
        return float((val & (dem <= cota)).sum() * area_px_km2)

    ref_completo = area_abaixo(dem_m, valido, 2.0)
    ref_recorte = area_abaixo(dem_r, valido_r, 2.0)
    dif = abs(ref_recorte - ref_completo) / max(ref_completo, 1e-9)

    log("1", f"Area < +2 m     : {ref_completo:.1f} km2 (completo) x "
             f"{ref_recorte:.1f} km2 (recorte) | dif {100 * dif:.2f} %")
    if dif > CONFIG["tolerancia_validacao"]:
        log("1", "AVISO: o recorte cortou terreno baixo relevante. "
                 "Aumente bbox_buffer_km ou bbox_elev_max_m.")
    else:
        log("1", "OK: recorte preserva a hipsometria de interesse.")

    diag = {
        "area_abaixo_2m_completo_km2": round(ref_completo, 2),
        "area_abaixo_2m_recorte_km2": round(ref_recorte, 2),
        "diferenca_relativa": round(dif, 5),
        "reducao_pixels": round(reducao, 2),
        "dimensoes_km": [round(largura_km, 1), round(altura_km, 1)],
    }
    return dem_r, agua_r, valido_r, cobertura_r, margem_r, transform_novo, area_px_km2, diag


# =============================================================================
# ETAPA 1b — mascara de caminho hidraulico (canais MapBiomas)
# =============================================================================

def etapa_1b_canal(dem_r, agua_r, valido_r, cobertura_r):
    """
    Mesma lógica de `src.slr_core.mascara_caminho`: canal (classe MapBiomas
    em `classes_caminho`) fora da máscara de água, com cota FABDEM finita e
    <= `caminho_cota_max_m`. Conduz água (entra em `candidato` no flood-fill),
    nunca é fonte.

    Só o canal MapBiomas — a margem d'água real (v1.4b) é lida à parte em
    `etapa_0_ler`/`etapa_1_recortar` e combinada com este resultado em `main()`.

    Devolve None se a cobertura não estiver disponível — o resto do script
    segue gerando o raster de limiar "com canais" igual ao "sem canais"
    (só a margem, sem o canal MapBiomas).
    """
    if cobertura_r is None:
        log("1b", "cobertura ausente — nenhum canal MapBiomas gerado")
        return None

    classes = CONFIG["classes_caminho"]
    cota_max = np.float32(CONFIG["caminho_cota_max_m"])
    caminho = (np.isin(cobertura_r, classes) & ~agua_r & valido_r & (dem_r <= cota_max))

    log("1b", f"caminho (canais MapBiomas {classes}, cota <= {cota_max:.1f} m): "
             f"{caminho.sum() / 1e6:.3f} Mpx")
    return caminho


# =============================================================================
# ETAPA 2 e 3 — clamp e conversao para int16
# =============================================================================

def etapa_2_3_clamp_int16(dem_r, valido_r):
    teto = np.float32(CONFIG["clamp_m"])
    n_clampados = int((valido_r & (dem_r > teto)).sum())

    dem_c = np.where(dem_r > teto, teto, dem_r)
    log("2", f"Clamp em +{teto:.0f} m: {n_clampados / 1e6:.2f} Mpx achatados "
             f"({100 * n_clampados / dem_r.size:.1f} % do recorte)")
    log("2", "      terreno alto so atua como barreira no flood-fill — "
             "achatar nao altera resultado abaixo do teto")

    dem_cm = np.round(dem_c * CONFIG["fator_escala"]).astype(np.int16)
    dem_cm[~valido_r] = CONFIG["nodata_saida"]

    erro_max = float(np.abs(
        dem_cm[valido_r].astype(np.float32) / CONFIG["fator_escala"] - dem_c[valido_r]
    ).max()) if valido_r.any() else 0.0

    log("3", f"float32 -> int16 (cm) | RAM {memoria_mb(dem_r):.1f} -> "
             f"{memoria_mb(dem_cm):.1f} MB")
    log("3", f"      erro maximo de quantizacao: {erro_max * 100:.2f} cm "
             f"(incerteza do FABDEM e' da ordem de 100 cm)")
    log("3", f"      nodata codificado como {CONFIG['nodata_saida']}")

    return dem_cm


# =============================================================================
# ETAPA 4 — escrita comprimida
# =============================================================================

def etapa_4_escrever(caminho, dados, perfil_base, transform, dtype, nodata, rotulo):
    p = perfil_saida(perfil_base, dtype, nodata,
                     dados.shape[0], dados.shape[1], transform)
    with rasterio.open(caminho, "w", **p) as dst:
        dst.write(dados, 1)

    mb = tamanho_mb(caminho)
    bruto = dados.nbytes / (1024 ** 2)
    log("4", f"{rotulo:<22}: {mb:6.2f} MB em disco "
             f"(bruto {bruto:6.2f} MB | razao {bruto / max(mb, 1e-9):.1f}x)")
    return mb


# =============================================================================
# ETAPA 5 — raster de limiar de conexao
# =============================================================================

def etapa_5_limiar(dem_cm, agua_r, valido_r, caminho_r=None, rotulo="sem canais MapBiomas"):
    """
    Para cada pixel, o menor nivel de mar (cm) em que ele passa a estar
    inundado E conectado ao oceano.

    Explora a monotonicidade da inundacao conectada: se um pixel conecta
    no nivel h, conecta em qualquer nivel maior. Logo o limiar existe e e'
    unico, e um so raster substitui todas as mascaras pre-computadas.

    `caminho_r`: mascara de caminho hidraulico (margem d'agua real, canal
    MapBiomas, ou a uniao dos dois — ver `inundacao_conectada`). `rotulo` e'
    so para o print — ver os dois usos em `main()` (raster sem/com canal
    MapBiomas; a margem d'agua real pode estar presente nos dois).
    """
    fino = CONFIG["limiar_passo_fino_cm"]
    grosso = CONFIG["limiar_passo_grosso_cm"]
    troca = int(CONFIG["limiar_troca_passo_m"] * 100)
    topo = int(CONFIG["limiar_nivel_max_m"] * 100)

    niveis = list(range(0, troca + 1, fino)) + list(range(troca + grosso, topo + 1, grosso))

    log("5", f"Pre-computando {len(niveis)} niveis ({rotulo}): "
             f"0–{troca / 100:.1f} m passo {fino} cm | "
             f"{troca / 100:.1f}–{topo / 100:.0f} m passo {grosso} cm")

    limiar = np.full(dem_cm.shape, CONFIG["nunca_alaga"], dtype=np.int16)
    t0 = time.time()

    for i, nivel in enumerate(niveis, 1):
        conectado = inundacao_conectada(dem_cm, agua_r, valido_r, nivel,
                                        semear_bordas=CONFIG["semear_bordas"],
                                        caminho=caminho_r)
        novos = conectado & (limiar == CONFIG["nunca_alaga"])
        limiar[novos] = nivel

        if i % 20 == 0 or i == len(niveis):
            frac = 100 * (limiar != CONFIG["nunca_alaga"]).mean()
            log("5", f"  ({rotulo}) {i:3d}/{len(niveis)} | nivel +{nivel / 100:5.2f} m | "
                     f"{frac:5.1f} % do recorte ja atribuido | "
                     f"{time.time() - t0:5.1f} s")

    limiar[~valido_r] = CONFIG["nodata_saida"]
    log("5", f"Concluido ({rotulo}) em {time.time() - t0:.1f} s")
    log("5", "      consulta no app: inundado = (limiar <= nivel_cm)")
    return limiar, niveis


# =============================================================================
# ETAPA 6 — tabela de conferencia 30 m local x 30 m web
# =============================================================================

def etapa_6_conferir(dem_cm, limiar, valido_r, area_px_km2, limiar_canais=None):
    """
    ATENÇÃO: "conectado" (e "conectado com canais") tem que cruzar o limiar
    com `abaixo` (dem_cm <= cm), exatamente como `fonte.mascara_inundacao_auto`
    faz no app (`inundada = abaixo & conectada`). Sem esse cruzamento, canais
    (que entram no `candidato` do flood-fill independente do nível, e por
    isso podem ganhar `limiar` bem abaixo da própria cota do pixel) contariam
    como "inundados" mesmo com cota real acima do nível testado — o canal é
    caminho, não deveria aparecer como se ele mesmo tivesse alagado cedo.
    """
    cotas = [0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0]
    linhas = []

    print()
    if limiar_canais is not None:
        print("  Nivel (m) | Bathtub (km2) | Conectado (km2) | Razao | "
              "Com canais (km2) | Razao canais")
        print("  " + "-" * 92)
    else:
        print("  Nivel (m) | Bathtub (km2) | Conectado (km2) | Razao")
        print("  " + "-" * 52)

    for cota in cotas:
        cm = int(round(cota * 100))
        abaixo = valido_r & (dem_cm <= cm)
        bathtub = float(abaixo.sum() * area_px_km2)
        conectado = float((abaixo & (limiar <= cm)).sum() * area_px_km2)
        razao = conectado / bathtub if bathtub > 0 else 0.0
        linha = {
            "nivel_m": cota,
            "bathtub_km2": round(bathtub, 2),
            "conectado_km2": round(conectado, 2),
        }
        texto = f"  {cota:9.2f} | {bathtub:13.2f} | {conectado:15.2f} | {razao:5.2f}"

        if limiar_canais is not None:
            conectado_c = float((abaixo & (limiar_canais <= cm)).sum() * area_px_km2)
            razao_c = conectado_c / bathtub if bathtub > 0 else 0.0
            linha["conectado_canais_km2"] = round(conectado_c, 2)
            texto += f" | {conectado_c:16.2f} | {razao_c:12.2f}"

        print(texto)
        linhas.append(linha)
    print()

    return linhas


# =============================================================================
# PRINCIPAL
# =============================================================================

def main():
    print("=" * 70)
    print(" 03_prepara_dem_web.py — Projeto 26.09 (NMRM Caravelas)")
    print(" Versao leve para deploy — resolucao original de 30 m preservada")
    print("=" * 70)

    dir_dados = resolver_dir_dados()
    dir_saida = Path(__file__).parent / CONFIG["dir_saida"]
    dir_saida.mkdir(exist_ok=True)
    log("0", f"Dados de entrada: {dir_dados}")
    log("0", f"Saida           : {dir_saida}")
    print()

    # --- 0 ---
    dem_m, agua, valido, perfil, res, cobertura, margem = etapa_0_ler(dir_dados)
    print()

    # --- 1 ---
    dem_r, agua_r, valido_r, cobertura_r, margem_r, transform, area_px_km2, diag = etapa_1_recortar(
        dem_m, agua, valido, perfil, res, cobertura, margem
    )
    _ref_antigo = CONFIG["ref_area_abaixo_2m_km2"]
    _ref_novo = diag["area_abaixo_2m_completo_km2"]
    log("1", f"Referencia 'area abaixo de 2 m' (extensao completa, modo local): "
             f"antiga(config)={_ref_antigo:.1f} km2 | nova={_ref_novo:.1f} km2 "
             f"(diferenca da Parte 1/1.4b — mascara de agua na grade nativa "
             f"+ agua_area por Resampling.average)")
    del dem_m, agua, valido, cobertura, margem  # libera a extensao completa
    print()

    # --- 1b ---
    # v1.4b: dois "caminhos" independentes, somados por união.
    #   caminho_base       : só a margem d'água real — sempre ativa, não
    #                        depende do MapBiomas nem de nenhum toggle.
    #   caminho_com_canais : caminho_base UNIÃO canal MapBiomas (classe 33,
    #                        com a salvaguarda de cota) — só se a cobertura
    #                        estiver disponível.
    canal_r = etapa_1b_canal(dem_r, agua_r, valido_r, cobertura_r)
    if margem_r is not None:
        log("1b", f"margem d'agua real (v1.4b, sempre ativa): "
                 f"{margem_r.sum() / 1e6:.3f} Mpx")
    else:
        log("1b", "margem d'agua ausente — rode 01_mapa_elevacao.py (v1.4b) de novo")
    caminho_base = margem_r
    print()

    # --- 2 e 3 ---
    dem_cm = etapa_2_3_clamp_int16(dem_r, valido_r)
    del dem_r
    print()

    # --- 4 (DEM e mascara) ---
    cam_dem = dir_saida / "dem_30m_web.tif"
    cam_agua = dir_saida / "mascara_agua_web.tif"

    mb_dem = etapa_4_escrever(cam_dem, dem_cm, perfil, transform,
                              "int16", CONFIG["nodata_saida"], "DEM 30 m (int16 cm)")
    mb_agua = etapa_4_escrever(cam_agua, agua_r.astype(np.uint8), perfil, transform,
                               "uint8", 255, "Mascara d'agua")
    verificar_alinhamento_cobertura_web(dir_saida, transform)
    print()

    # --- 5 (sem canais MapBiomas — inclui a margem d'água real, se houver) ---
    limiar, niveis = etapa_5_limiar(dem_cm, agua_r, valido_r, caminho_r=caminho_base,
                                    rotulo="sem canal MapBiomas")
    print()

    cam_limiar = dir_saida / "limiar_conexao_web.tif"
    mb_limiar = etapa_4_escrever(cam_limiar, limiar, perfil, transform,
                                 "int16", CONFIG["nodata_saida"], "Limiar de conexao")
    print()

    # --- 5 (com canais MapBiomas — margem UNIÃO canal, só se cobertura existir) ---
    limiar_canais = None
    mb_limiar_canais = 0.0
    if canal_r is not None:
        caminho_com_canais = canal_r if caminho_base is None else (caminho_base | canal_r)
        limiar_canais, _ = etapa_5_limiar(dem_cm, agua_r, valido_r, caminho_r=caminho_com_canais,
                                         rotulo="com canal MapBiomas")
        print()
        cam_limiar_canais = dir_saida / "limiar_conexao_canais_web.tif"
        mb_limiar_canais = etapa_4_escrever(
            cam_limiar_canais, limiar_canais, perfil, transform,
            "int16", CONFIG["nodata_saida"], "Limiar c/ canais")
        print()
    else:
        log("5", "raster COM canais não gerado (cobertura ausente).")
        print()

    # --- 6 ---
    tabela = etapa_6_conferir(dem_cm, limiar, valido_r, area_px_km2,
                              limiar_canais=limiar_canais)

    # --- Metadados ---
    total_mb = mb_dem + mb_agua + mb_limiar + mb_limiar_canais
    meta = {
        "projeto": "26.09 — Simulador NMRM Caravelas",
        "gerado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
        "resolucao_m": [float(res[0]), float(res[1])],
        "crs": str(perfil["crs"]),
        "shape": [int(dem_cm.shape[0]), int(dem_cm.shape[1])],
        "transform": list(transform)[:6],
        "config": {k: v for k, v in CONFIG.items() if not k.startswith("arq_")},
        "diagnostico_recorte": diag,
        "referencia_area_abaixo_2m": {
            "v1_3_km2": _ref_antigo,
            "v1_4b_km2": _ref_novo,
            "motivo": "mascara de agua passou a ser detectada na grade nativa, "
                      "com agua_area por Resampling.average (limiar 0.5) — "
                      "Partes 1 e 1.4b da v1.4",
        },
        "niveis_pre_computados_cm": [int(n) for n in niveis],
        "margem_agua": {
            "disponivel": margem_r is not None,
            "conceito": "agua_conexao (Resampling.max) & ~agua_area "
                        "(Resampling.average >= 0.5): fica terra na area "
                        "(cota real preservada), mas conduz conexao — "
                        "sempre ativa, sem salvaguarda de cota (agua real).",
        },
        "canais": {
            "disponivel": canal_r is not None,
            "classes_caminho": CONFIG["classes_caminho"],
            "caminho_cota_max_m": CONFIG["caminho_cota_max_m"],
            "conceito": "canal MapBiomas = caminho (conduz), nunca fonte "
                        "(nao injeta agua sozinho); so conta ate a cota de "
                        "salvaguarda, para nao religar depressoes distantes "
                        "atraves de lago/rio alto no tabuleiro Barreiras. "
                        "Soma-se a margem_agua por uniao no raster 'com canais'.",
        },
        "tabela_conferencia": tabela,
        "tamanho_total_mb": round(total_mb, 2),
        "observacoes": [
            f"Elevacao em centimetros (int16). Dividir por {CONFIG['fator_escala']:.0f} para metros.",
            f"Terreno acima de +{CONFIG['clamp_m']:.0f} m foi achatado (TETO). "
            f"Cenarios acima desse valor nao sao validos.",
            f"limiar == {CONFIG['nunca_alaga']} indica pixel que nunca conecta ao oceano "
            f"ate +{CONFIG['limiar_nivel_max_m']:.0f} m.",
            "limiar_conexao_web.tif = margem d'agua real (se disponivel), sem canal "
            "MapBiomas. limiar_conexao_canais_web.tif (se presente) = o mesmo, "
            "UNIAO com canal MapBiomas classe 33 como caminho hidraulico.",
            "Dado derivado do FABDEM V1-2 (Hawker et al. 2022) — CC BY-NC-SA 4.0. "
            "O derivado herda a mesma licenca e a restricao de uso nao comercial.",
        ],
    }
    with open(dir_saida / "metadados_web.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    # --- Licenca dos dados ---
    with open(dir_saida / "LICENSE.txt", "w", encoding="utf-8") as f:
        f.write(
            "DADOS DERIVADOS — Projeto 26.09 (NMRM Caravelas)\n"
            "=================================================\n\n"
            "Fonte: FABDEM V1-2 (Forest And Buildings removed Copernicus DEM)\n"
            "Hawker, L., Uhe, P., Paulo, L., Sosa, J., Savage, J., Sampson, C.,\n"
            "Neal, J. (2022). A 30 m global map of elevation with forests and\n"
            "buildings removed. Environmental Research Letters, 17(2), 024016.\n\n"
            "Licenca: Creative Commons Attribution-NonCommercial-ShareAlike 4.0\n"
            "         (CC BY-NC-SA 4.0)\n"
            "         https://creativecommons.org/licenses/by-nc-sa/4.0/\n\n"
            "Os rasters neste diretorio sao produtos derivados do FABDEM V1-2\n"
            "(recorte, reamostragem de tipo de dado e processamento de\n"
            "conectividade hidraulica). Herdam a mesma licenca: uso nao\n"
            "comercial, atribuicao obrigatoria e compartilhamento pela mesma\n"
            "licenca.\n\n"
            "A licenca do CODIGO deste repositorio e' declarada separadamente\n"
            "no LICENSE da raiz.\n"
        )

    print("=" * 70)
    print(f" CONCLUIDO — {total_mb:.2f} MB em {dir_saida}")
    print("=" * 70)
    linhas_resumo = [("dem_30m_web.tif", mb_dem),
                     ("mascara_agua_web.tif", mb_agua),
                     ("limiar_conexao_web.tif", mb_limiar)]
    if limiar_canais is not None:
        linhas_resumo.append(("limiar_conexao_canais_web.tif", mb_limiar_canais))
    for nome, mb in linhas_resumo:
        print(f"   {nome:<30} {mb:6.2f} MB")
    print(f"   {'metadados_web.json':<30}   ~0 MB")
    print(f"   {'LICENSE.txt':<30}   ~0 MB")
    print()

    if total_mb > 50:
        print(" AVISO: acima de 50 MB. O GitHub aceita ate 100 MB por arquivo,")
        print("        mas reclama acima de 50. Considere reduzir bbox_buffer_km,")
        print("        baixar clamp_m ou anexar os rasters a um GitHub Release.")
    else:
        print(" Tamanho confortavel para versionar diretamente no repositorio.")
    print()
    print(" Proximo passo: adaptar 02_simulador_nmrm.py para modo duplo")
    print("   local -> NMRM_DIR_DADOS (30 m completo, flood-fill em tempo real)")
    print("   web   -> dados_web/     (30 m recortado, limiar pre-computado)")
    print()


if __name__ == "__main__":
    main()
