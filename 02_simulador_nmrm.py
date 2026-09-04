"""
02_simulador_nmrm.py — Simulador interativo de exposição ao NMRM
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB — Caravelas (BA)

Interface Streamlit sobre o motor `slr_core.py`.
Toda a ciência está no motor; este arquivo só desenha controles.

COMO RODAR (local):
    pip install "streamlit>=1.49" rasterio scipy matplotlib pandas
    streamlit run 02_simulador_nmrm.py

Pré-requisito: ter rodado 01_mapa_elevacao.py.

COMO RODAR (Google Colab):
    !pip install -q "streamlit>=1.49" rasterio scipy
    !npm install -g localtunnel
    !streamlit run 02_simulador_nmrm.py &>/dev/null &
    !npx localtunnel --port 8501
  (se preferir, peço a versão ipywidgets, que roda nativo no Colab)

Autor: Helio | Assistência: Claude
"""

import io
import os
import time

import folium
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import config
import src.fonte_dados as fonte
import src.mapa_web as mapaweb
import src.slr_core as core

# Resolve a fonte de dados UMA vez: modo local (dados completos em
# NMRM_DIR_DADOS, flood-fill em tempo real) ou modo web (dados_web/
# versionado, limiar de conexão pré-computado). Todo o resto do arquivo
# consome FONTE, nunca config.MDE_PROCESSADO diretamente.
FONTE = fonte.resolver_fonte()
MODO_WEB = FONTE["modo"] == fonte.MODO_WEB

# =============================================================================
# PARÂMETROS DA INTERFACE
# =============================================================================

CONFIG_UI = {
    "caminho_padrao":  FONTE["dem"],  # local: produto do 01 | web: dados_web/dem_30m_web.tif
    "nmrm_min":        0.0,
    "nmrm_max":        3.0,       # teto dos modos guiados e da curva de exposição
    # v1.2 — o modo Manual passa a ir além dos cenários AR6. Serve para teste
    # de sensibilidade do terreno e para comparar com os paleoníveis
    # holocênicos da própria planície (Andrade et al. 2003: +4,8 / +3,5 / +2,5 m).
    # O teto real é recalculado adiante contra o raster de limiar e o clamp
    # do MDE leve — este valor é só o desejado.
    "nmrm_max_manual": 10.0,
    "nmrm_aviso_extrapolacao": 3.0,   # acima disto a interface avisa que saiu da faixa AR6
    "fracao_segura_clamp": 0.75,      # não chegar perto do teto artificial do MDE web
    "nmrm_passo":      0.05,
    "curva_passo":     0.10,      # passo fino da curva, até nmrm_max
    "curva_passo_extra": 0.25,    # passo grosso acima de nmrm_max (casa com o limiar web)
    "figsize":         (10, 8),
}

st.set_page_config(page_title="Simulador NMRM — Caravelas (BA)",
                   layout="wide", initial_sidebar_state="expanded")


# =============================================================================
# CARREGAMENTO COM CACHE
# =============================================================================

@st.cache_resource(show_spinner="Lendo o MDE FABDEM...")
def _carregar(caminho: str):
    # carregar_dem_auto cobre os dois formatos: float32 (m) no modo local e
    # int16 (cm) no modo web. Devolve o MESMO dicionário de core.carregar_dem.
    return fonte.carregar_dem_auto(caminho)


@st.cache_resource(show_spinner="Lendo a máscara de água...")
def _carregar_mascara_agua(caminho: str):
    return core.carregar_mascara_agua(caminho)


@st.cache_resource(show_spinner="Lendo o raster de limiar de conexão...")
def _carregar_limiar(caminho: str):
    # Só existe no modo web. No modo local `caminho` é "" e retorna None,
    # fazendo mascara_inundacao_auto cair no flood-fill em tempo real.
    return fonte.carregar_limiar(caminho or None)


@st.cache_resource(show_spinner="Calculando sombreamento...")
def _hillshade(caminho: str, exagero: int):
    d = _carregar(caminho)
    return core.hillshade(d["dem"], d["res_x"], exagero=exagero)


@st.cache_data(show_spinner="Gerando overlay do mapa interativo...")
def _overlay_web(caminho: str, caminho_mascara_agua: str, caminho_limiar: str,
                 cota_m: float, conectividade: bool, semear_bordas: bool,
                 area_min: float, cores: dict):
    """
    Recalcula a máscara de inundação (barato — ndimage.label numa grade de
    ~5M px no modo local, ou consulta O(n) ao raster de limiar no modo web)
    e reprojeta+codifica o PNG (caro — é isso que o cache evita a cada
    movimento de slider que NÃO muda cota/conectividade/área mínima).
    """
    d = _carregar(caminho)
    ma = (_carregar_mascara_agua(caminho_mascara_agua)
          if os.path.exists(caminho_mascara_agua) else None)
    lm = _carregar_limiar(caminho_limiar) if caminho_limiar else None
    m = fonte.mascara_inundacao_auto(
        core, d, cota_m,
        conectividade=conectividade, semear_bordas=semear_bordas,
        area_minima_ha=area_min, mascara_agua=ma, limiar=lm)
    classes = mapaweb.classificar_overlay(m, ma if ma is not None else d["mask_oceano"])
    return mapaweb.gerar_overlay_web(classes, d["transform"], d["crs"], cores)


# -----------------------------------------------------------------------------
# core.curva_exposicao e core.tabela_cenarios chamam core.mascara_inundacao
# internamente e não conhecem o raster de limiar do modo web. Os dois loops
# abaixo os reimplementam usando fonte.mascara_inundacao_auto, mantendo
# EXATAMENTE as colunas dos DataFrames originais (a interface e os
# download_button dependem delas). src/slr_core.py fica intocado.
# -----------------------------------------------------------------------------

def _mascara_auto(d, ma, lm, cota_m, conectividade, semear_bordas):
    return fonte.mascara_inundacao_auto(
        core, d, cota_m, conectividade=conectividade,
        semear_bordas=semear_bordas, mascara_agua=ma, limiar=lm)


@st.cache_data(show_spinner="Rodando a curva de exposição...")
def _curva(caminho: str, caminho_mascara_agua: str, caminho_limiar: str,
           mare_m: float, conectividade: bool, semear_bordas: bool, passo: float,
           topo: float = None):
    d = _carregar(caminho)
    ma = (_carregar_mascara_agua(caminho_mascara_agua)
          if os.path.exists(caminho_mascara_agua) else None)
    lm = _carregar_limiar(caminho_limiar) if caminho_limiar else None

    cotas = np.arange(CONFIG_UI["nmrm_min"], CONFIG_UI["nmrm_max"] + 1e-9, passo)

    # v1.2 — se o modo Manual pediu um NMRM acima do teto normal da curva,
    # estende o eixo até lá com passo GROSSO. Motivo: no modo local cada ponto
    # é um flood-fill inteiro, então não dá para manter 10 cm até 10 m; e no
    # modo web 0,25 m é exatamente o passo do raster de limiar acima de 5,5 m,
    # ou seja, passo mais fino ali não traria informação nova.
    if topo and topo > CONFIG_UI["nmrm_max"]:
        extra = np.arange(CONFIG_UI["nmrm_max"] + CONFIG_UI["curva_passo_extra"],
                          topo + 1e-9, CONFIG_UI["curva_passo_extra"])
        cotas = np.concatenate([cotas, extra])
    reg = []
    for nmrm in cotas:
        c = core.cota_limiar(float(nmrm), mare_m=mare_m)
        m = _mascara_auto(d, ma, lm, c["cota_m"], conectividade, semear_bordas)
        e = core.estatisticas_area(m, d["dem"], d["area_pixel_m2"])
        reg.append({"NMRM (m)": round(float(nmrm), 2),
                    "Cota (m)": round(c["cota_m"], 2),
                    "Área inundada (km²)": e["area_inundada_km2"],
                    "% da área emersa": e["pct_inundada"]})
    return pd.DataFrame(reg)


@st.cache_data(show_spinner="Rodando a matriz de cenários...")
def _tabela(caminho: str, caminho_mascara_agua: str, caminho_limiar: str,
            mare_m: float, conectividade: bool, semear_bordas: bool):
    d = _carregar(caminho)
    ma = (_carregar_mascara_agua(caminho_mascara_agua)
          if os.path.exists(caminho_mascara_agua) else None)
    lm = _carregar_limiar(caminho_limiar) if caminho_limiar else None

    horizontes = (2050, 2100)
    percentis = ("mediana", "p83")
    linhas = []
    for nome in core.CENARIOS_AR6:
        for ano in horizontes:
            for p in percentis:
                nmrm = core.CENARIOS_AR6[nome][ano][p]
                c = core.cota_limiar(nmrm, mare_m=mare_m)
                m = _mascara_auto(d, ma, lm, c["cota_m"], conectividade, semear_bordas)
                e = core.estatisticas_area(m, d["dem"], d["area_pixel_m2"])
                linhas.append({
                    "Cenário": nome, "Horizonte": str(ano), "Percentil": p,
                    "NMRM (m)": nmrm, "Cota total (m)": round(c["cota_m"], 2),
                    "Área inundada (km²)": round(e["area_inundada_km2"], 2),
                    "% da área emersa": round(e["pct_inundada"], 2),
                    "Depressões isoladas (km²)": round(e["area_isolada_km2"], 2),
                })
    for nivel in core.NIVEIS_TURMA:
        c = core.cota_limiar(nivel, mare_m=mare_m)
        m = _mascara_auto(d, ma, lm, c["cota_m"], conectividade, semear_bordas)
        e = core.estatisticas_area(m, d["dem"], d["area_pixel_m2"])
        linhas.append({
            "Cenário": "Sensibilidade (turma)", "Horizonte": "—", "Percentil": "—",
            "NMRM (m)": nivel, "Cota total (m)": round(c["cota_m"], 2),
            "Área inundada (km²)": round(e["area_inundada_km2"], 2),
            "% da área emersa": round(e["pct_inundada"], 2),
            "Depressões isoladas (km²)": round(e["area_isolada_km2"], 2),
        })
    return pd.DataFrame(linhas)


# =============================================================================
# BARRA LATERAL — PARÂMETROS
# =============================================================================

st.sidebar.title("Parâmetros")

if FONTE.get("forcado"):
    # Sem esta tarja é fácil olhar a tela, ver os controles bloqueados e achar
    # que o modo local quebrou. Aqui o bloqueio é o objetivo.
    st.sidebar.warning(
        "**Pré-visualização do modo público.** `NMRM_MODO=web` está ligado: "
        "rodando com os dados leves de `dados_web/` e com os controles da "
        "ferramenta pública. Limpe a variável de ambiente para voltar ao "
        "modo local.", icon="👁️")

# v1.2 — o campo de caminho só faz sentido no modo local, onde o usuário é
# quem gerou o MDE com o 01_mapa_elevacao.py. No modo web o raster é o
# dados_web/ versionado junto com o app: expor o caminho só cria um controle
# que não leva a lugar nenhum e um jeito fácil de quebrar a página.
if MODO_WEB:
    caminho = CONFIG_UI["caminho_padrao"]
else:
    caminho = st.sidebar.text_input(
        "MDE (GeoTIFF do script 01)",
        value=CONFIG_UI["caminho_padrao"],
        help="Saída do 01_mapa_elevacao.py: FABDEM recortado, EPSG:31984, 30 m.",
    )

if not os.path.exists(caminho):
    st.error(f"MDE não encontrado em `{caminho}`. "
             "Rode o `01_mapa_elevacao.py` ou corrija o caminho na barra lateral.")
    st.stop()

dados = _carregar(caminho)

caminho_mascara_agua = FONTE["agua"] or ""
if caminho_mascara_agua and os.path.exists(caminho_mascara_agua):
    mascara_agua = _carregar_mascara_agua(caminho_mascara_agua)
else:
    mascara_agua = None
    st.sidebar.warning(
        "Máscara de água não encontrada. "
        "Caindo para o método antigo de conectividade, que **subestima** a área "
        "conectada ao mar (o oceano já virou nodata no MDE processado). "
        "Rode `01_mapa_elevacao.py` novamente para gerar a máscara.",
        icon="⚠️")

caminho_limiar = FONTE["limiar"] or ""
limiar = _carregar_limiar(caminho_limiar) if caminho_limiar else None

# O raster de limiar (modo web) só é confiável até um teto de cota. Não deixa
# o slider de NMRM passar disso — além da grade o resultado congelaria em
# silêncio (a consulta é `limiar <= cota_cm`).
_teto_limiar = fonte.cota_maxima_limiar(limiar)
if _teto_limiar:
    CONFIG_UI["nmrm_max"] = min(CONFIG_UI["nmrm_max"], _teto_limiar)

# ---- v1.2: teto do modo Manual ---------------------------------------------
# Duas restrições independentes:
#   (a) raster de limiar — mesma lógica acima;
#   (b) CLAMP do MDE leve — no modo web todo terreno acima de `clamp_m` foi
#       achatado nesse valor. Perto do teto o platô inteiro alaga de uma vez e
#       o número deixa de ter sentido físico, então paramos bem antes dele.
_meta_fonte = FONTE.get("metadados") or {}
_cfg_web = _meta_fonte.get("config", {})
_clamp_web = _cfg_web.get("clamp_m")
_troca_passo_web = _cfg_web.get("limiar_troca_passo_m")
_passo_grosso_web = _cfg_web.get("limiar_passo_grosso_cm")

_teto_manual = CONFIG_UI["nmrm_max_manual"]
if _teto_limiar:
    _teto_manual = min(_teto_manual, _teto_limiar)
if _clamp_web:
    _teto_manual = min(_teto_manual,
                       CONFIG_UI["fracao_segura_clamp"] * float(_clamp_web))
# O max() final garante que o slider nunca receba min > max. Ele TEM
# prioridade sobre a fração de segurança do clamp: se algum dia `nmrm_max`
# passar de 0,75 * clamp_m, o teto do Manual acompanha `nmrm_max`, não o
# clamp. Hoje isso não acontece (clamp 20 m -> 15 m seguros contra 3 m de
# nmrm_max); quem mexer em `clamp_m` precisa reavaliar esta linha.
CONFIG_UI["nmrm_max_manual"] = round(max(_teto_manual, CONFIG_UI["nmrm_max"]), 2)

# Maior valor que o próprio AR6 projeta para 2100 (p83 do cenário de baixa
# confiança). Serve de referência para avisar quando o usuário extrapola.
NMRM_MAX_AR6 = max(c[2100]["p83"] for c in core.CENARIOS_AR6.values())

st.sidebar.divider()

# ---- 1. Cenário -------------------------------------------------------------
st.sidebar.subheader("1 · Cenário de NMRM")

# v1.2 — na ferramenta pública o cenário IPCC AR6 sai do seletor.
# Motivo (regra 1 do projeto): os valores de CENARIOS_AR6 são NMGM, o nível
# médio GLOBAL. A disciplina pede NMRM local de Caravelas, que só sai do
# NASA/IPCC AR6 Sea Level Projection Tool. Enquanto essa substituição não
# acontece, oferecer "Cenário IPCC AR6" ao público é entregar um número
# global rotulado como se fosse local. Os níveis da turma e o modo Manual
# não têm esse problema: são cotas declaradas, não projeções.
# No modo local o seletor segue completo, para o desenvolvimento continuar.
MODOS_CENARIO = ["Cenário IPCC AR6", "Níveis da turma", "Manual"]
_modos_disponiveis = MODOS_CENARIO[1:] if MODO_WEB else MODOS_CENARIO

modo = st.sidebar.radio("Origem do valor", _modos_disponiveis, horizontal=False)

if MODO_WEB:
    st.sidebar.info("Cenários IPCC AR6 em desenvolvimento.", icon="🛠️")

if modo == "Cenário IPCC AR6":
    nome_cen = st.sidebar.selectbox(
        "Cenário SSP", list(core.CENARIOS_AR6.keys()),
        format_func=lambda k: core.CENARIOS_AR6[k]["rotulo"], index=1)
    horizonte = st.sidebar.select_slider("Horizonte", options=[2050, 2100], value=2100)
    percentil = st.sidebar.selectbox(
        "Percentil da projeção", ["p17", "mediana", "p83"], index=1,
        format_func={"p17": "17% (otimista)", "mediana": "Mediana (50%)",
                     "p83": "83% (pessimista)"}.get)
    nmrm = core.CENARIOS_AR6[nome_cen][horizonte][percentil]
    rotulo_cen = f"{nome_cen} · {horizonte} · {percentil}"
    st.sidebar.caption(f"NMGM = **{nmrm:.2f} m** (AR6 WGI, base 1995–2014)")

elif modo == "Níveis da turma":
    nmrm = st.sidebar.select_slider("Nível de sensibilidade (m)",
                                    options=core.NIVEIS_TURMA, value=1.0)
    rotulo_cen = f"Sensibilidade espacial +{nmrm:.1f} m"

else:
    nmrm = st.sidebar.slider(
        "NMRM (m)", CONFIG_UI["nmrm_min"], CONFIG_UI["nmrm_max_manual"],
        1.0, CONFIG_UI["nmrm_passo"],
        help=(f"Modo livre até +{CONFIG_UI['nmrm_max_manual']:.1f} m. "
              f"Acima de +{CONFIG_UI['nmrm_aviso_extrapolacao']:.0f} m a simulação sai "
              "da faixa projetada pelo AR6 e passa a valer como teste de "
              "sensibilidade do terreno ou comparação com paleoníveis."))
    rotulo_cen = f"Manual +{nmrm:.2f} m"

    if nmrm > CONFIG_UI["nmrm_aviso_extrapolacao"]:
        st.sidebar.warning(
            f"**+{nmrm:.2f} m está fora da faixa do AR6.** O valor mais alto "
            f"projetado para 2100 é +{NMRM_MAX_AR6:.2f} m (SSP5-8.5 de baixa "
            "confiança, percentil 83). Acima disso o mapa é um teste de "
            "sensibilidade da planície — não um cenário climático. Para "
            "referência, os paleoníveis holocênicos de Caravelas "
            "(Andrade et al. 2003) chegam a +4,8 m.",
            icon="⚠️")

    if MODO_WEB and _troca_passo_web and _passo_grosso_web and nmrm > _troca_passo_web:
        st.sidebar.caption(
            f"Modo web: acima de +{_troca_passo_web:.1f} m a conectividade foi "
            f"pré-computada de {_passo_grosso_web:.0f} em {_passo_grosso_web:.0f} cm. "
            "Cotas dentro do mesmo degrau devolvem o mesmo mapa.")

# ---- 2. Maré e sobrelevação -------------------------------------------------
st.sidebar.subheader("2 · Empilhamento de maré")

chaves_mare = [k for k in core.NIVEIS_MARE if k != "PROVISORIO"]

if MODO_WEB:
    # v1.2 — ferramenta pública: a maré fica TRAVADA no nível médio.
    # Os demais datums continuam visíveis (o usuário precisa saber que existem
    # e que estão no roadmap), porém desabilitados, até as constantes
    # harmônicas do BNDO/CHM entrarem em NIVEIS_MARE. Regra 1 do projeto:
    # melhor um controle bloqueado que um offset inventado.
    st.sidebar.radio(
        "Datum de referência", chaves_mare,
        index=chaves_mare.index("NM"),
        format_func=lambda k: core.NIVEIS_MARE[k]["rotulo"],
        disabled=True,
        help="A simulação roda no nível médio nesta versão.")
    chave_mare = "NM"
    st.sidebar.info("Demais níveis de maré em desenvolvimento.", icon="🛠️")
else:
    chave_mare = st.sidebar.selectbox(
        "Datum de referência", chaves_mare,
        format_func=lambda k: core.NIVEIS_MARE[k]["rotulo"])
    if core.NIVEIS_MARE["PROVISORIO"]:
        st.sidebar.warning(
            "Datums de maré ainda **provisórios (0,00 m)**. "
            "Preencher `NIVEIS_MARE` em `slr_core.py` com as constantes "
            "harmônicas do BNDO/CHM ou com a estação Caravelas do catálogo FEMAR.",
            icon="⚠️")

mare = core.NIVEIS_MARE[chave_mare]["offset_m"]

sobrelev = st.sidebar.number_input(
    "Sobrelevação meteorológica (m)", 0.0, 2.0, 0.0, 0.05,
    help="Maré meteorológica / storm surge. Deixe 0 para exposição puramente astronômica.")

cota = core.cota_limiar(nmrm, mare_m=mare, sobrelevacao_m=sobrelev)

# ---- 3. Hidrologia ----------------------------------------------------------
st.sidebar.subheader("3 · Regra hidrológica")

conectividade = st.sidebar.toggle(
    "Exigir conexão hidráulica com o mar", value=True,
    help="Desligado = 'bathtub' ingênuo, igual aos simuladores online. "
         "Ligado = só conta água que tem caminho até o oceano.")
semear_bordas = st.sidebar.toggle(
    "Água pode entrar pelas bordas do recorte",
    value=True, disabled=MODO_WEB,
    help=("Fixado na geração dos dados leves — não editável nesta versão."
          if MODO_WEB else "Evita confinamento artificial quando o "
          "recorte corta a planície."))
# "Mancha" = grupo de pixels vizinhos (conectividade 8) que caíram na MESMA
# classe. O filtro roda depois da classificação e vale para as duas classes,
# inundada e depressão isolada. É um filtro de RUÍDO do MDE, não de ciência:
# o FABDEM tem incerteza vertical decimétrica, e numa planície tão plana isso
# gera pixels isolados abaixo da cota que não representam feição real.
_ha_por_pixel = dados["area_pixel_m2"] / 1e4
area_min = st.sidebar.number_input(
    "Área mínima de mancha (ha)", 0.0, 100.0, 0.0, 0.5,
    help=("Descarta cada mancha contígua menor que este valor, nas duas "
          "classes (inundada e depressão isolada). 0 = não descarta nada. "
          f"Nesta grade de {dados['res_x']:.0f} m, 1 pixel = "
          f"{_ha_por_pixel:.2f} ha, então 0,5 ha ≈ "
          f"{int(np.ceil(0.5 / _ha_por_pixel))} pixels."))
if area_min > 0:
    st.sidebar.caption(
        f"Descartando manchas com menos de "
        f"{int(np.ceil(area_min * 1e4 / dados['area_pixel_m2']))} pixels "
        f"({area_min:.1f} ha).")

# ---- 4. Cartografia ---------------------------------------------------------
st.sidebar.subheader("4 · Cartografia")
# v1.2 — relevo sombreado passa a ser o PADRÃO. Em Caravelas o hipsométrico
# consome a faixa de cor toda nos primeiros metros e compete visualmente com a
# lâmina d'água; o sombreado deixa os cordões litorâneos legíveis e o azul da
# inundação em primeiro plano. O hipsométrico continua disponível para quando
# a leitura de cota absoluta importar mais que a forma do terreno.
fundo = st.sidebar.radio("Fundo", ["hillshade", "hipsometrico", "limpo"],
                         index=0,
                         format_func={"hillshade": "Relevo sombreado (padrão)",
                                      "hipsometrico": "Hipsométrico + relevo sombreado",
                                      "limpo": "Sem fundo"}.get)
exagero = st.sidebar.slider("Exagero vertical", 1, 120,
                            core.CONFIG_MAPA["exagero_vertical"], 1)
mostrar_isoladas = st.sidebar.toggle("Destacar depressões sem conexão", value=True)
core.CONFIG_MAPA["alpha_agua"] = st.sidebar.slider("Opacidade da lâmina d'água",
                                                   0.2, 1.0, 0.62, 0.02)

# v1.2 — tema das FIGURAS, separado do tema da aplicação (esse vem de
# .streamlit/config.toml). Padrão escuro no modo web, para casar com a
# interface publicada; claro no modo local, que é de onde saem os PNG do
# relatório. As cores cartográficas não mudam com o tema — ver CONFIG_TEMA.
tema_figura = "escuro" if st.sidebar.toggle(
    "Tema escuro nas figuras", value=MODO_WEB,
    help="Muda apenas o papel da figura (fundo, título, eixos). As cores de "
         "inundação, depressão isolada e oceano são as mesmas nos dois temas. "
         "Para o relatório impresso, desligue antes de baixar o PNG."
) else "claro"
_pal = core.paleta(tema_figura)


# =============================================================================
# PROCESSAMENTO
# =============================================================================

mascaras = fonte.mascara_inundacao_auto(
    core, dados, cota["cota_m"],
    conectividade=conectividade, semear_bordas=semear_bordas,
    area_minima_ha=area_min, mascara_agua=mascara_agua, limiar=limiar)

est = core.estatisticas_area(mascaras, dados["dem"], dados["area_pixel_m2"])
hs = _hillshade(caminho, exagero)


# =============================================================================
# PAINEL PRINCIPAL
# =============================================================================

st.title("Exposição ao Nível Médio Relativo do Mar — Caravelas (BA)")
st.caption(f"{rotulo_cen} · datum {core.NIVEIS_MARE[chave_mare]['rotulo']} · "
           f"cota total **{cota['cota_m']:.2f} m** sobre o {core.CONFIG_DEM['datum_vertical']}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Área emersa atual", f"{est['area_terra_km2']:,.1f} km²")
c2.metric("Área inundada", f"{est['area_inundada_km2']:,.1f} km²",
          f"{est['pct_inundada']:.1f}% da área emersa")
c3.metric("Área remanescente", f"{est['area_remanescente_km2']:,.1f} km²")
c4.metric("Depressões sem conexão", f"{est['area_isolada_km2']:,.1f} km²",
          help="Terreno abaixo da cota que NÃO tem caminho hidráulico até o mar. "
               "Os simuladores online contam isto como inundação.")

aba_mapa, aba_mapa_web, aba_curva, aba_tabela, aba_meta = st.tabs(
    ["🗺️ Mapa", "🌐 Mapa interativo", "📈 Curva de exposição",
     "📊 Matriz de cenários", "ℹ️ Metadados"])

# ---- Mapa -------------------------------------------------------------------
with aba_mapa:
    subtitulo = (f"{rotulo_cen} · cota {cota['cota_m']:.2f} m · "
                 f"{'com' if conectividade else 'SEM'} teste de conectividade")
    fig, ax = core.figura_mapa(dados, mascaras, cota, subtitulo=subtitulo,
                               mostrar_isoladas=mostrar_isoladas, fundo=fundo,
                               hs=hs, tema=tema_figura,
                               figsize=CONFIG_UI["figsize"])
    st.pyplot(fig, width="stretch")

    col_a, col_b = st.columns(2)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=core.CONFIG_MAPA["dpi_export"],
                bbox_inches="tight", facecolor=fig.get_facecolor())
    if tema_figura == "escuro":
        st.caption("O PNG sai com o mesmo fundo escuro da tela. Para o "
                   "relatório impresso, desligue **Tema escuro nas figuras** "
                   "na barra lateral antes de baixar.")
    col_a.download_button(
        "⬇️ Baixar mapa (PNG 300 dpi)", buf.getvalue(),
        file_name=f"mapa_nmrm_{cota['cota_m']:.2f}m.png", mime="image/png",
        width="stretch")

    if col_b.button("💾 Gravar GeoTIFF classificado", width="stretch"):
        saida = str(config.DIR_SAIDAS / f"inundacao_{cota['cota_m']:.2f}m.tif")
        core.exportar_geotiff(mascaras, dados, saida, cota["cota_m"])
        st.success(f"Salvo em `{saida}` — pronto para o QGIS e para o "
                   "cruzamento com MapBiomas na Parte 2.")
    plt.close(fig)

# ---- Mapa interativo ---------------------------------------------------------
with aba_mapa_web:
    st.markdown("Mesma classificação da aba **Mapa**, sobreposta a um basemap "
                "real (satélite ou OpenStreetMap) — útil para reconhecimento "
                "de campo, não substitui a figura de 300 dpi da aba Mapa.")

    cores_overlay = {
        mapaweb.CODIGOS_CLASSE["inundada"]:   core.CONFIG_MAPA["cor_inundado"],
        mapaweb.CODIGOS_CLASSE["isolada"]:    core.CONFIG_MAPA["cor_isolado"],
        mapaweb.CODIGOS_CLASSE["agua_atual"]: core.CONFIG_MAPA["cor_oceano"],
    }

    t0 = time.perf_counter()
    png_uri, bounds_web = _overlay_web(
        caminho, caminho_mascara_agua, caminho_limiar, cota["cota_m"],
        conectividade, semear_bordas, area_min, cores_overlay)
    t_overlay_ms = (time.perf_counter() - t0) * 1000

    centro_lat = (bounds_web[0][0] + bounds_web[1][0]) / 2
    centro_lon = (bounds_web[0][1] + bounds_web[1][1]) / 2

    mapa_web = folium.Map(location=[centro_lat, centro_lon], zoom_start=11, tiles=None)

    folium.TileLayer(
        tiles=("https://server.arcgisonline.com/ArcGIS/rest/services/"
               "World_Imagery/MapServer/tile/{z}/{y}/{x}"),
        attr=("Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, "
              "GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community"),
        name="Esri World Imagery",
        overlay=False, control=True,
    ).add_to(mapa_web)

    folium.TileLayer(
        tiles="OpenStreetMap",
        name="OpenStreetMap",
        overlay=False, control=True,
    ).add_to(mapa_web)

    # NÃO adicionar basemap da CARTO aqui. Desde 2025 os basemaps públicos
    # (dark_matter, positron) exigem API key e as tiles voltam carimbadas com
    # "API KEY REQUIRED" por cima do mapa. Tentado e revertido na v1.2.
    # Se um dia quisermos basemap escuro, usar um provedor sem chave ou
    # registrar uma em https://carto.com/basemaps/apikey/.

    folium.raster_layers.ImageOverlay(
        image=png_uri,
        bounds=bounds_web,
        opacity=core.CONFIG_MAPA["alpha_agua"],
        name=f"Exposição · cota {cota['cota_m']:.2f} m",
        interactive=False,
        cross_origin=False,
        zindex=1,
    ).add_to(mapa_web)

    folium.LayerControl(collapsed=False).add_to(mapa_web)

    # returned_objects=[] — sem isso, todo movimento do mouse sobre o mapa
    # (pan, hover) reenvia estado ao Streamlit e reroda o script inteiro.
    st_folium(mapa_web, width=None, height=650, returned_objects=[])

    st.caption(f"Overlay (recorte + reprojeção + PNG) processado em "
               f"{t_overlay_ms:.0f} ms nesta chamada — cacheado por cota/"
               f"conectividade/borda/área mínima; recarregar sem mudar "
               f"nenhum desses é praticamente instantâneo.")

# ---- Curva ------------------------------------------------------------------
with aba_curva:
    st.markdown("Área inundada em função do NMRM — a **curva hipsométrica efetiva** "
                "da planície. Onde ela vira para cima está o limiar em que a "
                "planície de Caravelas passa a responder de forma não linear.")
    # `topo` entra na chave do @st.cache_data. Passar `nmrm` cru faria cada
    # passo de 0,05 m do slider Manual recalcular a curva inteira — no modo
    # local isso é um flood-fill por ponto. Só mandamos `topo` quando a
    # extensão do eixo realmente vai acontecer; abaixo disso vai None e a
    # curva volta a ser cacheada como era antes da v1.2.
    _topo_curva = float(nmrm) if nmrm > CONFIG_UI["nmrm_max"] else None
    df_curva = _curva(caminho, caminho_mascara_agua, caminho_limiar, mare,
                      conectividade, semear_bordas, CONFIG_UI["curva_passo"],
                      topo=_topo_curva)
    if nmrm > CONFIG_UI["nmrm_max"]:
        st.caption(
            f"Eixo estendido até +{nmrm:.2f} m para acompanhar o modo Manual. "
            f"Acima de +{CONFIG_UI['nmrm_max']:.1f} m o passo é de "
            f"{CONFIG_UI['curva_passo_extra']:.2f} m.")

    fig2, ax2 = plt.subplots(figsize=(9, 4.5), constrained_layout=True)
    fig2.patch.set_facecolor(_pal["fundo_figura"])
    ax2.set_facecolor(_pal["fundo_figura"])
    ax2.plot(df_curva["NMRM (m)"], df_curva["Área inundada (km²)"],
             color="#1F6FEB", lw=2.2)
    ax2.fill_between(df_curva["NMRM (m)"], 0, df_curva["Área inundada (km²)"],
                     color="#1F6FEB", alpha=0.15)
    for nome_c, prop in core.CENARIOS_AR6.items():
        v = prop[2100]["mediana"]
        ax2.axvline(v, color=prop["cor"], ls="--", lw=1.1)
        ax2.text(v, ax2.get_ylim()[1] * 0.97, f" {nome_c}", rotation=90,
                 va="top", ha="left", fontsize=7.5, color=prop["cor"])
    ax2.axvline(nmrm, color=_pal["texto"], lw=1.6)
    ax2.set_xlabel("NMRM (m)", color=_pal["texto"])
    ax2.set_ylabel("Área inundada (km²)", color=_pal["texto"])
    ax2.tick_params(colors=_pal["texto_fraco"])
    for _s in ax2.spines.values():
        _s.set_color(_pal["borda"])
    ax2.grid(alpha=0.25, color=_pal["grade"])
    st.pyplot(fig2, width="stretch")
    plt.close(fig2)

    st.download_button("⬇️ Baixar curva (CSV)",
                       df_curva.to_csv(index=False).encode("utf-8-sig"),
                       file_name="curva_exposicao_nmrm.csv", mime="text/csv")

# ---- Tabela -----------------------------------------------------------------
with aba_tabela:
    st.markdown("Matriz cenário × horizonte × percentil, mais os níveis de "
                "sensibilidade definidos pela turma.")
    df_tab = _tabela(caminho, caminho_mascara_agua, caminho_limiar, mare,
                     conectividade, semear_bordas)
    st.dataframe(df_tab, width="stretch", hide_index=True)
    st.download_button("⬇️ Baixar tabela (CSV)",
                       df_tab.to_csv(index=False).encode("utf-8-sig"),
                       file_name="matriz_cenarios_nmrm.csv", mime="text/csv")

# ---- Metadados --------------------------------------------------------------
with aba_meta:
    st.subheader("Decomposição da cota")
    st.table({k: [f"{v:+.3f} m"] for k, v in cota["parcelas"].items()})

    st.subheader("Raster")
    st.json({
        "arquivo": os.path.basename(caminho),
        "dimensoes_px": list(dados["dem"].shape),
        "resolucao_m": [dados["res_x"], dados["res_y"]],
        "crs": dados["crs"].to_string() if dados["crs"] else None,
        "datum_vertical": core.CONFIG_DEM["datum_vertical"],
        "area_pixel_m2": dados["area_pixel_m2"],
    })

    st.subheader("Como o nível médio entra na conta")
    st.markdown(
        "O nível médio **não foi calculado** por esta ferramenta: ele é "
        "herdado do datum vertical do próprio MDE. O FABDEM é referenciado ao "
        f"geoide **{core.CONFIG_DEM['datum_vertical']}**, e a simulação corta o "
        "terreno em z = 0 m nesse datum — ou seja, a v1 assume "
        "`nível médio local ≈ geoide`, com "
        f"`OFFSET_GEOIDE_NM_M = {core.OFFSET_GEOIDE_NM_M:.2f} m`.\n\n"
        "Essa igualdade é uma **aproximação**. A diferença real entre geoide e "
        "superfície média do mar é a topografia dinâmica média (MDT), "
        "sustentada por correntes, vento e densidade — de ordem decimétrica no "
        "Atlântico Sul tropical, portanto comparável ao próprio NMRM de 2050. "
        "Nenhuma constante harmônica foi usada até aqui: os offsets de "
        "PM/PMS/HAT seguem em 0,00 m com `PROVISORIO = True`.")

    st.subheader("Procedência dos cenários")
    st.markdown(
        f"- **Referência:** {core.FONTE_CENARIOS['referencia']}\n"
        f"- **Conferido:** {core.FONTE_CENARIOS['conferido']}\n"
        f"- **A conferir:** {core.FONTE_CENARIOS['a_conferir']}\n"
        f"- **Substituir por:** {core.FONTE_CENARIOS['substituir_por']}")

    st.subheader("Fonte de dados")
    st.caption(FONTE["rotulo"])
    _meta_web = FONTE.get("metadados")
    if _meta_web:
        st.markdown("**Diagnóstico do recorte (modo web)**")
        st.json(_meta_web.get("diagnostico_recorte", {}))
        for _obs in _meta_web.get("observacoes", []):
            if "TETO" in _obs or "achatado" in _obs:
                st.warning(_obs, icon="⚠️")

    st.subheader("Limitações declaradas")
    st.markdown(
        "- Modelo de **exposição estática** (bathtub com teste de conectividade). "
        "Não resolve hidrodinâmica, atenuação da maré no estuário, ondas nem drenagem.\n"
        "- O FABDEM remove dossel e edificações do Copernicus DEM, mas mantém "
        "incerteza vertical de ordem decimétrica a métrica — comparável aos "
        "próprios incrementos de NMRM simulados.\n"
        "- Não há **resposta morfodinâmica**: acresção de manguezal, migração de "
        "duna e aporte sedimentar não são representados. Em planície progradante "
        "como a de Caravelas isso tende a **superestimar** a perda.\n"
        "- Os valores SSP são **globais**; substituir pelos valores locais de NMRM "
        "(NASA/IPCC AR6 Sea Level Projection Tool, Garner et al.).\n"
        "- Cenário não é previsão; projeção não é mapa final; NMRM não é média global.")
