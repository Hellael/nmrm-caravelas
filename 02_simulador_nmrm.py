"""
02_simulador_nmrm.py — Simulador interativo de exposição ao NMRM
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB — Caravelas (BA)

Interface Streamlit sobre o motor `slr_core.py`.
Toda a ciência está no motor; este arquivo só desenha controles.

COMO RODAR (local):
    pip install -r requirements.txt
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
from folium.plugins import MousePosition
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import config
import src.cobertura as cob
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

    # v1.3 — o mapa precisa caber numa tela sem rolagem. A figura do
    # matplotlib é quadrada (o recorte tem 65,8 x 69,8 km), então largura
    # cheia numa tela ampla vira uma imagem alta demais: quem manda no
    # tamanho final é a LARGURA da coluna, não o figsize.
    "figsize":            (8.0, 7.0),
    "largura_figura_pct": 58,     # % da largura útil ocupada pela figura estática
    "altura_mapa_px":     620,    # altura do mapa interativo (cabe em tela de 1080p)
    "altura_mapa_min":    420,
    "altura_mapa_max":    900,

    # Opacidade padrão das camadas novas do mapa interativo.
    "opacidade_topo":      0.80,
    "opacidade_cobertura": 0.75,
}

# Onde o ponto consultado no mapa fica guardado entre reruns do Streamlit.
CHAVE_PONTO = "nmrm_ponto_consultado"

# Formatador de coordenada do MousePosition (JavaScript, roda no navegador).
_FORMATADOR_COORD = "function(n){return L.Util.formatNum(n, 5) + '\u00b0';};"

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


@st.cache_data(show_spinner="Gerando a camada topográfica (FABDEM)...")
def _overlay_topo(caminho: str):
    """
    Hipsométrico do PRÓPRIO FABDEM. Cacheado só pelo caminho do MDE: a
    topografia não muda com cenário, maré nem conectividade.
    """
    d = _carregar(caminho)
    return mapaweb.gerar_overlay_hipsometrico(d["dem"], d["transform"], d["crs"])


@st.cache_data(show_spinner="Traçando as isolinhas (FABDEM)...")
def _isolinhas(caminho: str):
    d = _carregar(caminho)
    return mapaweb.gerar_isolinhas_geojson(d["dem"], d["transform"], d["crs"])


@st.cache_resource(show_spinner="Lendo a cobertura MapBiomas...")
def _carregar_cobertura(caminho: str):
    # Retorna None quando o recorte não existe — a camada é opcional e a
    # simulação nunca depende dela.
    return cob.carregar_cobertura(caminho)


@st.cache_data(show_spinner="Gerando overlay de cobertura...")
def _overlay_cobertura(caminho: str):
    d = _carregar_cobertura(caminho)
    if d is None:
        return None, None, []
    uri, bounds = mapaweb.gerar_overlay_web(
        d["classes"], d["transform"], d["crs"], cob.cores_overlay(d))
    return uri, bounds, cob.legenda_para_interface(cob.resumo_classes(d))


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

# v1.3 — cobertura do solo. `FONTE.get` e não `FONTE[...]`: um dados_web/
# gerado por versão anterior do 03 não tem a chave, e faltar a camada não
# pode derrubar a ferramenta.
caminho_cobertura = FONTE.get("cobertura") or ""
tem_cobertura = bool(caminho_cobertura and os.path.exists(caminho_cobertura))

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

# ---- 5. Camadas do mapa interativo ------------------------------------------
# v1.3 — o mapa interativo virou a aba principal, então o controle das camadas
# sobe para a barra lateral em vez de ficar escondido dentro da aba.
st.sidebar.subheader("5 · Camadas do mapa interativo")

ver_exposicao = st.sidebar.toggle(
    "Exposição ao NMRM", value=True,
    help="A lâmina d'água do cenário selecionado — a mesma classificação da "
         "aba Mapa (figura).")

ver_topo = st.sidebar.toggle(
    "Topografia (hipsométrico FABDEM)", value=False,
    help="Faixas de elevação do PRÓPRIO FABDEM que a simulação corta. "
         "Não são tiles de terreno de terceiros: em planície com manguezal o "
         "viés de dossel dessas fontes é maior que o NMRM simulado.")

_niveis_iso_txt = " · ".join(f"{v:g}".replace(".", ",")
                             for v in mapaweb.CONFIG_TOPO["niveis_m"])
ver_isolinhas = st.sidebar.toggle(
    f"Isolinhas ({_niveis_iso_txt} m)", value=False,
    help="Traçadas do mesmo FABDEM, com suavização e simplificação para o "
         "navegador aguentar. Passe o mouse para ler a cota.")

if tem_cobertura:
    ver_cobertura = st.sidebar.toggle(
        "Cobertura MapBiomas Col. 11 (2025)", value=False,
        help="Camada VISUAL. Nesta versão a cobertura não entra em nenhuma "
             "conta — o cruzamento com a inundação é a Parte 2.")
else:
    ver_cobertura = False
    st.sidebar.caption(
        "Cobertura MapBiomas indisponível — rode `04_prepara_cobertura.py` "
        "para gerar o recorte.")

opac_topo = st.sidebar.slider("Opacidade da topografia", 0.1, 1.0,
                              CONFIG_UI["opacidade_topo"], 0.05,
                              disabled=not ver_topo)
opac_cob = st.sidebar.slider("Opacidade da cobertura", 0.1, 1.0,
                             CONFIG_UI["opacidade_cobertura"], 0.05,
                             disabled=not ver_cobertura)
altura_mapa = st.sidebar.slider(
    "Altura do mapa (px)", CONFIG_UI["altura_mapa_min"], CONFIG_UI["altura_mapa_max"],
    CONFIG_UI["altura_mapa_px"], 20,
    help="Ajuste para o mapa caber inteiro na sua tela sem rolagem.")
largura_figura = st.sidebar.slider(
    "Largura da figura estática (%)", 40, 100, CONFIG_UI["largura_figura_pct"], 2,
    help="A figura da aba Mapa é quase quadrada. Reduzir a largura é o que "
         "faz a altura caber na tela.")


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

# v1.3 — o MAPA INTERATIVO passa a ser a aba principal. Motivo: a leitura que
# a disciplina pede é "onde", e "onde" só fecha com base cartográfica real
# embaixo. A figura de 300 dpi continua sendo o produto do relatório, mas é
# consulta, não porta de entrada.
aba_mapa_web, aba_mapa, aba_curva, aba_tabela, aba_meta = st.tabs(
    ["🌐 Mapa interativo", "🗺️ Figura (300 dpi)", "📈 Curva de exposição",
     "📊 Matriz de cenários", "ℹ️ Metadados"])


def _legenda_html(itens: list, titulo: str) -> str:
    """Legenda em faixas horizontais. O folium não desenha legenda de overlay
    raster, então ela é montada aqui, no HTML do Streamlit, e herda o tema
    escuro da aplicação sem precisar de cor fixa de texto."""
    blocos = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;'
        f'margin:0 14px 6px 0;font-size:0.80rem;white-space:nowrap;">'
        f'<span style="width:14px;height:14px;border-radius:3px;'
        f'background:{i["cor"]};border:1px solid rgba(128,128,128,.55);'
        f'display:inline-block;"></span>{i["rotulo"]}</span>'
        for i in itens)
    return (f'<div style="margin:2px 0 6px 0;"><div style="font-size:0.78rem;'
            f'opacity:.7;margin-bottom:4px;">{titulo}</div>'
            f'<div style="display:flex;flex-wrap:wrap;">{blocos}</div></div>')


# ---- Mapa interativo (principal) --------------------------------------------
with aba_mapa_web:
    dados_cob = _carregar_cobertura(caminho_cobertura) if tem_cobertura else None

    def _leitura_ponto(ponto) -> dict | None:
        """
        Lê todas as camadas num ponto (lat, lon) e devolve o que o popup e as
        métricas mostram. Uma função só para os dois, senão o balão no mapa e o
        número embaixo dele acabariam divergindo na primeira alteração.
        """
        if not ponto:
            return None
        lat, lon = float(ponto[0]), float(ponto[1])

        z = mapaweb.valor_no_ponto(dados["dem"], dados["transform"],
                                   dados["crs"], lat, lon)
        inund = mapaweb.valor_no_ponto(mascaras["inundada"].astype("uint8"),
                                       dados["transform"], dados["crs"], lat, lon)
        isol = mapaweb.valor_no_ponto(mascaras["isolada"].astype("uint8"),
                                      dados["transform"], dados["crs"], lat, lon)
        # No modo web o MDE leve foi achatado (clamp) em `_clamp_web` — acima
        # disso o valor lido é o teto, não o terreno real. `-0.005` absorve o
        # arredondamento de ida e volta pelo armazenamento em cm (int16).
        _teto_web = _clamp_web if MODO_WEB else None
        faixa = mapaweb.faixa_da_cota(z, teto_m=_teto_web)
        no_teto = (_teto_web is not None and z is not None
                   and z >= _teto_web - 0.005)

        if z is None:
            situacao = "fora do terreno (oceano ou sem dado)"
        elif inund:
            situacao = "inundada — conectada ao mar"
        elif isol:
            situacao = "abaixo da cota, SEM conexão"
        else:
            situacao = "acima da cota"

        # Folga = quanto o terreno está acima (ou abaixo) da cota do cenário.
        # É a leitura que o usuário quer de fato: "falta quanto para alagar aqui".
        folga = None if z is None else z - cota["cota_m"]
        if no_teto:
            cota_txt = f"≥ {_teto_web:.2f} m (teto do modo web)"
            folga_txt = f"≥ {_teto_web - cota['cota_m']:.2f} m acima da cota do cenário"
        elif folga is None:
            cota_txt = "—"
            folga_txt = "—"
        elif folga >= 0:
            cota_txt = f"{z:.2f} m"
            folga_txt = f"{folga:.2f} m acima da cota do cenário"
        else:
            cota_txt = f"{z:.2f} m"
            folga_txt = f"{abs(folga):.2f} m abaixo da cota do cenário"

        codigo = None
        classe_nome, cor_classe = "—", "#9E9E9E"
        if dados_cob is not None:
            codigo = mapaweb.valor_no_ponto(dados_cob["classes"], dados_cob["transform"],
                                            dados_cob["crs"], lat, lon)
            if codigo in (None, dados_cob["nodata"]):
                codigo = None
                classe_nome = "sem classe no MapBiomas"
            else:
                info = cob.classe(int(codigo))
                classe_nome, cor_classe = info["nome"], info["cor"]

        return {
            "lat": lat, "lon": lon,
            "cota_m": z,
            "cota_txt": cota_txt,
            "faixa_txt": "—" if faixa is None else faixa["faixa"],
            "faixa_cor": "#9E9E9E" if faixa is None else faixa["cor"],
            "situacao": situacao,
            "folga_txt": folga_txt,
            "codigo": codigo,
            "classe": classe_nome,
            "classe_cor": cor_classe,
            "alerta_dossel": cob.alerta_dossel(codigo),
        }

    def _popup_html(l: dict) -> str:
        """Balão do ponto consultado. HTML puro: o folium injeta a string no
        Leaflet, então não há como reaproveitar componente do Streamlit aqui."""
        def _linha(rotulo, valor, cor=None):
            bolinha = (f'<span style="display:inline-block;width:10px;height:10px;'
                       f'border-radius:2px;background:{cor};border:1px solid #6668;'
                       f'margin-right:5px;vertical-align:middle;"></span>'
                       if cor else "")
            return (f'<tr><td style="padding:2px 8px 2px 0;color:#555;'
                    f'white-space:nowrap;">{rotulo}</td>'
                    f'<td style="padding:2px 0;"><b>{bolinha}{valor}</b></td></tr>')

        linhas = [
            _linha(f"Cota ({core.CONFIG_DEM['datum_vertical']})", l["cota_txt"]),
            _linha("Faixa", l["faixa_txt"], l["faixa_cor"]),
            _linha(f"Em {cota['cota_m']:.2f} m", l["situacao"]),
            _linha("Folga", l["folga_txt"]),
        ]
        if dados_cob is not None:
            linhas.append(_linha("Cobertura", l["classe"], l["classe_cor"]))

        aviso = ""
        if l["alerta_dossel"]:
            aviso = ('<div style="margin-top:6px;padding:5px 6px;background:#FFF4CE;'
                     'border-left:3px solid #E0A800;font-size:11px;color:#5A4A00;'
                     'line-height:1.35;">Manguezal: a cota aqui inclui dossel '
                     'residual do FABDEM. Leia como limite superior, não como '
                     'cota do solo.</div>')

        return (f'<div style="font-family:system-ui,sans-serif;font-size:12.5px;'
                f'line-height:1.4;min-width:230px;">'
                f'<div style="font-weight:600;margin-bottom:4px;">'
                f'{l["lat"]:.5f}\u00b0, {l["lon"]:.5f}\u00b0</div>'
                f'<table style="border-collapse:collapse;">{"".join(linhas)}</table>'
                f'{aviso}</div>')

    centro_lat = centro_lon = None
    png_uri = bounds_web = None
    t_overlay_ms = 0.0

    if ver_exposicao:
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

    # O enquadramento vem sempre do MDE, não da camada ligada no momento:
    # assim ligar/desligar camada não faz o mapa pular de lugar.
    uri_topo, bounds_topo = _overlay_topo(caminho)
    centro_lat = (bounds_topo[0][0] + bounds_topo[1][0]) / 2
    centro_lon = (bounds_topo[0][1] + bounds_topo[1][1]) / 2

    mapa_web = folium.Map(location=[centro_lat, centro_lon], zoom_start=11,
                          tiles=None, control_scale=True)

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
    #
    # E NÃO adicionar basemap topográfico de terceiros (OpenTopoMap, Terrarium,
    # Terrain-RGB). Regra 2 do projeto: o relevo dessas fontes não é o FABDEM,
    # e em planície com manguezal o viés de dossel delas é maior que o próprio
    # sinal de NMRM simulado. A topografia daqui é gerada do FABDEM.

    # Ordem de empilhamento (zindex): topografia embaixo, cobertura por cima
    # dela, lâmina d'água por cima de tudo, isolinhas como linha no topo.
    if ver_topo:
        folium.raster_layers.ImageOverlay(
            image=uri_topo, bounds=bounds_topo, opacity=opac_topo,
            name="Topografia — FABDEM (hipsométrico)",
            interactive=False, cross_origin=False, zindex=1,
        ).add_to(mapa_web)

    if ver_cobertura and dados_cob is not None:
        uri_cob, bounds_cob, legenda_cob = _overlay_cobertura(caminho_cobertura)
        if uri_cob:
            folium.raster_layers.ImageOverlay(
                image=uri_cob, bounds=bounds_cob, opacity=opac_cob,
                name=f"Cobertura — {cob.CONFIG_COBERTURA['colecao']} "
                     f"({cob.CONFIG_COBERTURA['ano_referencia']})",
                interactive=False, cross_origin=False, zindex=2,
            ).add_to(mapa_web)
    else:
        legenda_cob = []

    if ver_exposicao and png_uri:
        folium.raster_layers.ImageOverlay(
            image=png_uri, bounds=bounds_web,
            opacity=core.CONFIG_MAPA["alpha_agua"],
            name=f"Exposição · cota {cota['cota_m']:.2f} m",
            interactive=False, cross_origin=False, zindex=3,
        ).add_to(mapa_web)

    if ver_isolinhas:
        geo_isolinhas = _isolinhas(caminho)

        def _estilo_isolinha(feicao):
            destaque = feicao["properties"]["destaque"]
            return {
                "color": mapaweb.CONFIG_TOPO["cor_isolinha"],
                "weight": (mapaweb.CONFIG_TOPO["largura_isolinha_destaque"]
                           if destaque else mapaweb.CONFIG_TOPO["largura_isolinha"]),
                "opacity": 0.95 if destaque else 0.6,
            }

        folium.GeoJson(
            geo_isolinhas, name="Isolinhas — FABDEM (m)",
            style_function=_estilo_isolinha,
            tooltip=folium.GeoJsonTooltip(fields=["rotulo"], aliases=["Cota:"],
                                          sticky=True),
        ).add_to(mapa_web)

    # ---- Ponto consultado ----------------------------------------------------
    # v1.3.1 — a leitura do clique passa a sair EM CIMA do ponto, num popup, e não
    # só nas métricas abaixo do mapa. O ponto vem do `st.session_state`, e não do
    # retorno do `st_folium` desta chamada, por uma questão de ordem: o popup
    # precisa existir no objeto `folium.Map` ANTES de ele ser renderizado, e o
    # retorno do clique só chega depois. Então o clique é guardado, dispara um
    # rerun, e no rerun seguinte o marcador já nasce junto com o mapa.
    leitura = _leitura_ponto(st.session_state.get(CHAVE_PONTO))

    if leitura:
        folium.Marker(
            location=[leitura["lat"], leitura["lon"]],
            tooltip="Ponto consultado — clique em outro lugar para mover",
            popup=folium.Popup(_popup_html(leitura), max_width=330, show=True),
            icon=folium.Icon(color="lightgray", icon_color="#111111",
                             icon="crosshairs", prefix="fa"),
        ).add_to(mapa_web)

    # Latitude/longitude ao vivo sob o cursor. Cota sob o cursor não dá: exigiria
    # mandar a grade inteira (5 M px) para o navegador. O que existe de leitura
    # contínua é o tooltip das isolinhas, que já mostra a cota da linha no hover.
    # O MousePosition puxa um script externo (jsDelivr, mesmo CDN que o folium já
    # usa para o Leaflet). Se o CDN falhar, o controle simplesmente não aparece e
    # o resto do mapa segue funcionando — por isso é aceitável aqui, e por isso
    # nenhuma informação essencial depende dele.
    MousePosition(position="bottomleft", separator=" · ",
                  prefix="cursor:", num_digits=5,
                  lat_formatter=_FORMATADOR_COORD,
                  lng_formatter=_FORMATADOR_COORD).add_to(mapa_web)

    folium.LayerControl(collapsed=True).add_to(mapa_web)

    # returned_objects=["last_clicked"] — sem isso não há leitura de cota no
    # clique; COM mais que isso, todo pan/hover reenviaria estado ao Streamlit
    # e rerodaria o script inteiro. Clique rerroda; mover o mapa, não.
    saida_mapa = st_folium(mapa_web, width=None, height=altura_mapa,
                           returned_objects=["last_clicked"])

    # Só rerroda quando o ponto MUDA. Sem esta comparação o app entraria em
    # rerun infinito: o st_folium devolve o mesmo `last_clicked` em toda
    # execução seguinte, e cada uma pediria outra.
    clique = (saida_mapa or {}).get("last_clicked")
    if clique:
        novo_ponto = (round(float(clique["lat"]), 6), round(float(clique["lng"]), 6))
        if novo_ponto != st.session_state.get(CHAVE_PONTO):
            st.session_state[CHAVE_PONTO] = novo_ponto
            st.rerun()

    # ---- Leitura pontual (mesma informação do popup, em métricas) ------------
    if leitura:
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Ponto consultado", f"{leitura['lat']:.5f}, {leitura['lon']:.5f}")
        p2.metric(f"Cota FABDEM ({core.CONFIG_DEM['datum_vertical']})",
                  leitura["cota_txt"],
                  delta=leitura["faixa_txt"], delta_color="off",
                  help="Valor do pixel de 30 m, sem interpolação. Numa planície "
                       "onde 30 cm decidem o cenário, número interpolado entre "
                       "dois pixels não é medição de lugar nenhum.")
        p3.metric("Situação nesta cota", leitura["situacao"],
                  delta=leitura["folga_txt"], delta_color="off",
                  help="Diferença entre a cota do terreno no ponto e a cota total "
                       "do cenário selecionado.")
        p4.metric("Cobertura MapBiomas", leitura["classe"],
                  help="Camada visual (Coleção 11, 2025). Não entra em nenhuma "
                       "conta desta versão.")
        if leitura["alerta_dossel"]:
            st.warning(
                "Ponto sobre **manguezal**: a cota do FABDEM aqui carrega dossel "
                "residual (mediana de 4,31 m contra 1,91 m do apicum, quando a "
                "zonação de maré prevê o contrário). Leia este número como limite "
                "superior, não como cota do solo — "
                "ver `docs/validacao_mapbiomas_laudo.md` §4.4.", icon="⚠️")
        if st.button("Limpar ponto consultado"):
            st.session_state.pop(CHAVE_PONTO, None)
            st.rerun()
    else:
        st.caption("Clique em qualquer ponto do mapa para abrir ali um balão com a "
                   "cota do FABDEM, a faixa hipsométrica, a situação naquela cota "
                   "e a classe de cobertura do MapBiomas.")

    # ---- Legendas ------------------------------------------------------------
    with st.expander("Legendas das camadas", expanded=False):
        if ver_exposicao:
            itens_exp = [
                {"cor": core.CONFIG_MAPA["cor_inundado"], "rotulo": "Inundação conectada ao mar"},
                {"cor": core.CONFIG_MAPA["cor_isolado"], "rotulo": "Abaixo da cota, sem conexão hidráulica"},
                {"cor": core.CONFIG_MAPA["cor_oceano"], "rotulo": "Oceano/estuário atual (FABDEM)"},
            ]
            st.markdown(_legenda_html(itens_exp,
                        f"Exposição — cota {cota['cota_m']:.2f} m"),
                        unsafe_allow_html=True)
        if ver_topo:
            itens_topo = [{"cor": f["cor"], "rotulo": f["faixa"]}
                          for f in mapaweb.faixas_hipsometricas(
                              teto_m=_clamp_web if MODO_WEB else None)]
            st.markdown(_legenda_html(
                itens_topo,
                f"Topografia — FABDEM V1-2, datum {core.CONFIG_DEM['datum_vertical']}"),
                unsafe_allow_html=True)
        if ver_cobertura and legenda_cob:
            itens_cob = [{"cor": i["cor"],
                          "rotulo": f"{i['nome']} ({i['pct']:.1f}%)"}
                         for i in legenda_cob]
            st.markdown(_legenda_html(
                itens_cob,
                f"Cobertura — {cob.CONFIG_COBERTURA['colecao']}, "
                f"{cob.CONFIG_COBERTURA['ano_referencia']} · classes costeiras primeiro"),
                unsafe_allow_html=True)
            st.caption(cob.FONTE_COBERTURA["limitacao"])
            st.warning(cob.FONTE_COBERTURA["alerta_mangue"], icon="⚠️")

    if ver_exposicao:
        st.caption(f"Overlay de exposição (recorte + reprojeção + PNG) processado em "
                   f"{t_overlay_ms:.0f} ms nesta chamada — cacheado por cota/"
                   f"conectividade/borda/área mínima. Topografia e isolinhas são "
                   f"cacheadas pelo MDE e só são geradas uma vez por sessão.")


# ---- Figura de 300 dpi (secundária) ------------------------------------------
with aba_mapa:
    st.markdown("Produto do relatório: mesma classificação do mapa interativo, "
                "em projeção UTM, com barra de escala, seta norte e créditos de "
                "fonte. Use o mapa interativo para reconhecimento; use esta "
                "figura para imprimir.")

    subtitulo = (f"{rotulo_cen} · cota {cota['cota_m']:.2f} m · "
                 f"{'com' if conectividade else 'SEM'} teste de conectividade")
    fig, ax = core.figura_mapa(dados, mascaras, cota, subtitulo=subtitulo,
                               mostrar_isoladas=mostrar_isoladas, fundo=fundo,
                               hs=hs, tema=tema_figura,
                               figsize=CONFIG_UI["figsize"])

    # v1.3 — a figura é quase quadrada (o recorte tem 65,8 x 69,8 km). Em
    # `width="stretch"` numa tela ampla ela ocupava a largura toda e a altura
    # ia junto, exigindo rolagem para ver o mapa inteiro. Centralizar numa
    # coluna mais estreita resolve sem mexer no conteúdo da figura — e o PNG
    # baixado continua com a resolução de sempre.
    _lado = max(0.001, (100 - largura_figura) / 2)
    _esq, _centro, _dir = st.columns([_lado, float(largura_figura), _lado])
    with _centro:
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

    st.subheader("Procedência da cobertura do solo")
    if tem_cobertura:
        st.markdown(
            f"- **Referência:** {cob.FONTE_COBERTURA['referencia']}\n"
            f"- **Legenda:** {cob.FONTE_COBERTURA['legenda']}\n"
            f"- **Conferido:** {cob.FONTE_COBERTURA['conferido']}\n"
            f"- **Validação:** {cob.FONTE_COBERTURA['validacao']}\n"
            f"- **Limitação:** {cob.FONTE_COBERTURA['limitacao']}")
        st.warning(cob.FONTE_COBERTURA["alerta_mangue"], icon="⚠️")
        _d_cob = _carregar_cobertura(caminho_cobertura)
        if _d_cob is not None:
            st.dataframe(cob.resumo_classes(_d_cob).drop(columns=["Costeira"]),
                         width="stretch", hide_index=True)
    else:
        st.caption("Camada de cobertura ausente. Rode `04_prepara_cobertura.py`.")

    st.subheader("Procedência da topografia exibida")
    st.markdown(
        "A camada hipsométrica e as isolinhas do mapa interativo são geradas "
        "**do próprio FABDEM** carregado acima — não são tiles de terreno de "
        "terceiros. É a regra 2 do projeto: em planície com manguezal o viés de "
        "dossel de SRTM/Terrarium/Terrain-RGB é maior que o próprio sinal de "
        "NMRM simulado, e exibir um relevo diferente do que o modelo corta "
        "convidaria a ler no mapa uma cota que a simulação não usou.\n\n"
        f"As isolinhas passam por suavização gaussiana "
        f"(sigma = {mapaweb.CONFIG_TOPO['suavizacao_sigma_px']} px), "
        f"subamostragem de {mapaweb.CONFIG_TOPO['subamostragem']}x e simplificação "
        f"Douglas-Peucker de {mapaweb.CONFIG_TOPO['tolerancia_simplificacao_m']:.0f} m — "
        "necessário para o navegador, e o motivo de a isolinha ser guia de "
        "leitura, não medida. O número que vale é o do clique, que lê o pixel.")

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
        "- A camada de **cobertura MapBiomas** é ilustrativa nesta versão: não "
        "entra em nenhum cálculo, e a classificação a 30 m não separa as "
        "fitofisionomias de restinga que o laudo do Cassurubá distingue em campo.\n"
        "- **Viés de dossel sobre manguezal.** O cruzamento FABDEM × MapBiomas "
        "(set/2026) mostrou o mangue em cota mediana de 4,3 m e o apicum em 1,9 m — "
        "ordem invertida em relação à zonação de maré. O resíduo de dossel sobre "
        "mangue é da ordem de 3 m, maior que o NMRM de 2100: a exposição do "
        "manguezal sai **subestimada** e não deve ser reportada por cenário. "
        "Ver `docs/validacao_mapbiomas_laudo.md`.\n"
        "- As **isolinhas** são suavizadas e simplificadas para o navegador; "
        "a cota exata de um ponto é a do clique, não a da linha desenhada.\n"
        "- Cenário não é previsão; projeção não é mapa final; NMRM não é média global.")
