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
    "nmrm_max":        3.0,
    "nmrm_passo":      0.05,
    "curva_passo":     0.10,
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
           mare_m: float, conectividade: bool, semear_bordas: bool, passo: float):
    d = _carregar(caminho)
    ma = (_carregar_mascara_agua(caminho_mascara_agua)
          if os.path.exists(caminho_mascara_agua) else None)
    lm = _carregar_limiar(caminho_limiar) if caminho_limiar else None

    cotas = np.arange(CONFIG_UI["nmrm_min"], CONFIG_UI["nmrm_max"] + 1e-9, passo)
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

st.sidebar.divider()

# ---- 1. Cenário -------------------------------------------------------------
st.sidebar.subheader("1 · Cenário de NMRM")

modo = st.sidebar.radio("Origem do valor",
                        ["Cenário IPCC AR6", "Níveis da turma", "Manual"],
                        horizontal=False)

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
    nmrm = st.sidebar.slider("NMRM (m)", CONFIG_UI["nmrm_min"], CONFIG_UI["nmrm_max"],
                             1.0, CONFIG_UI["nmrm_passo"])
    rotulo_cen = f"Manual +{nmrm:.2f} m"

# ---- 2. Maré e sobrelevação -------------------------------------------------
st.sidebar.subheader("2 · Empilhamento de maré")

chaves_mare = [k for k in core.NIVEIS_MARE if k != "PROVISORIO"]
chave_mare = st.sidebar.selectbox(
    "Datum de referência", chaves_mare,
    format_func=lambda k: core.NIVEIS_MARE[k]["rotulo"])
mare = core.NIVEIS_MARE[chave_mare]["offset_m"]

if core.NIVEIS_MARE["PROVISORIO"]:
    st.sidebar.warning(
        "Datums de maré ainda **provisórios (0,00 m)**. "
        "Preencher `NIVEIS_MARE` em `slr_core.py` com as constantes "
        "harmônicas do BNDO/CHM ou com a estação Caravelas do catálogo FEMAR.",
        icon="⚠️")

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
area_min = st.sidebar.number_input("Área mínima de mancha (ha)", 0.0, 100.0, 0.0, 0.5)

# ---- 4. Cartografia ---------------------------------------------------------
st.sidebar.subheader("4 · Cartografia")
fundo = st.sidebar.radio("Fundo", ["hipsometrico", "hillshade", "limpo"],
                         format_func={"hipsometrico": "Hipsométrico + relevo sombreado",
                                      "hillshade": "Relevo sombreado",
                                      "limpo": "Sem fundo"}.get)
exagero = st.sidebar.slider("Exagero vertical", 1, 120,
                            core.CONFIG_MAPA["exagero_vertical"], 1)
mostrar_isoladas = st.sidebar.toggle("Destacar depressões sem conexão", value=True)
core.CONFIG_MAPA["alpha_agua"] = st.sidebar.slider("Opacidade da lâmina d'água",
                                                   0.2, 1.0, 0.62, 0.02)


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
                               hs=hs, figsize=CONFIG_UI["figsize"])
    st.pyplot(fig, width="stretch")

    col_a, col_b = st.columns(2)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=core.CONFIG_MAPA["dpi_export"],
                bbox_inches="tight", facecolor="white")
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
    df_curva = _curva(caminho, caminho_mascara_agua, caminho_limiar, mare,
                      conectividade, semear_bordas, CONFIG_UI["curva_passo"])

    fig2, ax2 = plt.subplots(figsize=(9, 4.5), constrained_layout=True)
    ax2.plot(df_curva["NMRM (m)"], df_curva["Área inundada (km²)"],
             color="#1F6FEB", lw=2.2)
    ax2.fill_between(df_curva["NMRM (m)"], 0, df_curva["Área inundada (km²)"],
                     color="#1F6FEB", alpha=0.15)
    for nome_c, prop in core.CENARIOS_AR6.items():
        v = prop[2100]["mediana"]
        ax2.axvline(v, color=prop["cor"], ls="--", lw=1.1)
        ax2.text(v, ax2.get_ylim()[1] * 0.97, f" {nome_c}", rotation=90,
                 va="top", ha="left", fontsize=7.5, color=prop["cor"])
    ax2.axvline(nmrm, color="k", lw=1.6)
    ax2.set_xlabel("NMRM (m)")
    ax2.set_ylabel("Área inundada (km²)")
    ax2.grid(alpha=0.25)
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
