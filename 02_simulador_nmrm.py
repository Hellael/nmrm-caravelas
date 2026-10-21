"""
02_simulador_nmrm.py — Simulador interativo de exposição ao NMRM
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB — Caravelas (BA)

Interface Streamlit sobre o motor `slr_core.py`.
Toda a ciência está no motor; este arquivo só desenha controles.

v3.0 (02/10/2026) — REDESIGN EM PÁGINAS. A barra lateral única com seis
seções e oito abas virou cinco páginas (`st.navigation`, menu no topo):

    1. Simulador      — uso público: mapa, controles ao lado, figura sob demanda
    2. Turma          — o mesmo simulador com os valores da disciplina
                        pré-selecionados (nada trancado) + análises por UC
    3. Paleoambiente  — os sete estágios de Andrade et al. (2003)
    4. Exposição e cenários — curva de exposição + matriz de cenários
    5. Metadados      — procedência e limitações

Por que páginas e não abas: o Streamlit executa TODAS as abas a cada
interação, e foi isso que derrubou o app no Cloud em 01/10 (figuras de
300 dpi de várias abas na memória ao mesmo tempo). Com páginas só a página
aberta roda. A figura de 300 dpi passou a ser gerada SÓ quando o usuário
pede (botão), pelo mesmo motivo.

COMO RODAR (local):
    pip install -r requirements.txt
    streamlit run 02_simulador_nmrm.py

Pré-requisito no modo local: ter rodado 01_mapa_elevacao.py.

Autor: Helio | Assistência: Claude
"""

import io
import json
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
from rasterio.features import rasterize
from rasterio.warp import transform as _warp_transform
from streamlit_folium import st_folium

import config
import src.cobertura as cob
import src.correntes as corr
import src.fonte_dados as fonte
import src.mapa_web as mapaweb
import src.paleo as paleo
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
    # v1.2 — o modo Manual vai além dos cenários AR6: teste de sensibilidade
    # do terreno e comparação com os paleoníveis holocênicos (Andrade et al.
    # 2003: +4,8 / +3,5 / +2,5 m). O teto real é recalculado adiante contra o
    # raster de limiar e o clamp do MDE leve — este valor é só o desejado.
    "nmrm_max_manual": 10.0,
    "nmrm_aviso_extrapolacao": 3.0,   # acima disto a interface avisa que saiu da faixa AR6
    "sobrelevacao_max_m": 2.0,        # teto do number_input de maré meteorológica
    "fracao_segura_clamp": 0.75,      # não chegar perto do teto artificial do MDE web
    "nmrm_passo":      0.05,
    "curva_passo":     0.10,      # passo fino da curva, até nmrm_max
    "curva_passo_extra": 0.25,    # passo grosso acima de nmrm_max (casa com o limiar web)

    # Atalhos do modo Manual (pílulas abaixo do slider).
    "atalhos_manual_m": [0.5, 1.0, 2.0, 3.0, 5.0],

    "figsize":            (8.0, 7.0),
    "dpi_previa":         110,    # prévia da figura na tela (o download sai em 300 dpi)
    "altura_mapa_px":     680,    # altura do mapa interativo (cabe em tela de 1080p)
    "altura_mapa_min":    420,
    "altura_mapa_max":    1000,
    # Largura da coluna de controles, em fração da página.
    "proporcao_colunas":  (0.30, 0.70),

    # Opacidade padrão das camadas do mapa interativo.
    "opacidade_topo":      0.80,
    "opacidade_cobertura": 0.75,
}

# -----------------------------------------------------------------------------
# PERFIS — Simulador público e Simulador da turma (v3.0).
#
# Herdeiros diretos do "Modo de uso" da v1.4/v1.5: o perfil define o PADRÃO
# dos controles, nunca os tranca (regra mantida a pedido em 02/10/2026). Cada
# perfil guarda os próprios valores (chaves `w_*_{perfil}`), então ir de uma
# página à outra não mistura os ajustes.
#
# Cenários IPCC AR6 (02/10/2026): voltam aos dois perfis, também no modo web,
# MAS rotulados como o que são — nível médio GLOBAL (NMGM), não o relativo
# local de Caravelas. A v1.2 os escondia do público por esse motivo (regra 1);
# a decisão nova é mostrar com o rótulo explícito, até a troca pelos valores
# regionais (NASA/IPCC AR6 Sea Level Projection Tool, Garner et al.).
# -----------------------------------------------------------------------------
CONFIG_PERFIS = {
    "livre": {
        "eyebrow": "Simulador · uso público",
        "titulo": "Até onde o mar chega na planície de Caravelas",
        "texto": ("Escolha um nível do mar e uma referência de maré. O mapa mostra "
                  "o terreno que fica abaixo dessa cota <em>e</em> tem caminho até o mar."),
        "origens": ["Manual", "Cenário IPCC AR6"],
        "origem_padrao": "Manual",
        "camadas_turma_ligadas": False,
        "recorte_padrao": False,
        "ucs_ligadas": False,
        "analises_turma": False,
    },
    "turma": {
        "eyebrow": "Simulador · turma de Ecossistemas Marinhos Costeiros",
        "titulo": "Exposição da área de estudo da turma",
        "texto": ("RESEX Cassurubá, APA Ponta da Baleia/Abrolhos e PARNA Marinho dos "
                  "Abrolhos, até a isóbata de 500 m. A conexão com o mar é resolvida "
                  "no domínio inteiro; o recorte vale para a contagem, o desenho e a "
                  "figura."),
        "origens": ["Níveis da turma", "Manual", "Cenário IPCC AR6"],
        "origem_padrao": "Níveis da turma",
        "camadas_turma_ligadas": True,
        "recorte_padrao": True,
        "ucs_ligadas": False,
        "analises_turma": True,
    },
}

# Parâmetros só das análises da turma.
CONFIG_TURMA = {
    # Abaixo disto a UC é tratada como "fora do recorte do MDE" em vez de
    # mostrar um percentual — caso do PARNA Abrolhos (recife/mar aberto) e da
    # maior parte da APA Ponta da Baleia.
    "limiar_cobertura_minima": 0.01,
}

# Pasta dos dados leves versionados (GeoJSON da turma, etc.), em qualquer modo.
_DIR_WEB = str(config.DIR_RAIZ / fonte.CONFIG_FONTE["subdir_web"])

# Onde o ponto consultado no mapa fica guardado entre reruns (um por perfil).
CHAVE_PONTO = "nmrm_ponto_consultado"

# Estado compartilhado entre páginas: o último cenário simulado alimenta as
# páginas de Exposição e de Metadados.
CHAVE_ESTADO = "nmrm_estado_simulacao"

# Prefixo das chaves de widget que precisam sobreviver à troca de página.
PREFIXO_WIDGET = "w_"

# Formatador de coordenada do MousePosition (JavaScript, roda no navegador).
_FORMATADOR_COORD = "function(n){return L.Util.formatNum(n, 5) + '°';};"

st.set_page_config(page_title="Simulador NMRM — Caravelas (BA)",
                   page_icon="🌊", layout="wide",
                   initial_sidebar_state="collapsed")


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
def _overlay_topo(caminho: str, usar_recorte: bool = False):
    """
    Hipsométrico do PRÓPRIO FABDEM. Cacheado pelo caminho do MDE e pelo
    recorte: a topografia não muda com cenário, maré nem conectividade, mas
    muda com o modo de uso (no modo Turma ela para no limite da área de
    estudo, como todo o resto do mapa).
    """
    d = _carregar(caminho)
    return mapaweb.gerar_overlay_hipsometrico(
        d["dem"], d["transform"], d["crs"], recorte=_recorte_de(caminho, usar_recorte))


@st.cache_data(show_spinner="Traçando as isolinhas (FABDEM)...")
def _isolinhas(caminho: str, usar_recorte: bool = False):
    d = _carregar(caminho)
    return mapaweb.gerar_isolinhas_geojson(
        d["dem"], d["transform"], d["crs"],
        recorte=_recorte_de(caminho, usar_recorte))


@st.cache_resource(show_spinner="Lendo a cobertura MapBiomas...")
def _carregar_cobertura(caminho: str):
    # Retorna None quando o recorte não existe — a camada é opcional e a
    # simulação nunca depende dela.
    return cob.carregar_cobertura(caminho)


@st.cache_resource(show_spinner="Lendo as correntes (CMEMS GLORYS12)...")
def _carregar_correntes(caminho: str, _mtime: float):
    # None quando o produto não existe (rode 11 e 12) — camada opcional.
    # `_mtime` entra na chave do cache: regerar o npz invalida a leitura antiga.
    return corr.carregar(caminho)


@st.cache_data(show_spinner="Desenhando as correntes...")
def _corr_overlay(caminho: str, _mtime: float, ip: int, iz: int):
    return corr.gerar_overlay(_carregar_correntes(caminho, _mtime), ip, iz)


@st.cache_data(show_spinner=False)
def _corr_setas(caminho: str, _mtime: float, ip: int, iz: int):
    return corr.gerar_setas_geojson(_carregar_correntes(caminho, _mtime), ip, iz)


@st.cache_data(show_spinner="Lendo os constituintes de maré (TPXO9-atlas v5)...")
def _mare_tpxo(caminho: str) -> dict | None:
    """
    Lê `dados_web/mare_caravelas_tpxo9v5.json` (produto do 07_mare_tpxo.py,
    rodado FORA deste repo — ver o cabeçalho daquele script). Só leitura:
    nenhum constituinte é recalculado aqui, e os offsets que a simulação usa
    de fato vivem em `core.NIVEIS_MARE` (extraídos deste mesmo JSON, uma vez,
    na hora de escrever o dicionário — não a cada execução). Este loader
    serve só para a interface mostrar o detalhe completo (constituintes,
    ponto, leitura física) sem redigitar nada.

    `None` se o arquivo faltar — quem chama decide como reagir.
    """
    if not os.path.exists(caminho):
        return None
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(show_spinner="Lendo as camadas da área de trabalho da turma...")
def _camadas_turma(dir_dados: str):
    # Vetorial e leve (3 GeoJSON pequenos) — cache mais por consistência com
    # o resto do módulo do que por custo real de releitura.
    return mapaweb.carregar_camadas_turma(dir_dados)


@st.cache_resource(show_spinner="Rasterizando o limite da turma na grade do MDE...")
def _recorte_mascara(caminho: str, dir_dados: str):
    """
    Máscara booleana do recorte do modo Turma (True = dentro), na grade do
    MDE. Estática por dataset — cacheada só por caminho, nunca por cota.
    `None` se `limite_turma.geojson` não carregou (o app segue sem recorte).

    RECORTE É DE RELATO, NÃO DE CÁLCULO: a conectividade é resolvida no
    domínio INTEIRO (flood-fill ou limiar pré-computado) e esta máscara só
    entra depois, na contagem e no desenho. Ver `core.mascara_recorte`.
    """
    geo = (_camadas_turma(dir_dados) or {}).get("limite")
    if geo is None:
        return None
    return core.mascara_recorte(geo, _carregar(caminho))


def _recorte_de(caminho: str, usar: bool):
    """Máscara do recorte se `usar`, senão None (modo Livre = domínio inteiro)."""
    return _recorte_mascara(caminho, _DIR_WEB) if usar else None


# ---- Paleoambiente (v2.1) ---------------------------------------------------
# Toda a ciência vive em `src/paleo.py` (regra da separação motor/interface);
# aqui só o cache. Estas máscaras são ESTÁTICAS por dataset — não dependem de
# cota, de maré nem de cenário —, então são cacheadas por caminho e estágio, e
# nunca por parâmetro da barra lateral.

@st.cache_resource(show_spinner="Lendo as paleolinhas de costa...")
def _paleo_geojson(dir_dados: str):
    """`paleolinhas_turma.geojson`, ou None se não existir — a aba então nem
    aparece. Sem arquivo é ausência de funcionalidade, nunca exceção."""
    return paleo.carregar_paleolinhas(
        os.path.join(dir_dados, paleo.CONFIG_PALEO["arquivo"]))


@st.cache_resource(show_spinner="Rasterizando o quadro das figuras do artigo...")
def _paleo_quadro(caminho: str, dir_dados: str):
    """Máscara do quadro 39°30'–39°00'W x 17°30'–18°00'S na grade do MDE. É
    MENOR que o domínio do simulador: fora dele o artigo não desenhou nada, e
    contar a terra de hoje no domínio inteiro contra um polígono que só cobre o
    quadro daria assimetria de recorte lida como progradação."""
    gj = _paleo_geojson(dir_dados)
    return None if gj is None else paleo.mascara_quadro(core, gj, _carregar(caminho))


@st.cache_resource(show_spinner="Comparando o estágio com a costa atual...")
def _paleo_classes(caminho: str, dir_dados: str, estagio: str):
    """Grade de classes (1=terra nos dois momentos, 2=construída, 3=água hoje)."""
    gj = _paleo_geojson(dir_dados)
    d = _carregar(caminho)
    est = next(e for e in paleo.estagios(gj) if e["estagio"] == estagio)
    return paleo.classificar(paleo.mascara_estagio(core, est, d),
                             np.isfinite(d["dem"]),
                             _paleo_quadro(caminho, dir_dados))


@st.cache_resource(show_spinner="Comparando todos os estágios com a costa atual...")
def _paleo_tabela(caminho: str, dir_dados: str):
    """Áreas de TODOS os estágios (v2.1) — alimenta a tabela comparativa. Mesma
    régua de pixel do estágio selecionado, então os números batem com as
    métricas de cima."""
    gj = _paleo_geojson(dir_dados)
    return None if gj is None else paleo.tabela_estagios(core, gj, _carregar(caminho))


def _geometria_para_utm(geometria: dict, crs_origem: str = "EPSG:4674") -> dict:
    """
    Reprojeta um Polygon/MultiPolygon GeoJSON de `crs_origem` (EPSG:4674 nos
    três arquivos da turma) para a grade UTM do MDE (`config.CRS_ALVO`),
    preservando a estrutura de anéis (buracos inclusive).

    Diferente de `core._geo_para_pixel` (que converte para PIXEL da figura):
    aqui o destino é METRO UTM, porque é isso que `rasterio.features.rasterize`
    espera para casar com `transform` do raster.
    """
    def _reprojetar_anel(anel):
        lons = [p[0] for p in anel]
        lats = [p[1] for p in anel]
        xs, ys = _warp_transform(crs_origem, config.CRS_ALVO, lons, lats)
        return list(zip(xs, ys))

    tipo = geometria["type"]
    if tipo == "Polygon":
        coords = [_reprojetar_anel(anel) for anel in geometria["coordinates"]]
    elif tipo == "MultiPolygon":
        coords = [[_reprojetar_anel(anel) for anel in poligono]
                  for poligono in geometria["coordinates"]]
    else:
        raise ValueError(f"geometria não suportada para rasterização: {tipo}")
    return {"type": tipo, "coordinates": coords}


@st.cache_resource(show_spinner="Rasterizando as UCs na grade do MDE...")
def _mascara_ucs(caminho: str, dir_dados_web: str, usar_recorte: bool = False) -> dict:
    """
    Uma máscara booleana por UC, na MESMA grade do MDE — cacheada só por
    `caminho` (o raster) e `dir_dados_web` (os GeoJSON): a rasterização não
    depende de cota nem de máscara de inundação, então recalcular a cada
    cenário seria trabalho jogado fora (seção 3.c/3.d da aba Turma só
    cruzam esta máscara com `mascaras`/`_mascara_auto`, não a refazem).

    Retorna {cd_cnuc: {"nome", "categoria", "esfera", "ha_total", "mask"}};
    dict vazio se `ucs_turma.geojson` não carregou.

    `usar_recorte`: intersecta cada UC com o recorte da turma (as UCs cabem
    dentro do limite — `09_limite_turma.py` confere —, então na prática é
    no-op; fica explícito para a contagem nunca sair do recorte).
    """
    d = _carregar(caminho)
    rec = _recorte_de(caminho, usar_recorte)
    geo_ucs = (_camadas_turma(dir_dados_web) or {}).get("ucs")
    resultado: dict = {}
    if geo_ucs is None:
        return resultado

    for feicao in geo_ucs.get("features", []):
        props = feicao["properties"]
        geom_utm = _geometria_para_utm(feicao["geometry"])
        mask = rasterize(
            [(geom_utm, 1)], out_shape=d["dem"].shape, transform=d["transform"],
            fill=0, dtype="uint8", all_touched=False,
        ).astype(bool)
        if rec is not None:
            mask &= rec
        resultado[props["cd_cnuc"]] = {
            "nome": props["nome_uc"], "categoria": props["categoria"],
            "esfera": props["esfera"], "ha_total": float(props["ha_total"]),
            "mask": mask,
        }
    return resultado


@st.cache_data(show_spinner="Calculando a cobertura das UCs pelo MDE...")
def _cobertura_ucs(caminho: str, dir_dados_web: str,
                   usar_recorte: bool = False) -> pd.DataFrame:
    """
    Item (b) da aba Turma: por UC, quanto da área OFICIAL (`ha_total`, CNUC)
    cai sobre terreno válido do MDE (`np.isfinite(dem)`) dentro do recorte.
    Usa `ha_total` como denominador (não a área recalculada do polígono):
    é o número oficial e já é a coluna pedida, então não faz sentido gerar
    um segundo número de área que poderia divergir dele.
    """
    d = _carregar(caminho)
    ucs = _mascara_ucs(caminho, dir_dados_web, usar_recorte)
    a = d["area_pixel_m2"] / 1e6
    limiar = CONFIG_TURMA["limiar_cobertura_minima"]

    linhas = []
    for cd, info in ucs.items():
        area_terra_km2 = float((info["mask"] & np.isfinite(d["dem"])).sum()) * a
        area_uc_km2 = info["ha_total"] / 100.0
        fracao = area_terra_km2 / area_uc_km2 if area_uc_km2 > 0 else 0.0
        linhas.append({
            "cd_cnuc": cd,
            "Unidade": info["nome"],
            "Categoria": info["categoria"],
            "Esfera": info["esfera"],
            "Área (ha)": round(info["ha_total"], 1),
            "_area_terra_km2": round(area_terra_km2, 3),
            "_fracao": fracao,
            "Cobertura pelo MDE": ("fora do recorte do MDE" if fracao < limiar
                                   else f"{fracao * 100:.1f}%"),
        })
    return pd.DataFrame(linhas)


@st.cache_data(show_spinner="Cruzando os níveis da turma com as UCs...")
def _matriz_niveis_por_uc(caminho: str, caminho_mascara_agua: str, caminho_limiar: str,
                          mare_m: float, conectividade: bool, semear_bordas: bool,
                          dir_dados_web: str, usar_recorte: bool = False) -> pd.DataFrame:
    """
    Item (d) da aba Turma: os três níveis de `core.NIVEIS_TURMA`, cruzados
    com a rasterização das UCs. Reaproveita `_mascara_auto` — a MESMA função
    de máscara que `_tabela` usa por trás — em vez de reimplementar
    flood-fill; só o cruzamento com a máscara de cada UC é novo aqui.
    """
    d = _carregar(caminho)
    ma = (_carregar_mascara_agua(caminho_mascara_agua)
          if os.path.exists(caminho_mascara_agua) else None)
    lm = _carregar_limiar(caminho_limiar) if caminho_limiar else None
    ucs = _mascara_ucs(caminho, dir_dados_web, usar_recorte)
    a = d["area_pixel_m2"] / 1e6

    linhas = []
    for nivel in core.NIVEIS_TURMA:
        c = core.cota_limiar(nivel, mare_m=mare_m)
        m = _mascara_auto(d, ma, lm, c["cota_m"], conectividade, semear_bordas)
        for info in ucs.values():
            area_terra_uc = float((info["mask"] & np.isfinite(d["dem"])).sum()) * a
            if area_terra_uc <= 0:
                continue  # UC sem terra no recorte — nada para cruzar
            area_inund = float((info["mask"] & m["inundada"]).sum()) * a
            area_isol = float((info["mask"] & m["isolada"]).sum()) * a
            linhas.append({
                "Nível (m)": nivel,
                "Unidade": info["nome"],
                "Área inundada (km²)": round(area_inund, 2),
                "Área isolada (km²)": round(area_isol, 2),
                "% da área emersa da UC": round(100 * area_inund / area_terra_uc, 1),
            })
    return pd.DataFrame(linhas)


@st.cache_data(show_spinner="Gerando overlay de cobertura...")
def _overlay_cobertura(caminho: str, caminho_mde: str = None,
                       usar_recorte: bool = False):
    """
    `caminho` é o recorte de cobertura; `caminho_mde` só entra para montar a
    máscara do recorte, que vive na grade do MDE. O `04_prepara_cobertura.py`
    alinha a cobertura pixel a pixel a essa grade — se um dia as formas
    divergirem, o recorte é PULADO com aviso em vez de casar arrays errados.

    Fora do recorte as classes viram nodata: some do desenho e também do
    resumo e da legenda, que é o que se quer — classe de cobertura fora da
    área de estudo não deveria aparecer em legenda nenhuma.
    """
    d = _carregar_cobertura(caminho)
    if d is None:
        return None, None, []
    rec = _recorte_de(caminho_mde, usar_recorte) if caminho_mde else None
    if rec is not None:
        if rec.shape != d["classes"].shape:
            print(f"[COBERTURA] AVISO: grade da cobertura {d['classes'].shape} != "
                  f"grade do MDE {rec.shape}; recorte NÃO aplicado nesta camada.")
        else:
            d = dict(d)   # cópia rasa: o cache de _carregar_cobertura é compartilhado
            d["classes"] = np.where(rec, d["classes"], d["nodata"])
    uri, bounds = mapaweb.gerar_overlay_web(
        d["classes"], d["transform"], d["crs"], cob.cores_overlay(d))
    return uri, bounds, cob.legenda_para_interface(cob.resumo_classes(d))


@st.cache_data(show_spinner="Gerando overlay do mapa interativo...")
def _overlay_web(caminho: str, caminho_mascara_agua: str, caminho_limiar: str,
                 cota_m: float, conectividade: bool, semear_bordas: bool,
                 area_min: float, cores: dict, usar_recorte: bool = False):
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
    classes = mapaweb.classificar_overlay(
        m, ma if ma is not None else d["mask_oceano"],
        recorte=_recorte_de(caminho, usar_recorte))
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
           topo: float = None, usar_recorte: bool = False):
    d = _carregar(caminho)
    rec = _recorte_de(caminho, usar_recorte)
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
        e = core.estatisticas_area(m, d["dem"], d["area_pixel_m2"], recorte=rec)
        reg.append({"NMRM (m)": round(float(nmrm), 2),
                    "Cota (m)": round(c["cota_m"], 2),
                    "Área inundada (km²)": e["area_inundada_km2"],
                    "% da área emersa": e["pct_inundada"]})
    return pd.DataFrame(reg)


@st.cache_data(show_spinner="Rodando a matriz de cenários...")
def _tabela(caminho: str, caminho_mascara_agua: str, caminho_limiar: str,
            mare_m: float, conectividade: bool, semear_bordas: bool,
            usar_recorte: bool = False):
    d = _carregar(caminho)
    rec = _recorte_de(caminho, usar_recorte)
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
                e = core.estatisticas_area(m, d["dem"], d["area_pixel_m2"], recorte=rec)
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
        e = core.estatisticas_area(m, d["dem"], d["area_pixel_m2"], recorte=rec)
        linhas.append({
            "Cenário": "Sensibilidade (turma)", "Horizonte": "—", "Percentil": "—",
            "NMRM (m)": nivel, "Cota total (m)": round(c["cota_m"], 2),
            "Área inundada (km²)": round(e["area_inundada_km2"], 2),
            "% da área emersa": round(e["pct_inundada"], 2),
            "Depressões isoladas (km²)": round(e["area_isolada_km2"], 2),
        })
    return pd.DataFrame(linhas)


# =============================================================================
# ESTILO, ESTADO E AUXILIARES DE INTERFACE (v3.0)
# =============================================================================
# O tema base (cores, fonte Rubik, cantos) mora em `.streamlit/config.toml`.
# Aqui entra só o que o tema não cobre: o cabeçalho de cada página, o número
# grande do nível do mar, as "pílulas" de destaque e o fundo em gradiente.
# CSS mínimo de propósito — classes PRÓPRIAS (`nmrm-*`), quase nada sobre os
# nomes internos do Streamlit, que mudam entre versões.

_CSS = """
<style>
.stApp { background: radial-gradient(1200px 600px at 8% -12%, #14304F 0%, #0B1220 58%) fixed; }
.nmrm-hero { margin: .25rem 0 1.4rem 0; max-width: 920px; }
.nmrm-eyebrow { font-size: .78rem; font-weight: 600; letter-spacing: .22em;
  text-transform: uppercase; color: #E9B949; margin-bottom: .55rem; }
.nmrm-titulo { font-size: 2.75rem; font-weight: 700; line-height: 1.06;
  color: #F5F7FA; letter-spacing: -.01em; margin: 0 0 .65rem 0; }
.nmrm-texto { font-size: 1.08rem; line-height: 1.55; color: #AEB7C3; margin: 0; }
.nmrm-rotulo { font-size: .72rem; font-weight: 600; letter-spacing: .14em;
  text-transform: uppercase; color: #9AA4B2; margin: .15rem 0 .1rem 0; }
.nmrm-numero { font-family: 'IBM Plex Mono', monospace; font-size: 2.5rem;
  font-weight: 600; color: #FFFFFF; line-height: 1.1; margin: 0 0 .2rem 0; }
.nmrm-numero small { font-size: 1.05rem; color: #9AA4B2; margin-left: .35rem; font-weight: 500; }
.nmrm-chip { display: inline-flex; align-items: center; min-height: 32px; padding: 0 12px;
  border-radius: 999px; background: rgba(29,155,240,.16); color: #9ED3FB;
  font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: .85rem; }
.nmrm-chip.ouro { background: rgba(233,185,73,.14); color: #F3D27E; }
.nmrm-chip-texto { color: #9AA4B2; font-size: .85rem; margin-left: .6rem; }
.nmrm-aviso { display: inline-flex; gap: .55rem; align-items: center; padding: .55rem .9rem;
  border-radius: 12px; background: rgba(233,185,73,.10); border: 1px solid rgba(233,185,73,.35);
  color: #F3D27E; font-size: .92rem; margin: -.4rem 0 1.1rem 0; }
.nmrm-global { padding: .5rem .7rem; border-radius: 10px; background: rgba(242,163,58,.10);
  border: 1px solid rgba(242,163,58,.35); color: #F7C98A; font-size: .82rem; line-height: 1.4; }
[data-testid="stMetricValue"] { font-family: 'IBM Plex Mono', monospace; }
</style>
"""


def _manter_estado():
    """
    Widgets de uma página que NÃO está aberta são apagados do session_state
    no fim da execução (comportamento do Streamlit). Reatribuir a chave a ela
    mesma a cada execução converte o estado do widget em estado comum, que
    sobrevive à troca de página. Só para chaves `w_*` — botões ficam de fora.
    """
    for chave in list(st.session_state.keys()):
        if isinstance(chave, str) and chave.startswith(PREFIXO_WIDGET):
            st.session_state[chave] = st.session_state[chave]


def _padrao(chave: str, valor):
    """Semeia o valor inicial de um widget e devolve a chave. Os widgets
    recebem só `key=` (nunca `value=` junto), senão o Streamlit avisa de
    valor definido em dois lugares."""
    if chave not in st.session_state:
        st.session_state[chave] = valor
    return chave


def _cabecalho(eyebrow: str, titulo: str, texto: str) -> None:
    st.markdown(f'<div class="nmrm-hero"><div class="nmrm-eyebrow">{eyebrow}</div>'
                f'<div class="nmrm-titulo">{titulo}</div>'
                f'<p class="nmrm-texto">{texto}</p></div>', unsafe_allow_html=True)


def _rotulo(texto: str) -> None:
    st.markdown(f'<div class="nmrm-rotulo">{texto}</div>', unsafe_allow_html=True)


def _numero_grande(valor: float, sufixo: str = "m") -> None:
    txt = f"{valor:+.2f}".replace(".", ",")
    st.markdown(f'<div class="nmrm-numero">{txt}<small>{sufixo}</small></div>',
                unsafe_allow_html=True)


def _br(v: float, casas: int = 1) -> str:
    """Número no padrão brasileiro: 2.440,9."""
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_m(v: float) -> str:
    return f"+{v:g} m".replace(".", ",")


def _legenda_html(itens: list, titulo: str) -> str:
    """Legenda em faixas horizontais. O folium não desenha legenda de overlay
    raster, então ela é montada aqui, no HTML do Streamlit."""
    blocos = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;'
        f'margin:0 14px 6px 0;font-size:0.82rem;white-space:nowrap;">'
        f'<span style="width:14px;height:14px;border-radius:4px;'
        f'background:{i["cor"]};border:1px solid rgba(128,128,128,.55);'
        f'display:inline-block;"></span>{i["rotulo"]}</span>'
        for i in itens)
    return (f'<div style="margin:2px 0 6px 0;"><div style="font-size:0.72rem;'
            f'letter-spacing:.12em;text-transform:uppercase;opacity:.7;'
            f'margin-bottom:6px;">{titulo}</div>'
            f'<div style="display:flex;flex-wrap:wrap;">{blocos}</div></div>')


def _chaves_mare() -> list:
    return [k for k in core.NIVEIS_MARE if k not in ("MEDIDA", "FONTE")]


def _png(fig, dpi) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    return buf.getvalue()


def _basemaps(mapa) -> None:
    """Esri World Imagery + OpenStreetMap.

    NÃO adicionar basemap da CARTO (desde 2025 exige API key e as tiles voltam
    carimbadas) nem basemap topográfico de terceiros (regra 2: o relevo exibido
    tem de ser o FABDEM que a simulação corta)."""
    folium.TileLayer(
        tiles=("https://server.arcgisonline.com/ArcGIS/rest/services/"
               "World_Imagery/MapServer/tile/{z}/{y}/{x}"),
        attr=("Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, "
              "GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community"),
        name="Esri World Imagery", overlay=False, control=True,
    ).add_to(mapa)
    folium.TileLayer(tiles="OpenStreetMap", name="OpenStreetMap",
                     overlay=False, control=True).add_to(mapa)


LIMITACOES_MD = (
    "- Modelo de **exposição estática** (bathtub com teste de conectividade). "
    "Não resolve hidrodinâmica, atenuação da maré no estuário, ondas nem drenagem.\n"
    "- O FABDEM remove dossel e edificações do Copernicus DEM, mas mantém "
    "incerteza vertical de ordem decimétrica a métrica — comparável aos "
    "próprios incrementos de NMRM simulados.\n"
    "- Não há **resposta morfodinâmica**: acresção de manguezal, migração de "
    "duna e aporte sedimentar não são representados. Em planície progradante "
    "como a de Caravelas isso tende a **superestimar** a perda.\n"
    "- Os cenários **IPCC AR6** desta versão são o nível médio **global** "
    "(NMGM), não o relativo local; substituir pelos valores locais de NMRM "
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

FONTES_MD = (
    "- **Relevo:** FABDEM V1-2 (Hawker et al. 2022), 30 m, sem dossel e edificações.\n"
    "- **Maré:** TPXO9-atlas v5 (OSU) — modelo global, não marégrafo.\n"
    "- **Cenários:** IPCC AR6 WGI (nível médio global, base 1995–2014).\n"
    "- **Cobertura do solo:** MapBiomas Coleção 11 (2025).\n"
    "- **Unidades de conservação:** CNUC 07/2026 (ICMBio/MMA).\n"
    "- **Isóbatas:** Batimetria do Brasil CPRM/ANP 2013 (GEBCO 925 m).\n"
    "- **Imagem de fundo:** Esri World Imagery.\n\n"
    "Procedência completa e decisões de método na página **Metadados**.")


# =============================================================================
# DADOS COMPARTILHADOS ENTRE AS PÁGINAS
# =============================================================================

st.markdown(_CSS, unsafe_allow_html=True)
_manter_estado()

if FONTE.get("forcado"):
    st.sidebar.warning(
        "**Pré-visualização do modo público.** `NMRM_MODO=web` está ligado: "
        "rodando com os dados leves de `dados_web/`. Limpe a variável de "
        "ambiente para voltar ao modo local.", icon="👁️")

# O campo de caminho só existe no modo local, onde o usuário é quem gerou o
# MDE com o 01_mapa_elevacao.py. É o único uso da barra lateral que restou.
if MODO_WEB:
    caminho = CONFIG_UI["caminho_padrao"]
else:
    caminho = st.sidebar.text_input(
        "MDE (GeoTIFF do script 01)", value=CONFIG_UI["caminho_padrao"],
        help="Saída do 01_mapa_elevacao.py: FABDEM recortado, EPSG:31984, 30 m.")

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
        "Máscara de água não encontrada. Caindo para o método antigo de "
        "conectividade, que **subestima** a área conectada ao mar. Rode "
        "`01_mapa_elevacao.py` novamente para gerar a máscara.", icon="⚠️")

caminho_limiar = FONTE["limiar"] or ""
limiar = _carregar_limiar(caminho_limiar) if caminho_limiar else None

caminho_cobertura = FONTE.get("cobertura") or ""
tem_cobertura = bool(caminho_cobertura and os.path.exists(caminho_cobertura))

GJ_PALEO = _paleo_geojson(_DIR_WEB)
tem_paleo = GJ_PALEO is not None

caminho_correntes = corr.caminho_produto(_DIR_WEB)
_mtime_correntes = os.path.getmtime(caminho_correntes) if os.path.exists(caminho_correntes) else 0.0
D_CORRENTES = _carregar_correntes(caminho_correntes, _mtime_correntes)
tem_correntes = D_CORRENTES is not None

_limite_ok = (_camadas_turma(_DIR_WEB) or {}).get("limite") is not None

# ---- Tetos do NMRM -----------------------------------------------------------
# O raster de limiar (modo web) só é confiável até um teto de cota. Quem
# entra na consulta não é o NMRM puro, é a cota TOTAL de `core.cota_limiar`,
# que soma TRÊS parcelas depois deste clamp: maré (até HAT), sobrelevação
# (até `sobrelevacao_max_m`) e `core.OFFSET_GEOIDE_NM_M` (hoje 0,00 m, mas o
# projeto pretende preenchê-lo — por isso o `abs(...)` entra agora). Descontar
# só o NMRM deixaria a cota total passar do teto em silêncio e a área inundada
# sairia SUBESTIMADA (pixels presos em "isolada"). Ver a guarda equivalente,
# em tempo de execução, dentro de `fonte.mascara_inundacao_auto`.
_maior_offset_mare = max(v["offset_m"] for k, v in core.NIVEIS_MARE.items()
                         if k not in ("MEDIDA", "FONTE"))
_maior_empilhamento = (_maior_offset_mare + CONFIG_UI["sobrelevacao_max_m"]
                       + abs(core.OFFSET_GEOIDE_NM_M))

_teto_limiar = fonte.cota_maxima_limiar(limiar)
if _teto_limiar:
    CONFIG_UI["nmrm_max"] = min(CONFIG_UI["nmrm_max"],
                                max(CONFIG_UI["nmrm_min"], _teto_limiar - _maior_empilhamento))

# Teto do modo Manual: (a) raster de limiar, mesma lógica acima; (b) CLAMP do
# MDE leve — acima de `clamp_m` todo terreno foi achatado, então paramos bem
# antes dele (`fracao_segura_clamp`).
_meta_fonte = FONTE.get("metadados") or {}
_cfg_web = _meta_fonte.get("config", {})
_clamp_web = _cfg_web.get("clamp_m")
_troca_passo_web = _cfg_web.get("limiar_troca_passo_m")
_passo_grosso_web = _cfg_web.get("limiar_passo_grosso_cm")

_teto_manual = CONFIG_UI["nmrm_max_manual"]
if _teto_limiar:
    _teto_manual = min(_teto_manual, _teto_limiar - _maior_empilhamento)
if _clamp_web:
    _teto_manual = min(_teto_manual, CONFIG_UI["fracao_segura_clamp"] * float(_clamp_web))
_teto_manual = max(CONFIG_UI["nmrm_min"], _teto_manual)
# O max() final garante que o slider nunca receba min > max e tem prioridade
# sobre a fração de segurança do clamp — quem mexer em `clamp_m` reavalie.
CONFIG_UI["nmrm_max_manual"] = round(max(_teto_manual, CONFIG_UI["nmrm_max"]), 2)

# Maior valor que o próprio AR6 projeta para 2100 (p83 de baixa confiança).
NMRM_MAX_AR6 = max(c[2100]["p83"] for c in core.CENARIOS_AR6.values())


def _estado_atual() -> dict:
    """Último cenário simulado (Simulador ou Turma). Sem nenhum ainda, o
    padrão do simulador público: Manual +1,00 m, nível médio, com conexão."""
    e = st.session_state.get(CHAVE_ESTADO)
    if e:
        return e
    chave_mare = _chaves_mare()[0]
    mare = core.NIVEIS_MARE[chave_mare]["offset_m"]
    return {
        "perfil": "livre", "nmrm": 1.0, "rotulo_cen": "Manual +1,00 m",
        "chave_mare": chave_mare, "mare": mare,
        "cota": core.cota_limiar(1.0, mare_m=mare),
        "conectividade": True, "semear_bordas": True, "usar_recorte": False,
        "tema_figura": "escuro" if MODO_WEB else "claro",
        "exagero": core.CONFIG_MAPA["exagero_vertical"],
        "altura_mapa": CONFIG_UI["altura_mapa_px"],
    }


# =============================================================================
# CONTROLES DO SIMULADOR (coluna da esquerda)
# =============================================================================

def _controles(p: str) -> dict:
    """
    Desenha o cartão de controles do perfil `p` e devolve os parâmetros.
    Ordem: origem do valor -> nível do mar -> maré -> camadas -> ajustes
    avançados. Tudo o que não é essencial para ler o mapa foi para o popover
    "Ajustes avançados", inclusive o que era a seção 3 (regra hidrológica) e
    a seção 4 (cartografia da figura).
    """
    cfg = CONFIG_PERFIS[p]

    def k(nome):
        return f"{PREFIXO_WIDGET}{nome}_{p}"

    par = {}

    # ---- Origem do valor ------------------------------------------------------
    origem = st.segmented_control(
        "Origem do valor", cfg["origens"],
        key=_padrao(k("origem"), cfg["origem_padrao"]), width="stretch")
    origem = origem or cfg["origem_padrao"]   # o controle permite desmarcar

    # ---- Nível do mar ---------------------------------------------------------
    if origem == "Manual":
        ch_nmrm, ch_atalho = k("nmrm_manual"), k("atalho")
        _padrao(ch_nmrm, 1.0)
        # Um valor guardado acima do teto (ex.: teto menor depois de trocar de
        # dados) quebraria o slider — volta para dentro da faixa.
        st.session_state[ch_nmrm] = min(float(st.session_state[ch_nmrm]),
                                        CONFIG_UI["nmrm_max_manual"])

        def _aplicar_atalho(ka=ch_atalho, kn=ch_nmrm):
            v = st.session_state.get(ka)
            if v is not None:
                st.session_state[kn] = float(v)
                st.session_state[ka] = None

        _rotulo("Nível do mar")
        _numero_grande(st.session_state[ch_nmrm])
        nmrm = st.slider(
            "NMRM (m)", CONFIG_UI["nmrm_min"], CONFIG_UI["nmrm_max_manual"],
            step=CONFIG_UI["nmrm_passo"], key=ch_nmrm, label_visibility="collapsed",
            help=(f"Até +{CONFIG_UI['nmrm_max_manual']:.1f} m. Acima de "
                  f"+{CONFIG_UI['nmrm_aviso_extrapolacao']:.0f} m a simulação sai da "
                  "faixa projetada pelo AR6 e vale como teste de sensibilidade do "
                  "terreno ou comparação com paleoníveis."))
        _atalhos = [v for v in CONFIG_UI["atalhos_manual_m"]
                    if v <= CONFIG_UI["nmrm_max_manual"]]
        st.pills("Atalhos", _atalhos, format_func=_fmt_m, key=ch_atalho,
                 on_change=_aplicar_atalho, label_visibility="collapsed")
        rotulo_cen = f"Manual +{nmrm:.2f} m"

        if nmrm > CONFIG_UI["nmrm_aviso_extrapolacao"]:
            st.warning(
                f"**+{nmrm:.2f} m está fora da faixa do AR6.** O valor mais alto "
                f"projetado para 2100 é +{NMRM_MAX_AR6:.2f} m (SSP5-8.5 de baixa "
                "confiança, percentil 83). Acima disso o mapa é um teste de "
                "sensibilidade da planície — não um cenário climático. Para "
                "referência, os paleoníveis holocênicos de Caravelas "
                "(Andrade et al. 2003) chegam a +4,8 m.", icon="⚠️")
        if MODO_WEB and _troca_passo_web and _passo_grosso_web and nmrm > _troca_passo_web:
            st.caption(
                f"Acima de +{_troca_passo_web:.1f} m a conexão com o mar foi "
                f"pré-computada de {_passo_grosso_web:.0f} em {_passo_grosso_web:.0f} cm: "
                "cotas no mesmo degrau devolvem o mesmo mapa.")

    elif origem == "Níveis da turma":
        _rotulo("Nível de sensibilidade da turma")
        nmrm = st.segmented_control(
            "Nível de sensibilidade", core.NIVEIS_TURMA, format_func=_fmt_m,
            key=_padrao(k("nivel_turma"), 1.0), width="stretch",
            label_visibility="collapsed")
        nmrm = float(nmrm if nmrm is not None else 1.0)
        _numero_grande(nmrm)
        rotulo_cen = f"Sensibilidade espacial +{nmrm:.1f} m"

    else:   # Cenário IPCC AR6
        nome_cen = st.selectbox(
            "Cenário SSP", list(core.CENARIOS_AR6.keys()),
            format_func=lambda c: core.CENARIOS_AR6[c]["rotulo"],
            key=_padrao(k("ssp"), list(core.CENARIOS_AR6.keys())[1]))
        c_h, c_p = st.columns(2)
        with c_h:
            horizonte = st.segmented_control(
                "Horizonte", [2050, 2100], key=_padrao(k("horizonte"), 2100),
                width="stretch") or 2100
        with c_p:
            percentil = st.segmented_control(
                "Percentil", ["p17", "mediana", "p83"],
                format_func={"p17": "17%", "mediana": "50%", "p83": "83%"}.get,
                key=_padrao(k("percentil"), "mediana"), width="stretch",
                help="17% = otimista · 50% = mediana · 83% = pessimista") or "mediana"
        nmrm = core.CENARIOS_AR6[nome_cen][horizonte][percentil]
        rotulo_cen = f"{nome_cen} · {horizonte} · {percentil} (NMGM)"
        _rotulo("Nível do mar do cenário")
        _numero_grande(nmrm)
        st.markdown(
            '<div class="nmrm-global"><b>Nível médio GLOBAL (NMGM)</b>, não o '
            'relativo local de Caravelas. Valores do IPCC AR6 WGI, base '
            '1995–2014 — a troca pelos valores regionais está pendente.</div>',
            unsafe_allow_html=True)

    par["nmrm"], par["rotulo_cen"], par["origem"] = float(nmrm), rotulo_cen, origem

    # ---- Maré -------------------------------------------------------------------
    # TPXO9-atlas v5 (22/09/2026). A procedência completa — modelo e não
    # marégrafo, célula ao largo da barra — está na página Metadados (regra 3:
    # se sair de lá, a tarja precisa voltar para cá).
    chaves_mare = _chaves_mare()
    _dados_mare = _mare_tpxo(str(config.DIR_RAIZ / "dados_web" / config.ARQ_MARE_TPXO))
    _ajuda_mare = None
    if _dados_mare:
        _n = _dados_mare["niveis_m"]
        # Altura acima do NM != amplitude total (2x). 2x PM_quadratura e
        # PM_media dão quase o mesmo número por PURO ACASO — não reaproveite
        # um pelo outro.
        _ajuda_mare = (
            f"Acima do nível médio: quadratura {_n['PM_quadratura_m']:.2f} m · "
            f"média {_n['PM_media_m']:.2f} m · sizígia {_n['PM_sizigia_m']:.2f} m. "
            f"Amplitude total (baixa-mar a preamar): quadratura "
            f"{2 * _n['PM_quadratura_m']:.2f} m · sizígia {2 * _n['PM_sizigia_m']:.2f} m. "
            f"Maré {_n['regime']} (F = {_n['numero_forma_F']:.3f}). "
            "Fonte: TPXO9-atlas v5 — modelo, não medição.")
    chave_mare = st.selectbox(
        "Maré (datum de referência)", chaves_mare,
        format_func=lambda c: core.NIVEIS_MARE[c]["rotulo"],
        key=_padrao(k("mare"), chaves_mare[0]), help=_ajuda_mare)
    mare = core.NIVEIS_MARE[chave_mare]["offset_m"]
    sobrelev = float(st.session_state.get(_padrao(k("sobrelev"), 0.0)))
    cota = core.cota_limiar(par["nmrm"], mare_m=mare, sobrelevacao_m=sobrelev)
    st.caption(f"Cota total **{_br(cota['cota_m'], 2)} m** sobre o "
               f"{core.CONFIG_DEM['datum_vertical']}"
               + (f" · inclui {_br(sobrelev, 2)} m de sobrelevação" if sobrelev else ""))
    par.update(chave_mare=chave_mare, mare=mare, cota=cota)

    st.divider()

    # ---- Camadas ---------------------------------------------------------------
    _rotulo("Área e camadas")
    usar_recorte = st.toggle(
        "Recortar à área de estudo da turma",
        key=_padrao(k("recorte"), cfg["recorte_padrao"] and _limite_ok),
        disabled=not _limite_ok,
        help=("Conta e desenha só o que cai dentro da área de estudo que a turma "
              "desenhou; a conexão com o mar segue resolvida no domínio inteiro "
              "(o recorte é de relato, não de cálculo)." if _limite_ok else
              "`dados_web/limite_turma.geojson` não carregou — rode "
              "`09_limite_turma.py`. O app segue sem recorte."))
    par["usar_recorte"] = bool(usar_recorte and _limite_ok)
    par["ver_exposicao"] = st.toggle("Exposição ao NMRM", key=_padrao(k("exposicao"), True))
    par["mostrar_isoladas"] = st.toggle(
        "Depressões sem conexão", key=_padrao(k("isoladas"), True),
        help="Terreno abaixo da cota SEM caminho até o mar. Os simuladores "
             "online contam isto como inundação; aqui fica em outra cor.")
    par["ver_topo"] = st.toggle(
        "Topografia", key=_padrao(k("topo"), False),
        help="Faixas de elevação do PRÓPRIO relevo que a simulação corta.")
    par["ver_isolinhas"] = st.toggle(
        "Isolinhas (" + " · ".join(f"{v:g}".replace(".", ",")
                                    for v in mapaweb.CONFIG_TOPO["niveis_m"]) + " m)",
        key=_padrao(k("isolinhas"), False),
        help="Guia de leitura suavizado; a cota exata é a do clique.")
    par["ver_cobertura"] = (st.toggle(
        "Cobertura MapBiomas", key=_padrao(k("cobertura"), False),
        help="Camada VISUAL (Coleção 11, 2025): não entra em nenhuma conta.")
        if tem_cobertura else False)
    par["ver_correntes"] = (st.toggle(
        "Correntes oceânicas (CMEMS)", key=_padrao(k("correntes"), False),
        help="Média de 10 anos de correntes (GLORYS12). Camada VISUAL de contexto "
             "oceânico: não entra em nenhuma conta de exposição ao NMRM.")
        if tem_correntes else False)
    par["corr_periodo"], par["corr_nivel"], par["corr_setas"] = "climatologia", 0, True
    if par["ver_correntes"]:
        _cp = config.CONFIG_CORRENTES["periodos"]
        _trimestres = [c for c in _cp if c != "climatologia" and c in D_CORRENTES["periodos"]]
        _tipo = st.segmented_control(
            "Análise", ["Climatologia", "Por trimestre"],
            key=_padrao(k("corr_tipo"), "Climatologia"), width="stretch") or "Climatologia"
        if _tipo == "Por trimestre" and _trimestres:
            par["corr_periodo"] = st.selectbox(
                "Trimestre (média dos 10 anos)", _trimestres,
                format_func=corr.rotulo_periodo, key=_padrao(k("corr_trim"), _trimestres[0]))
        par["corr_nivel"] = st.selectbox(
            "Profundidade", list(range(len(D_CORRENTES["prof_usada"]))),
            format_func=lambda i: corr.rotulo_nivel(D_CORRENTES, i),
            key=_padrao(k("corr_nivel"), 0))
        par["corr_setas"] = st.toggle("Setas de direção", key=_padrao(k("corr_setas"), True))
    par["ver_limite_turma"] = st.toggle(
        "Limite da área de estudo", key=_padrao(k("limite"), cfg["camadas_turma_ligadas"]))
    par["ver_isobatas_turma"] = st.toggle(
        "Isóbatas (20–500 m)", key=_padrao(k("isobatas"), cfg["camadas_turma_ligadas"]))
    par["ver_ucs_turma"] = st.toggle(
        "Unidades de conservação", key=_padrao(k("ucs"), cfg["ucs_ligadas"]),
        help="Vem desligada: o preenchimento das três UCs disputa a leitura da "
             "lâmina d'água justamente no estuário.")

    # ---- Ajustes avançados ------------------------------------------------------
    with st.popover("Ajustes avançados", icon=":material/tune:", width="stretch"):
        _rotulo("Maré meteorológica")
        st.number_input(
            "Sobrelevação meteorológica (m)", 0.0, CONFIG_UI["sobrelevacao_max_m"],
            step=0.05, key=k("sobrelev"),
            help="Storm surge. Deixe 0 para exposição puramente astronômica.")

        _rotulo("Regra hidrológica")
        par["conectividade"] = st.toggle(
            "Exigir conexão hidráulica com o mar", key=_padrao(k("conect"), True),
            help="Desligado = 'bathtub' ingênuo, igual aos simuladores online. "
                 "Ligado = só conta água que tem caminho até o oceano.")
        par["semear_bordas"] = st.toggle(
            "Água pode entrar pelas bordas do recorte", key=_padrao(k("bordas"), True),
            disabled=MODO_WEB,
            help=("Fixado na geração dos dados leves — não editável nesta versão."
                  if MODO_WEB else "Evita confinamento artificial quando o "
                  "recorte corta a planície."))
        # Filtro de RUÍDO do MDE, não de ciência: descarta manchas contíguas
        # menores que isto nas duas classes (inundada e isolada).
        _ha_px = dados["area_pixel_m2"] / 1e4
        par["area_min"] = st.number_input(
            "Área mínima de mancha (ha)", 0.0, 100.0, step=0.5,
            key=_padrao(k("area_min"), 0.0),
            help=(f"0 = não descarta nada. Nesta grade de {dados['res_x']:.0f} m, "
                  f"1 pixel = {_ha_px:.2f} ha."))

        _rotulo("Figura (PNG 300 dpi)")
        par["fundo"] = st.segmented_control(
            "Fundo da figura", ["hillshade", "hipsometrico", "limpo"],
            format_func={"hillshade": "Relevo", "hipsometrico": "Hipsométrico",
                         "limpo": "Sem fundo"}.get,
            key=_padrao(k("fundo"), "hillshade"), width="stretch") or "hillshade"
        par["exagero"] = st.slider("Exagero vertical do relevo", 1, 120,
                                   key=_padrao(k("exagero"),
                                               core.CONFIG_MAPA["exagero_vertical"]))
        par["alpha_agua"] = st.slider("Opacidade da lâmina d'água", 0.2, 1.0,
                                      step=0.02, key=_padrao(k("alpha"), 0.62))
        par["tema_figura"] = "escuro" if st.toggle(
            "Tema escuro na figura", key=_padrao(k("tema"), MODO_WEB),
            help="Muda só o papel da figura; as cores cartográficas são as mesmas. "
                 "Para o relatório impresso, desligue antes de gerar.") else "claro"
        _enq = {"planicie": "Só a planície (onde há MDE)",
                "area_estudo": "Área de estudo inteira"}
        par["enquadramento"] = st.radio(
            "Enquadramento da figura", list(_enq), format_func=_enq.get,
            key=_padrao(k("enq"), "planicie"), disabled=not par["usar_recorte"],
            help="Só com o recorte ligado. Não muda número nenhum, só o que "
                 "entra no quadro.")

        _rotulo("Mapa interativo")
        par["altura_mapa"] = st.slider(
            "Altura do mapa (px)", CONFIG_UI["altura_mapa_min"],
            CONFIG_UI["altura_mapa_max"], step=20,
            key=_padrao(k("altura"), CONFIG_UI["altura_mapa_px"]))
        par["opac_topo"] = st.slider("Opacidade da topografia", 0.1, 1.0, step=0.05,
                                     key=_padrao(k("opac_topo"), CONFIG_UI["opacidade_topo"]),
                                     disabled=not par["ver_topo"])
        par["opac_cob"] = st.slider("Opacidade da cobertura", 0.1, 1.0, step=0.05,
                                    key=_padrao(k("opac_cob"), CONFIG_UI["opacidade_cobertura"]),
                                    disabled=not par["ver_cobertura"])
        par["opac_corr"] = st.slider("Opacidade das correntes", 0.1, 1.0, step=0.05,
                                     key=_padrao(k("opac_corr"),
                                                 corr.CONFIG_CORRENTES_VIZ["opacidade_padrao"]),
                                     disabled=not par["ver_correntes"])
    par["sobrelev"] = sobrelev
    return par


# =============================================================================
# PÁGINA DO SIMULADOR (públicos e turma)
# =============================================================================

def pagina_simulador(p: str) -> None:
    cfg = CONFIG_PERFIS[p]
    _cabecalho(cfg["eyebrow"], cfg["titulo"], cfg["texto"])
    if p == "turma":
        st.markdown('<div class="nmrm-aviso">Valores da disciplina pré-selecionados '
                    '— você pode alterar qualquer um.</div>', unsafe_allow_html=True)

    col_ctl, col_mapa = st.columns(CONFIG_UI["proporcao_colunas"], gap="medium")
    with col_ctl:
        with st.container(border=True):
            par = _controles(p)

    # ---- Processamento ------------------------------------------------------------
    cota = par["cota"]
    core.CONFIG_MAPA["alpha_agua"] = par["alpha_agua"]
    mascaras = fonte.mascara_inundacao_auto(
        core, dados, cota["cota_m"],
        conectividade=par["conectividade"], semear_bordas=par["semear_bordas"],
        area_minima_ha=par["area_min"], mascara_agua=mascara_agua, limiar=limiar)
    # Recorte SÓ depois da conectividade: recortar antes cortaria caminhos de
    # água que entram pela borda. Não inverta essa ordem numa refatoração.
    usar_recorte = par["usar_recorte"]
    recorte = _recorte_de(caminho, usar_recorte)
    est = core.estatisticas_area(mascaras, dados["dem"], dados["area_pixel_m2"],
                                 recorte=recorte)

    st.session_state[CHAVE_ESTADO] = {
        "perfil": p, "nmrm": par["nmrm"], "rotulo_cen": par["rotulo_cen"],
        "chave_mare": par["chave_mare"], "mare": par["mare"], "cota": cota,
        "conectividade": par["conectividade"], "semear_bordas": par["semear_bordas"],
        "usar_recorte": usar_recorte, "tema_figura": par["tema_figura"],
        "exagero": par["exagero"], "altura_mapa": par["altura_mapa"],
    }

    with col_mapa:
        if mascaras.get("saturado_limiar"):
            st.warning(
                f"**Cota pedida ({mascaras['cota_pedida_m']:.2f} m) acima do teto "
                f"pré-computado do raster de limiar ({mascaras['teto_limiar_m']:.2f} m).** "
                "O número que saiu SUBESTIMA a área inundada acima do teto. Reduza "
                "o nível, a maré ou a sobrelevação — ou rode em modo local.", icon="⚠️")

        with st.container(border=True):
            # ---- Cabeçalho do cartão do mapa: cenário + figura sob demanda ------
            c_chip, c_btn = st.columns([0.55, 0.45], vertical_alignment="center")
            with c_chip:
                st.markdown(
                    f'<span class="nmrm-chip">{("+" if cota["cota_m"] >= 0 else "") + _br(cota["cota_m"], 2)} m · '
                    f'{core.NIVEIS_MARE[par["chave_mare"]]["rotulo"].split(" (")[0]}</span>'
                    f'<span class="nmrm-chip-texto">{par["rotulo_cen"]} · '
                    f'{"área de estudo da turma" if usar_recorte else "domínio inteiro"}'
                    f'</span>', unsafe_allow_html=True)
            _figura_sob_demanda(c_btn, p, par, mascaras, recorte, cota)

            _mapa_interativo(p, par, mascaras, recorte, cota)

        # ---- Métricas --------------------------------------------------------------
        m1, m2, m3, m4 = st.columns(4)
        with m1.container(border=True):
            st.metric("Terra na área de estudo" if usar_recorte else "Área emersa atual",
                      f"{_br(est['area_terra_km2'])} km²")
        with m2.container(border=True):
            st.metric("Área inundada", f"{_br(est['area_inundada_km2'])} km²",
                      f"{_br(est['pct_inundada'])}% da área emersa", delta_color="off")
        with m3.container(border=True):
            st.metric("Área remanescente", f"{_br(est['area_remanescente_km2'])} km²")
        with m4.container(border=True):
            st.metric("Sem conexão", f"{_br(est['area_isolada_km2'])} km²",
                      help="Terreno abaixo da cota que NÃO tem caminho hidráulico até "
                           "o mar. Os simuladores online contam isto como inundação.")

        if usar_recorte:
            _terra_dom = float(np.isfinite(dados["dem"]).sum()) * dados["area_pixel_m2"] / 1e6
            st.caption(
                f"Recorte ligado: os km² são a TERRA da área de estudo que o MDE cobre "
                f"({_br(est['area_terra_km2'])} de {_br(_terra_dom)} km² do domínio), "
                "não a extensão do polígono, que é quase toda plataforma continental. "
                "Fica de fora a planície continental a oeste (Grupo Barreiras), que "
                "no domínio inteiro dilui a porcentagem.")

    # ---- Blocos recolhidos, largura total ---------------------------------------
    with st.expander("Como ler este mapa"):
        _legendas_mapa(par, cota)
    with st.expander("Sobre precisão e limitações"):
        st.markdown(LIMITACOES_MD)
    with st.expander("Fontes dos dados"):
        st.markdown(FONTES_MD)

    if cfg["analises_turma"]:
        _secao_turma(par, mascaras, cota)


def _figura_sob_demanda(container, p, par, mascaras, recorte, cota) -> None:
    """
    Botão "Gerar figura" + download. A figura de 300 dpi é a parte mais
    pesada do app (~0,5 GB no pico): só é montada quando pedida, fechada logo
    depois, e o PNG fica guardado enquanto os parâmetros não mudam.
    """
    assinatura = (p, round(cota["cota_m"], 4), par["rotulo_cen"], par["conectividade"],
                  par["semear_bordas"], par["area_min"], par["fundo"], par["exagero"],
                  par["alpha_agua"], par["tema_figura"], par["mostrar_isoladas"],
                  par["usar_recorte"], par["enquadramento"], par["ver_limite_turma"],
                  par["ver_isobatas_turma"], par["ver_ucs_turma"])
    chave = f"nmrm_figura_{p}"
    guardada = st.session_state.get(chave)
    if guardada and guardada["assinatura"] != assinatura:
        st.session_state.pop(chave, None)
        guardada = None

    with container:
        b1, b2 = st.columns(2)
        gerar = b1.button("Gerar figura", icon=":material/image:", width="stretch",
                          key=f"btn_figura_{p}",
                          help="Monta a figura de 300 dpi (UTM, escala, norte, créditos).")
        if gerar:
            with st.spinner("Desenhando a figura de 300 dpi..."):
                subtitulo = (f"{par['rotulo_cen']} · cota {cota['cota_m']:.2f} m · "
                             f"{'com' if par['conectividade'] else 'SEM'} teste de conectividade")
                fig, _ = core.figura_mapa(
                    dados, mascaras, cota, subtitulo=subtitulo,
                    mostrar_isoladas=par["mostrar_isoladas"], fundo=par["fundo"],
                    hs=_hillshade(caminho, par["exagero"]), tema=par["tema_figura"],
                    figsize=CONFIG_UI["figsize"],
                    camadas_turma=_camadas_turma(_DIR_WEB),
                    ver_isobatas_turma=par["ver_isobatas_turma"],
                    ver_ucs_turma=par["ver_ucs_turma"],
                    ver_limite_turma=par["ver_limite_turma"],
                    recorte=recorte, enquadramento=par["enquadramento"])
                guardada = {"assinatura": assinatura,
                            "png": _png(fig, core.CONFIG_MAPA["dpi_export"]),
                            "previa": _png(fig, CONFIG_UI["dpi_previa"])}
                plt.close(fig)
            st.session_state[chave] = guardada
        b2.download_button(
            "Baixar PNG", guardada["png"] if guardada else b"",
            file_name=f"mapa_nmrm_{cota['cota_m']:.2f}m.png", mime="image/png",
            icon=":material/download:", type="primary", width="stretch",
            disabled=guardada is None, key=f"dl_figura_{p}",
            help=None if guardada else "Gere a figura primeiro.")

    if guardada:
        with st.expander("Prévia da figura", expanded=gerar):
            st.image(guardada["previa"], width="stretch")
            if par["tema_figura"] == "escuro":
                st.caption("O PNG sai com fundo escuro. Para o relatório impresso, "
                           "desligue **Tema escuro na figura** em Ajustes avançados.")
            if not MODO_WEB and st.button("Gravar GeoTIFF classificado",
                                          key=f"btn_tif_{p}"):
                saida = str(config.DIR_SAIDAS / f"inundacao_{cota['cota_m']:.2f}m.tif")
                core.exportar_geotiff(mascaras, dados, saida, cota["cota_m"],
                                      recorte=recorte)
                st.success(f"Salvo em `{saida}`.")


def _mapa_interativo(p, par, mascaras, recorte, cota) -> None:
    """Mapa folium com as camadas escolhidas, o ponto consultado e a leitura
    do clique. Lógica idêntica à aba "Mapa interativo" da v2.1."""
    usar_recorte = par["usar_recorte"]
    dados_cob = _carregar_cobertura(caminho_cobertura) if tem_cobertura else None
    chave_ponto = f"{CHAVE_PONTO}_{p}"
    corr_ip = (D_CORRENTES["periodos"].index(par["corr_periodo"])
               if par["ver_correntes"] and par["corr_periodo"] in D_CORRENTES["periodos"] else 0)

    def _leitura_ponto(ponto) -> dict | None:
        """Lê todas as camadas num ponto (lat, lon). Uma função só para o popup
        e as métricas, senão os dois acabariam divergindo."""
        if not ponto:
            return None
        lat, lon = float(ponto[0]), float(ponto[1])
        # Corrente é leitura de CONTEXTO oceânico: vale também fora do recorte
        # (o recorte só governa o que entra na conta de exposição).
        rc = (corr.valor_no_ponto(D_CORRENTES, corr_ip, par["corr_nivel"], lat, lon)
              if par["ver_correntes"] else None)
        # Clique FORA da área de estudo, com recorte ligado, não devolve cota:
        # aquele pixel não entra em conta nenhuma.
        if recorte is not None:
            dentro = mapaweb.valor_no_ponto(recorte.astype("uint8"),
                                            dados["transform"], dados["crs"], lat, lon)
            if not dentro:
                return {"lat": lat, "lon": lon, "fora_do_recorte": True, "corrente": rc}

        z = mapaweb.valor_no_ponto(dados["dem"], dados["transform"], dados["crs"], lat, lon)
        inund = mapaweb.valor_no_ponto(mascaras["inundada"].astype("uint8"),
                                       dados["transform"], dados["crs"], lat, lon)
        isol = mapaweb.valor_no_ponto(mascaras["isolada"].astype("uint8"),
                                      dados["transform"], dados["crs"], lat, lon)
        # No modo web o MDE leve foi achatado em `_clamp_web` — acima disso o
        # valor lido é o teto, não o terreno. -0.005 absorve o arredondamento cm.
        _teto_web = _clamp_web if MODO_WEB else None
        faixa = mapaweb.faixa_da_cota(z, teto_m=_teto_web)
        no_teto = _teto_web is not None and z is not None and z >= _teto_web - 0.005

        if z is None:
            situacao = "fora do terreno (oceano ou sem dado)"
        elif inund:
            situacao = "inundada — conectada ao mar"
        elif isol:
            situacao = "abaixo da cota, SEM conexão"
        else:
            situacao = "acima da cota"

        folga = None if z is None else z - cota["cota_m"]
        if no_teto:
            cota_txt = f"≥ {_teto_web:.2f} m (teto do modo web)"
            folga_txt = f"≥ {_teto_web - cota['cota_m']:.2f} m acima da cota do cenário"
        elif folga is None:
            cota_txt = folga_txt = "—"
        elif folga >= 0:
            cota_txt, folga_txt = f"{z:.2f} m", f"{folga:.2f} m acima da cota do cenário"
        else:
            cota_txt, folga_txt = f"{z:.2f} m", f"{abs(folga):.2f} m abaixo da cota do cenário"

        codigo, classe_nome, cor_classe = None, "—", "#9E9E9E"
        if dados_cob is not None:
            codigo = mapaweb.valor_no_ponto(dados_cob["classes"], dados_cob["transform"],
                                            dados_cob["crs"], lat, lon)
            if codigo in (None, dados_cob["nodata"]):
                codigo, classe_nome = None, "sem classe no MapBiomas"
            else:
                info = cob.classe(int(codigo))
                classe_nome, cor_classe = info["nome"], info["cor"]

        return {"lat": lat, "lon": lon, "cota_m": z, "cota_txt": cota_txt,
                "faixa_txt": "—" if faixa is None else faixa["faixa"],
                "faixa_cor": "#9E9E9E" if faixa is None else faixa["cor"],
                "situacao": situacao, "folga_txt": folga_txt, "codigo": codigo,
                "classe": classe_nome, "classe_cor": cor_classe,
                "alerta_dossel": cob.alerta_dossel(codigo), "corrente": rc}

    def _linhas_corrente(l: dict) -> str:
        """Linhas de corrente do popup/métricas; vazio com a camada desligada."""
        c = l.get("corrente")
        if not par["ver_correntes"] or c is None:
            return ""
        rot = f"{corr.rotulo_periodo(par['corr_periodo'])} · {corr.rotulo_nivel(D_CORRENTES, par['corr_nivel'])}"
        if c.get("terra"):
            txt = "célula de terra no modelo"
        else:
            txt = (f"{c['rapidez']:.2f} m/s para {c['rosa']} ({c['direcao']:.0f}°)"
                   .replace(".", ","))
        return (f'<tr><td style="padding:2px 8px 2px 0;color:#555;white-space:nowrap;">'
                f'Corrente<br><span style="font-size:10px">{rot}</span></td>'
                f'<td style="padding:2px 0;"><b>{txt}</b></td></tr>')

    def _popup_html(l: dict) -> str:
        def _linha(rotulo, valor, cor=None):
            bolinha = (f'<span style="display:inline-block;width:10px;height:10px;'
                       f'border-radius:2px;background:{cor};border:1px solid #6668;'
                       f'margin-right:5px;vertical-align:middle;"></span>' if cor else "")
            return (f'<tr><td style="padding:2px 8px 2px 0;color:#555;white-space:nowrap;">'
                    f'{rotulo}</td><td style="padding:2px 0;"><b>{bolinha}{valor}</b></td></tr>')

        cab = (f'<div style="font-family:system-ui,sans-serif;font-size:12.5px;'
               f'line-height:1.4;min-width:230px;"><div style="font-weight:600;'
               f'margin-bottom:4px;">{l["lat"]:.5f}°, {l["lon"]:.5f}°</div>')
        if l.get("fora_do_recorte"):
            _tab_c = _linhas_corrente(l)
            return (cab + '<div style="padding:5px 6px;background:#EEF1F4;border-left:3px '
                    'solid #8A97A3;font-size:11.5px;color:#33404B;line-height:1.35;">Fora '
                    'da área de estudo da turma. Este ponto não entra em nenhuma conta '
                    'desta análise.</div>'
                    + (f'<table style="border-collapse:collapse;margin-top:4px;">{_tab_c}</table>'
                       if _tab_c else '') + '</div>')
        linhas = [_linha(f"Cota ({core.CONFIG_DEM['datum_vertical']})", l["cota_txt"]),
                  _linha("Faixa", l["faixa_txt"], l["faixa_cor"]),
                  _linha(f"Em {cota['cota_m']:.2f} m", l["situacao"]),
                  _linha("Folga", l["folga_txt"])]
        if dados_cob is not None:
            linhas.append(_linha("Cobertura", l["classe"], l["classe_cor"]))
        _lc = _linhas_corrente(l)
        aviso = ""
        if l["alerta_dossel"]:
            aviso = ('<div style="margin-top:6px;padding:5px 6px;background:#FFF4CE;'
                     'border-left:3px solid #E0A800;font-size:11px;color:#5A4A00;'
                     'line-height:1.35;">Manguezal: a cota aqui inclui dossel residual '
                     'do relevo. Leia como limite superior, não como cota do solo.</div>')
        return (cab + f'<table style="border-collapse:collapse;">{"".join(linhas)}{_lc}</table>'
                f'{aviso}</div>')

    # ---- Camadas -----------------------------------------------------------------
    png_uri = bounds_web = None
    t0 = time.perf_counter()
    if par["ver_exposicao"]:
        cores_overlay = {
            mapaweb.CODIGOS_CLASSE["inundada"]:   core.CONFIG_MAPA["cor_inundado"],
            mapaweb.CODIGOS_CLASSE["agua_atual"]: core.CONFIG_MAPA["cor_oceano"],
        }
        # "Depressões sem conexão" desligado = classe fica transparente.
        if par["mostrar_isoladas"]:
            cores_overlay[mapaweb.CODIGOS_CLASSE["isolada"]] = core.CONFIG_MAPA["cor_isolado"]
        png_uri, bounds_web = _overlay_web(
            caminho, caminho_mascara_agua, caminho_limiar, cota["cota_m"],
            par["conectividade"], par["semear_bordas"], par["area_min"],
            cores_overlay, usar_recorte)
    st.session_state[f"nmrm_t_overlay_{p}"] = (time.perf_counter() - t0) * 1000

    # O enquadramento vem sempre do MDE, não da camada ligada no momento:
    # assim ligar/desligar camada não faz o mapa pular de lugar.
    uri_topo, bounds_topo = _overlay_topo(caminho, usar_recorte)
    mapa_web = folium.Map(location=[(bounds_topo[0][0] + bounds_topo[1][0]) / 2,
                                    (bounds_topo[0][1] + bounds_topo[1][1]) / 2],
                          zoom_start=11, tiles=None, control_scale=True)
    if par["ver_correntes"]:
        # Correntes são oceânicas: enquadra o domínio delas, não a planície.
        mapa_web.fit_bounds(corr.limites_graus(D_CORRENTES))
    elif usar_recorte:
        _bounds_rec = mapaweb.bounds_recorte(recorte, dados["transform"], dados["crs"])
        if _bounds_rec:
            mapa_web.fit_bounds(_bounds_rec)
    _basemaps(mapa_web)

    # Empilhamento: topografia, cobertura, lâmina d'água, isolinhas por cima.
    if par["ver_topo"]:
        folium.raster_layers.ImageOverlay(
            image=uri_topo, bounds=bounds_topo, opacity=par["opac_topo"],
            name="Topografia (hipsométrico)", interactive=False, cross_origin=False,
            zindex=1).add_to(mapa_web)
    if par["ver_cobertura"] and dados_cob is not None:
        uri_cob, bounds_cob, _ = _overlay_cobertura(caminho_cobertura, caminho, usar_recorte)
        if uri_cob:
            folium.raster_layers.ImageOverlay(
                image=uri_cob, bounds=bounds_cob, opacity=par["opac_cob"],
                name=f"Cobertura — {cob.CONFIG_COBERTURA['colecao']} "
                     f"({cob.CONFIG_COBERTURA['ano_referencia']})",
                interactive=False, cross_origin=False, zindex=2).add_to(mapa_web)
    if par["ver_correntes"]:
        _ip, _iz = corr_ip, par["corr_nivel"]
        _rot_corr = (f"{corr.rotulo_periodo(par['corr_periodo'])} · "
                     f"{corr.rotulo_nivel(D_CORRENTES, _iz)}")
        _uri_c, _bounds_c = _corr_overlay(caminho_correntes, _mtime_correntes, _ip, _iz)
        folium.raster_layers.ImageOverlay(
            image=_uri_c, bounds=_bounds_c, opacity=par["opac_corr"],
            name=f"Correntes (m/s) — {_rot_corr}",
            interactive=False, cross_origin=False, zindex=2).add_to(mapa_web)
        if par["corr_setas"]:
            _cfg_v = corr.CONFIG_CORRENTES_VIZ
            folium.GeoJson(
                _corr_setas(caminho_correntes, _mtime_correntes, _ip, _iz),
                name="Setas de corrente",
                style_function=lambda _f, _c=_cfg_v: {
                    "color": _c["seta_cor"], "weight": _c["seta_espessura"], "opacity": 0.9},
                tooltip=folium.GeoJsonTooltip(fields=["rap", "dir"],
                                              aliases=["Rapidez:", "Para (azimute):"],
                                              sticky=True),
            ).add_to(mapa_web)
    if par["ver_exposicao"] and png_uri:
        folium.raster_layers.ImageOverlay(
            image=png_uri, bounds=bounds_web, opacity=core.CONFIG_MAPA["alpha_agua"],
            name=f"Exposição · cota {cota['cota_m']:.2f} m",
            interactive=False, cross_origin=False, zindex=3).add_to(mapa_web)
    if par["ver_isolinhas"]:
        def _estilo_isolinha(feicao):
            destaque = feicao["properties"]["destaque"]
            return {"color": mapaweb.CONFIG_TOPO["cor_isolinha"],
                    "weight": (mapaweb.CONFIG_TOPO["largura_isolinha_destaque"]
                               if destaque else mapaweb.CONFIG_TOPO["largura_isolinha"]),
                    "opacity": 0.95 if destaque else 0.6}
        folium.GeoJson(
            _isolinhas(caminho, usar_recorte), name="Isolinhas (m)",
            style_function=_estilo_isolinha,
            tooltip=folium.GeoJsonTooltip(fields=["rotulo"], aliases=["Cota:"], sticky=True),
        ).add_to(mapa_web)

    # Contexto da turma — vetorial, sempre registrado no LayerControl (o usuário
    # pode ligar direto no mapa, sem rerun). Ordem: isóbatas -> UCs -> limite.
    camadas_turma = _camadas_turma(_DIR_WEB)
    if camadas_turma["isobatas"] is not None:
        _cfg_iso = mapaweb.CONFIG_CAMADAS_TURMA["isobatas"]

        def _estilo_isobata(feicao, _c=_cfg_iso):
            prof = int(round(abs(feicao["properties"].get("prof", 0))))
            return {"color": _c["cores_por_profundidade_m"].get(prof, _c["cor_padrao"]),
                    "weight": _c["espessura_500m"] if prof == 500 else _c["espessura"],
                    "opacity": 0.9}
        fg = folium.FeatureGroup(name="Isóbatas (20–500 m)", show=par["ver_isobatas_turma"])
        folium.GeoJson(camadas_turma["isobatas"], style_function=_estilo_isobata,
                       tooltip=folium.GeoJsonTooltip(fields=["rotulo"],
                                                     aliases=["Profundidade:"], sticky=True),
                       ).add_to(fg)
        fg.add_to(mapa_web)
    if camadas_turma["ucs"] is not None:
        _cfg_uc = mapaweb.CONFIG_CAMADAS_TURMA["ucs"]
        fg = folium.FeatureGroup(name="Unidades de conservação", show=par["ver_ucs_turma"])
        folium.GeoJson(
            camadas_turma["ucs"],
            style_function=lambda _f, _c=_cfg_uc: {
                "color": _c["cor_borda"], "weight": _c["espessura_borda"],
                "fillColor": _c["cor_preenchimento"], "fillOpacity": _c["alpha_preenchimento"]},
            tooltip=folium.GeoJsonTooltip(
                fields=["nome_uc", "categoria", "esfera", "ha_total_fmt"],
                aliases=["Unidade:", "Categoria:", "Esfera:", "Área (ha):"], sticky=True),
        ).add_to(fg)
        fg.add_to(mapa_web)
    if camadas_turma.get("limite") is not None:
        _cfg_lim = mapaweb.CONFIG_CAMADAS_TURMA["limite"]
        fg = folium.FeatureGroup(name="Limite da área de estudo", show=par["ver_limite_turma"])
        folium.GeoJson(
            camadas_turma["limite"],
            style_function=lambda _f, _c=_cfg_lim: {
                "color": _c["cor_borda"], "weight": _c["espessura_borda"],
                "fillOpacity": _c["alpha_preenchimento"]},
            tooltip=folium.GeoJsonTooltip(fields=["nome", "area_km2_fmt"],
                                          aliases=["Limite:", "Extensão (km²):"], sticky=True),
        ).add_to(fg)
        fg.add_to(mapa_web)

    # ---- Ponto consultado ---------------------------------------------------------
    # O popup precisa existir no folium.Map ANTES da renderização, e o clique só
    # chega depois: o clique é guardado, dispara um rerun, e o marcador nasce
    # junto com o mapa na execução seguinte.
    leitura = _leitura_ponto(st.session_state.get(chave_ponto))
    if leitura:
        folium.Marker(
            location=[leitura["lat"], leitura["lon"]],
            tooltip="Ponto consultado — clique em outro lugar para mover",
            popup=folium.Popup(_popup_html(leitura), max_width=330, show=True),
            icon=folium.Icon(color="lightgray", icon_color="#111111",
                             icon="crosshairs", prefix="fa"),
        ).add_to(mapa_web)

    MousePosition(position="bottomleft", separator=" · ", prefix="cursor:",
                  num_digits=5, lat_formatter=_FORMATADOR_COORD,
                  lng_formatter=_FORMATADOR_COORD).add_to(mapa_web)
    folium.LayerControl(collapsed=True).add_to(mapa_web)

    # returned_objects=["last_clicked"]: clique rerroda; mover o mapa, não.
    saida_mapa = st_folium(mapa_web, width=None, height=par["altura_mapa"],
                           returned_objects=["last_clicked"], key=f"mapa_{p}")
    clique = (saida_mapa or {}).get("last_clicked")
    if clique:
        novo = (round(float(clique["lat"]), 6), round(float(clique["lng"]), 6))
        if novo != st.session_state.get(chave_ponto):   # sem isto: rerun infinito
            st.session_state[chave_ponto] = novo
            st.rerun()

    # ---- Leitura pontual -----------------------------------------------------------
    if leitura and leitura.get("fora_do_recorte"):
        st.info(f"Ponto **{leitura['lat']:.5f}, {leitura['lon']:.5f}** está fora da área "
                "de estudo da turma: esse pixel não entra em nenhuma conta. Desligue "
                "**Recortar à área de estudo** para consultar o domínio inteiro.", icon="📍")
    elif leitura:
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Ponto consultado", f"{leitura['lat']:.4f}, {leitura['lon']:.4f}")
        q2.metric(f"Cota ({core.CONFIG_DEM['datum_vertical']})", leitura["cota_txt"],
                  delta=leitura["faixa_txt"], delta_color="off",
                  help="Valor do pixel de 30 m, sem interpolação.")
        q3.metric("Situação nesta cota", leitura["situacao"],
                  delta=leitura["folga_txt"], delta_color="off")
        q4.metric("Cobertura MapBiomas", leitura["classe"],
                  help="Camada visual (Coleção 11, 2025). Não entra em nenhuma conta.")
        if leitura["alerta_dossel"]:
            st.warning("Ponto sobre **manguezal**: a cota aqui carrega dossel residual "
                       "(mediana de 4,31 m contra 1,91 m do apicum). Leia como limite "
                       "superior, não como cota do solo.", icon="⚠️")
    _c = (leitura or {}).get("corrente") if par["ver_correntes"] else None
    if _c is not None:
        c1, c2, c3, c4 = st.columns(4)
        _rot_c = (f"{corr.rotulo_periodo(par['corr_periodo'])} · "
                  f"{corr.rotulo_nivel(D_CORRENTES, par['corr_nivel'])}")
        if _c.get("terra"):
            c1.metric("Corrente", "célula de terra", delta=_rot_c, delta_color="off")
        else:
            c1.metric("Corrente (média de 10 anos)", f"{_br(_c['rapidez'], 2)} m/s",
                      delta=_rot_c, delta_color="off")
            c2.metric("Para onde flui", f"{_c['rosa']} ({_c['direcao']:.0f}°)")
            c3.metric("Componentes u · v", f"{_br(_c['u'], 2)} · {_br(_c['v'], 2)}",
                      help="u = leste (+) / oeste (−); v = norte (+) / sul (−), em m/s.")
            c4.metric("Constância", "—" if _c["constancia"] is None else _br(_c["constancia"], 2),
                      help="|vetor médio| / média da rapidez mensal. Perto de 1: corrente "
                           "estável; perto de 0: meandros e reversões.")
    if leitura:
        if st.button("Limpar ponto consultado", key=f"btn_limpar_{p}"):
            st.session_state.pop(chave_ponto, None)
            st.rerun()
    else:
        st.caption("Clique em qualquer ponto do mapa para ver a cota, a situação "
                   "naquela cota e a cobertura do solo.")


def _legendas_mapa(par, cota) -> None:
    itens = [{"cor": core.CONFIG_MAPA["cor_inundado"], "rotulo": "Inundação conectada ao mar"}]
    if par["mostrar_isoladas"]:
        itens.append({"cor": core.CONFIG_MAPA["cor_isolado"],
                      "rotulo": "Abaixo da cota, sem conexão hidráulica"})
    itens.append({"cor": core.CONFIG_MAPA["cor_oceano"], "rotulo": "Oceano/estuário atual"})
    st.markdown(_legenda_html(itens, f"Exposição — cota {cota['cota_m']:.2f} m"),
                unsafe_allow_html=True)
    if par["ver_correntes"] and tem_correntes:
        st.markdown(corr.legenda_html(
            corr.vmax_nivel(D_CORRENTES, par["corr_nivel"]),
            f"Correntes — {corr.rotulo_periodo(par['corr_periodo'])} · "
            f"{corr.rotulo_nivel(D_CORRENTES, par['corr_nivel'])}"), unsafe_allow_html=True)
        st.caption("Escala de cor fixa por profundidade: a climatologia e os trimestres "
                   "são comparáveis entre si. Mostra o campo MÉDIO (vetor médio de "
                   f"{D_CORRENTES['meta'].get('anos', 10)} anos); a constância (clique) diz o "
                   "quanto ele representa a corrente instantânea.")
    if par["ver_topo"]:
        st.markdown(_legenda_html(
            [{"cor": f["cor"], "rotulo": f["faixa"]}
             for f in mapaweb.faixas_hipsometricas(teto_m=_clamp_web if MODO_WEB else None)],
            f"Topografia — datum {core.CONFIG_DEM['datum_vertical']}"), unsafe_allow_html=True)
    if par["ver_cobertura"] and tem_cobertura:
        _, _, legenda_cob = _overlay_cobertura(caminho_cobertura, caminho, par["usar_recorte"])
        if legenda_cob:
            st.markdown(_legenda_html(
                [{"cor": i["cor"], "rotulo": f"{i['nome']} ({i['pct']:.1f}%)"}
                 for i in legenda_cob],
                f"Cobertura — {cob.CONFIG_COBERTURA['colecao']}, "
                f"{cob.CONFIG_COBERTURA['ano_referencia']}"), unsafe_allow_html=True)
            st.caption(cob.FONTE_COBERTURA["limitacao"])
            st.warning(cob.FONTE_COBERTURA["alerta_mangue"], icon="⚠️")
    st.markdown(
        "- **Azul** é água com caminho até o mar na cota escolhida; **laranja** é "
        "terreno abaixo da cota, mas cercado por terreno mais alto.\n"
        "- A cota total soma o nível do mar, a maré escolhida e a sobrelevação.\n"
        "- Clique no mapa para ler a cota de um ponto; o ícone de camadas, no canto "
        "do mapa, liga e desliga cada camada sem recalcular nada.")


def _secao_turma(par, mascaras, cota) -> None:
    """Análises da disciplina (antiga aba 📚 Turma). Consome a MESMA máscara de
    inundação do mapa — nenhum flood-fill é refeito, só o cruzamento com a
    rasterização de cada UC."""
    usar_recorte = par["usar_recorte"]
    st.markdown('<div class="nmrm-hero" style="margin-top:1.6rem">'
                '<div class="nmrm-eyebrow">Análises da disciplina</div>'
                '<div class="nmrm-titulo" style="font-size:2rem">Exposição por '
                'unidade de conservação</div></div>', unsafe_allow_html=True)
    st.caption(
        "A área de estudo da turma não é o domínio do MDE: o FABDEM não tem dado "
        "sobre a plataforma nem sobre o banco dos Abrolhos. Só a fração de cada UC "
        "que cai sobre terra dentro do recorte do MDE entra nos números abaixo.")

    df_cob_ucs = _cobertura_ucs(caminho, _DIR_WEB, usar_recorte)
    c1, c2 = st.columns(2, gap="medium")
    with c1.container(border=True):
        st.markdown("**Unidades de conservação**")
        if df_cob_ucs.empty:
            st.caption("Camada de UCs indisponível — confira `dados_web/ucs_turma.geojson`.")
        else:
            st.dataframe(df_cob_ucs[["Unidade", "Categoria", "Esfera", "Área (ha)",
                                     "Cobertura pelo MDE"]], width="stretch", hide_index=True)
            st.caption(
                "\"Cobertura pelo MDE\" = fração da área oficial (CNUC) sobre terreno "
                f"válido dentro do recorte. Abaixo de "
                f"{CONFIG_TURMA['limiar_cobertura_minima'] * 100:.0f}% aparece \"fora do "
                "recorte do MDE\" — caso do PARNA Abrolhos e da maior parte da APA.")

    with c2.container(border=True):
        st.markdown(f"**Exposição por UC — {par['rotulo_cen']} · cota {cota['cota_m']:.2f} m**")
        _com_terra = (df_cob_ucs[df_cob_ucs["_fracao"] >= CONFIG_TURMA["limiar_cobertura_minima"]]
                      if not df_cob_ucs.empty else df_cob_ucs)
        if _com_terra.empty:
            st.caption("Nenhuma UC tem terra dentro do recorte do MDE.")
        else:
            _masc_uc = _mascara_ucs(caminho, _DIR_WEB, usar_recorte)
            _a_px = dados["area_pixel_m2"] / 1e6
            linhas = []
            for _, linha in _com_terra.iterrows():
                m_uc = _masc_uc[linha["cd_cnuc"]]["mask"]
                a_inund = float((m_uc & mascaras["inundada"]).sum()) * _a_px
                a_isol = float((m_uc & mascaras["isolada"]).sum()) * _a_px
                a_terra = linha["_area_terra_km2"]
                linhas.append({
                    "Unidade": linha["Unidade"],
                    "Área inundada (km²)": round(a_inund, 2),
                    "Área isolada (km²)": round(a_isol, 2),
                    "% da área emersa da UC": (round(100 * a_inund / a_terra, 1)
                                               if a_terra > 0 else float("nan")),
                })
            st.dataframe(pd.DataFrame(linhas), width="stretch", hide_index=True)

    with st.container(border=True):
        st.markdown("**Matriz dos níveis da turma, por UC**")
        df_matriz_uc = _matriz_niveis_por_uc(
            caminho, caminho_mascara_agua, caminho_limiar, par["mare"],
            par["conectividade"], par["semear_bordas"], _DIR_WEB, usar_recorte)
        if df_matriz_uc.empty:
            st.caption("Nenhuma UC com terra no recorte — nada para cruzar.")
        else:
            st.dataframe(df_matriz_uc, width="stretch", hide_index=True)
            st.download_button(
                "Baixar matriz por UC (CSV)",
                df_matriz_uc.to_csv(index=False).encode("utf-8-sig"),
                file_name="matriz_niveis_turma_por_uc.csv", mime="text/csv",
                icon=":material/download:")

    with st.container(border=True):
        st.markdown("**O que esta ferramenta NÃO diz**")
        st.markdown(
            f"- **Maré de modelo global, não medição.** Os offsets vêm do "
            f"{core.NIVEIS_MARE['FONTE']}, célula de ~3,7 km AO LARGO da barra — a "
            "amplificação e a defasagem dentro dos canais do estuário de Caravelas "
            "não estão representadas. O pedido ao BNDO/CHM segue em aberto.\n"
            f"- **Datum {core.CONFIG_DEM['datum_vertical']} (geoide), não maregráfico "
            "da DHN.** A diferença real para a superfície média do mar é de ordem "
            "decimétrica — comparável ao próprio NMRM projetado para 2050.\n"
            "- **Cenários IPCC AR6 são globais (NMGM)**, não o NMRM local de Caravelas.\n"
            "- **Viés de dossel sobre manguezal.** Sob mangue o relevo mede o topo da "
            "copa, não o solo: a cota sai superestimada em ordem de 3 m. **Área de "
            "manguezal perdida não deve ser lida por cenário** nesta versão.\n"
            "- **Resolução de 30 m.** Um canal de maré mais estreito que isso nunca "
            "vira pixel de água na grade — é limite do dado bruto, não desta ferramenta.")


def _pagina_publica():
    pagina_simulador("livre")


def _pagina_turma():
    pagina_simulador("turma")


# =============================================================================
# PÁGINA PALEOAMBIENTE
# =============================================================================
# RECONSTRUÇÃO redesenhada de Andrade et al. (2003), não simulação. Toda a
# ciência vive em `src/paleo.py`; aqui só a interface. Ver §5 do CLAUDE.md.

def pagina_paleo() -> None:
    estado = _estado_atual()
    _cabecalho("Paleoambiente · Andrade et al. (2003)",
               "Sete estágios da evolução quaternária",
               "Do Pleistoceno ao Holoceno tardio, cada estágio comparado com a terra "
               "emersa de hoje. A evolução foi controlada pelas variações do nível "
               "relativo do mar e pelo crescimento dos recifes de Abrolhos. "
               "<b>Reconstrução redesenhada, não simulação:</b> os polígonos são a "
               "digitalização das Figs. 9 a 15 do artigo, com erro posicional da ordem "
               "de centenas de metros. Compare estágios entre si.")

    ests = paleo.estagios(GJ_PALEO)
    por_id = {e["estagio"]: e for e in ests}
    with st.container(border=True):
        sel = st.segmented_control(
            "Estágio evolutivo — do mais antigo ao mais recente", list(por_id),
            format_func=lambda s: f"{s} · {por_id[s]['idade_rotulo']}",
            key=_padrao(f"{PREFIXO_WIDGET}paleo_estagio", ests[0]["estagio"]),
            width="stretch")
    est = por_id[sel or ests[0]["estagio"]]

    cls_paleo = _paleo_classes(caminho, _DIR_WEB, est["estagio"])
    dentro = _paleo_quadro(caminho, _DIR_WEB)
    stats = paleo.estatisticas_estagio(cls_paleo, dados["area_pixel_m2"], est)

    col_mapa, col_info = st.columns([0.62, 0.38], gap="medium")
    with col_mapa:
        with st.container(border=True):
            c_chip, c_btn = st.columns([0.55, 0.45], vertical_alignment="center")
            c_chip.markdown(f'<span class="nmrm-chip ouro">Estágio {est["estagio"]} × hoje</span>',
                            unsafe_allow_html=True)
            _figura_paleo_sob_demanda(c_btn, est, cls_paleo, stats, dentro, estado)

            uri, bounds = mapaweb.gerar_overlay_web(
                cls_paleo, dados["transform"], dados["crs"], paleo.cores_overlay())
            mapa = folium.Map(location=[(bounds[0][0] + bounds[1][0]) / 2,
                                        (bounds[0][1] + bounds[1][1]) / 2],
                              zoom_start=10, tiles=None, control_scale=True)
            _fit = mapaweb.bounds_recorte(cls_paleo > 0, dados["transform"], dados["crs"])
            if _fit:
                mapa.fit_bounds(_fit)
            _basemaps(mapa)
            folium.raster_layers.ImageOverlay(
                image=uri, bounds=bounds, opacity=paleo.CONFIG_PALEO["alpha_overlay_web"],
                name=f"Estágio {est['estagio']} × hoje", interactive=False,
                cross_origin=False, zindex=2).add_to(mapa)
            folium.GeoJson(
                {"type": "FeatureCollection",
                 "features": [{"type": "Feature", "properties": {},
                               "geometry": est["_geometria"]}]},
                name="Paleolinha de costa",
                style_function=lambda _: {"color": paleo.CONFIG_PALEO["cores"]["contorno"],
                                          "weight": 2, "fillOpacity": 0.0},
            ).add_to(mapa)
            folium.LayerControl(collapsed=True).add_to(mapa)
            # Esta página não lê clique: sem estado de volta, sem rerun no pan.
            st_folium(mapa, width=None, height=estado["altura_mapa"],
                      returned_objects=[], key="mapa_paleo")
            st.markdown(_legenda_html(paleo.itens_legenda(stats),
                                      "Comparação com a costa atual"),
                        unsafe_allow_html=True)

    with col_info:
        with st.container(border=True):
            st.caption(" · ".join(x for x in (
                est.get("periodo"), est.get("idade_rotulo"),
                f"{est.get('figura', '')} de Andrade et al. (2003)") if x))
            st.markdown(f"#### Estágio {est['estagio']} — {est['titulo']}")
            st.markdown(est.get("descricao", ""))
            if est.get("nmrm_obs"):
                st.info(f"**Nível do mar:** {est['nmrm_obs']}", icon=":material/water:")
        a1, a2 = st.columns(2)
        with a1.container(border=True):
            st.metric("Terra no estágio", f"{_br(stats['area_terra_paleo_km2'], 0)} km²")
        with a2.container(border=True):
            st.metric("Terra hoje", f"{_br(stats['area_terra_hoje_km2'], 0)} km²",
                      f"{'+' if stats['variacao_km2'] >= 0 else ''}{_br(stats['variacao_km2'], 0)} km² "
                      f"({'+' if stats['variacao_pct'] >= 0 else ''}{_br(stats['variacao_pct'])}%)",
                      delta_color="off")
        a3, a4 = st.columns(2)
        with a3.container(border=True):
            st.metric("Construída", f"{_br(stats['area_ganho_km2'], 0)} km²",
                      help="Mar no estágio, terra hoje.")
        with a4.container(border=True):
            st.metric("Então terra, hoje água", f"{_br(stats['area_perda_km2'], 0)} km²",
                      help="Inclui a rede de canais de maré e o estuário atuais — não "
                           "é, por si, recuo de linha de costa.")
        st.caption(
            "Áreas contadas em pixel da grade do MDE, dentro do quadro das figuras do "
            "artigo (39°30'–39°00'W × 17°30'–18°00'S). O polígono deste estágio tem "
            f"{stats['area_poligono_km2']:,.0f} km² por geometria esférica contra "
            f"{stats['area_terra_paleo_km2']:,.0f} km² rasterizados a 30 m — a "
            "diferença é discretização.")

    if len(ests) > 1:
        with st.container(border=True):
            st.markdown("#### Todos os estágios")
            tab = _paleo_tabela(caminho, _DIR_WEB)
            if tab:
                st.dataframe(pd.DataFrame([{
                    "Estágio": t["estagio"],
                    "Período": t.get("periodo") or "—",
                    "Idade": t["idade_rotulo"],
                    "NMRM (m)": (f"{t['nmrm_m']:+.1f}"
                                 if isinstance(t["nmrm_m"], (int, float)) else "—"),
                    "Terra no estágio (km²)": round(t["area_terra_paleo_km2"]),
                    "Terra hoje (km²)": round(t["area_terra_hoje_km2"]),
                    "Hoje − estágio (km²)": round(t["variacao_km2"]),
                    "Construída desde então (km²)": round(t["area_ganho_km2"]),
                    "Terra então, água hoje (km²)": round(t["area_perda_km2"]),
                } for t in tab]), hide_index=True, width="stretch")
                st.caption(
                    "\"Hoje\" é sempre o relevo atual (FABDEM); nenhum estágio do artigo é "
                    "a costa atual — o VII é a última fase do modelo, no Holoceno tardio. "
                    "NMRM só aparece onde o artigo dá cota (curva de Salvador). Um erro de "
                    "centenas de metros ao longo de dezenas de km de costa equivale a "
                    "dezenas de km²: diferenças desse tamanho entre estágios vizinhos "
                    "(V, VI, VII) estão dentro do erro de redesenho.")


def _figura_paleo_sob_demanda(container, est, cls_paleo, stats, dentro, estado) -> None:
    assinatura = (est["estagio"], estado["tema_figura"], estado["exagero"])
    chave = "nmrm_figura_paleo"
    guardada = st.session_state.get(chave)
    if guardada and guardada["assinatura"] != assinatura:
        st.session_state.pop(chave, None)
        guardada = None
    with container:
        b1, b2 = st.columns(2)
        gerar = b1.button("Gerar figura", icon=":material/image:", width="stretch",
                          key="btn_figura_paleo")
        if gerar:
            with st.spinner("Desenhando a figura de 300 dpi..."):
                fig, _ = paleo.figura_paleo(
                    core, dados, cls_paleo, est, stats, GJ_PALEO,
                    hs=_hillshade(caminho, estado["exagero"]), tema=estado["tema_figura"],
                    figsize=CONFIG_UI["figsize"], dentro_quadro=dentro)
                guardada = {"assinatura": assinatura,
                            "png": _png(fig, paleo.CONFIG_PALEO["dpi_export"]),
                            "previa": _png(fig, CONFIG_UI["dpi_previa"])}
                plt.close(fig)
            st.session_state[chave] = guardada
        b2.download_button(
            "Baixar PNG", guardada["png"] if guardada else b"",
            file_name=f"paleoambiente_estagio_{est['estagio']}.png", mime="image/png",
            icon=":material/download:", type="primary", width="stretch",
            disabled=guardada is None, key="dl_figura_paleo")
    if guardada:
        with st.expander("Prévia da figura", expanded=gerar):
            st.image(guardada["previa"], width="stretch")


# =============================================================================
# PÁGINA EXPOSIÇÃO E CENÁRIOS (curva + matriz)
# =============================================================================

def pagina_exposicao() -> None:
    estado = _estado_atual()
    _cabecalho("Exposição e cenários", "Quanto a planície responde a cada metro",
               "A curva mostra a área inundada em função do nível do mar; a matriz "
               "cruza cenários, horizontes e níveis da turma. Onde a curva vira para "
               "cima está o limiar em que a planície passa a responder de forma não "
               "linear.")

    _area_opc = {"dominio": "Domínio inteiro", "turma": "Área de estudo da turma"}
    c_sel, c_txt = st.columns([0.4, 0.6], vertical_alignment="center")
    with c_sel:
        area = st.segmented_control(
            "Área analisada", list(_area_opc) if _limite_ok else ["dominio"],
            format_func=_area_opc.get, width="stretch",
            key=_padrao(f"{PREFIXO_WIDGET}expo_area",
                        "turma" if (estado["usar_recorte"] and _limite_ok) else "dominio"))
    usar_recorte = (area or "dominio") == "turma"
    with c_txt:
        st.caption(
            f"Maré **{core.NIVEIS_MARE[estado['chave_mare']]['rotulo']}** · conexão com o "
            f"mar **{'exigida' if estado['conectividade'] else 'ignorada'}** — vêm do "
            f"último cenário simulado ({estado['rotulo_cen']}). Mude no Simulador.")

    pal = core.paleta(estado["tema_figura"])
    nmrm = float(estado["nmrm"])
    topo = nmrm if nmrm > CONFIG_UI["nmrm_max"] else None
    args = (caminho, caminho_mascara_agua, caminho_limiar, estado["mare"],
            estado["conectividade"], estado["semear_bordas"])

    col_c, col_t = st.columns([0.58, 0.42], gap="medium")
    with col_c.container(border=True):
        st.markdown("#### Curva de exposição")
        series = {"Domínio inteiro": (_curva(*args, CONFIG_UI["curva_passo"], topo=topo,
                                             usar_recorte=False), "#1D9BF0")}
        if _limite_ok:
            series["Área de estudo da turma"] = (
                _curva(*args, CONFIG_UI["curva_passo"], topo=topo, usar_recorte=True),
                "#F2A33A")
        fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
        fig.patch.set_facecolor(pal["fundo_figura"])
        ax.set_facecolor(pal["fundo_figura"])
        for nome, (df, cor) in series.items():
            destaque = (nome != "Domínio inteiro") == usar_recorte
            ax.plot(df["NMRM (m)"], df["Área inundada (km²)"], color=cor,
                    lw=2.6 if destaque else 1.6, alpha=1.0 if destaque else 0.6, label=nome)
            if destaque:
                ax.fill_between(df["NMRM (m)"], 0, df["Área inundada (km²)"],
                                color=cor, alpha=0.12)
        for nome_c, prop in core.CENARIOS_AR6.items():
            v = prop[2100]["mediana"]
            ax.axvline(v, color=prop["cor"], ls="--", lw=1.0)
            ax.text(v, ax.get_ylim()[1] * 0.97, f" {nome_c} (NMGM 2100)", rotation=90,
                    va="top", ha="left", fontsize=7.5, color=prop["cor"])
        ax.axvline(nmrm, color="#E9B949", lw=1.6)
        ax.set_xlabel("Nível do mar acima do NM (m)", color=pal["texto"])
        ax.set_ylabel("Área inundada (km²)", color=pal["texto"])
        ax.tick_params(colors=pal["texto_fraco"])
        for s in ax.spines.values():
            s.set_color(pal["borda"])
        ax.grid(alpha=0.25, color=pal["grade"])
        ax.legend(loc="lower right", fontsize=8.5, frameon=False, labelcolor=pal["texto"])
        st.pyplot(fig, width="stretch")
        plt.close(fig)
        st.caption("Linha dourada: o nível do último cenário simulado. Tracejadas: "
                   "medianas 2100 dos cenários AR6 (nível GLOBAL).")
        df_sel = series["Área de estudo da turma" if usar_recorte else "Domínio inteiro"][0]
        st.download_button("Baixar curva (CSV)", df_sel.to_csv(index=False).encode("utf-8-sig"),
                           file_name="curva_exposicao_nmrm.csv", mime="text/csv",
                           icon=":material/download:")

    with col_t.container(border=True):
        st.markdown("#### Matriz de cenários")
        df_tab = _tabela(*args, usar_recorte)
        st.dataframe(df_tab, width="stretch", hide_index=True, height=520)
        st.caption("Cenário × horizonte × percentil (AR6, nível médio GLOBAL) e os "
                   "níveis de sensibilidade da turma, na área escolhida acima.")
        st.download_button("Baixar matriz (CSV)", df_tab.to_csv(index=False).encode("utf-8-sig"),
                           file_name="matriz_cenarios_nmrm.csv", mime="text/csv",
                           icon=":material/download:")


# =============================================================================
# PÁGINA METADADOS
# =============================================================================

def pagina_metadados() -> None:
    estado = _estado_atual()
    cota = estado["cota"]
    _cabecalho("Metadados", "De onde vem cada número",
               "Procedência dos dados, datums e decisões de método — o que a "
               "ferramenta assume e o que ela não resolve.")

    c1, c2 = st.columns(2, gap="medium")
    with c1.container(border=True):
        st.markdown(f"#### Decomposição da cota\n{estado['rotulo_cen']}")
        st.table({k: [f"{v:+.3f} m"] for k, v in cota["parcelas"].items()})
    with c2.container(border=True):
        st.markdown("#### Raster")
        st.json({
            "arquivo": os.path.basename(caminho),
            "dimensoes_px": list(dados["dem"].shape),
            "resolucao_m": [dados["res_x"], dados["res_y"]],
            "crs": dados["crs"].to_string() if dados["crs"] else None,
            "datum_vertical": core.CONFIG_DEM["datum_vertical"],
            "area_pixel_m2": dados["area_pixel_m2"],
        })

    with st.container(border=True):
        st.markdown("#### Como o nível médio entra na conta")
        st.markdown(
            "O nível médio **não foi calculado** por esta ferramenta: ele é herdado do "
            "datum vertical do próprio MDE. O FABDEM é referenciado ao geoide "
            f"**{core.CONFIG_DEM['datum_vertical']}**, e a simulação corta o terreno em "
            "z = 0 m nesse datum — ou seja, assume `nível médio local ≈ geoide`, com "
            f"`OFFSET_GEOIDE_NM_M = {core.OFFSET_GEOIDE_NM_M:.2f} m`.\n\n"
            "Essa igualdade é uma **aproximação**. A diferença real entre geoide e "
            "superfície média do mar é a topografia dinâmica média (MDT) — de ordem "
            "decimétrica no Atlântico Sul tropical, comparável ao próprio NMRM de 2050. "
            "**A maré do TPXO não fecha esse buraco:** ela é referenciada ao nível "
            "médio LOCAL do modelo de maré, não ao geoide. São dois problemas "
            "independentes.")

    with st.container(border=True):
        st.markdown("#### Procedência da maré")
        dm = _mare_tpxo(str(config.DIR_RAIZ / "dados_web" / config.ARQ_MARE_TPXO))
        if dm:
            pt = dm["ponto"]
            st.markdown(
                f"- **Fonte:** {dm['fonte']}\n"
                f"- **Referência vertical:** {dm['referencia_vertical']}\n"
                f"- **Ressalva:** {dm['ressalva']}\n"
                f"- **Ponto usado:** {pt['lon']:.4f}°, {pt['lat']:.4f}° · profundidade "
                f"da célula {pt['profundidade_m']:.1f} m · {pt['dist_do_alvo_km']:.2f} km "
                "do ponto-alvo original\n"
                "- **Reprodutibilidade:** `07_mare_tpxo.py` (versionado; o atlas de "
                "~10 GB roda fora do repositório). Rodado em 22/09/2026.")
            st.dataframe(pd.DataFrame([
                {"Constituinte": n, "Amplitude (m)": i["amplitude_m"],
                 "Fase (°, GMT)": i["fase_graus"]}
                for n, i in dm["constituintes"].items()]), width="stretch", hide_index=True)
        else:
            st.caption(f"`{config.ARQ_MARE_TPXO}` não encontrado em `dados_web/` — rode "
                       "`07_mare_tpxo.py`.")

    with st.container(border=True):
        st.markdown("#### Procedência dos cenários")
        st.markdown(
            "**Os cenários IPCC AR6 desta ferramenta são o nível médio GLOBAL (NMGM)**, "
            "não o relativo local de Caravelas — por isso aparecem rotulados assim no "
            "Simulador.\n\n"
            f"- **Referência:** {core.FONTE_CENARIOS['referencia']}\n"
            f"- **Conferido:** {core.FONTE_CENARIOS['conferido']}\n"
            f"- **A conferir:** {core.FONTE_CENARIOS['a_conferir']}\n"
            f"- **Substituir por:** {core.FONTE_CENARIOS['substituir_por']}")

    with st.container(border=True):
        st.markdown("#### Procedência da cobertura do solo")
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

    with st.container(border=True):
        st.markdown("#### Procedência da topografia exibida")
        st.markdown(
            "A camada hipsométrica e as isolinhas do mapa interativo são geradas **do "
            "próprio FABDEM** — não são tiles de terreno de terceiros (regra 2: em "
            "planície com manguezal o viés de dossel dessas fontes é maior que o sinal "
            "de NMRM simulado).\n\n"
            f"As isolinhas passam por suavização gaussiana "
            f"(sigma = {mapaweb.CONFIG_TOPO['suavizacao_sigma_px']} px), subamostragem "
            f"de {mapaweb.CONFIG_TOPO['subamostragem']}x e Douglas-Peucker de "
            f"{mapaweb.CONFIG_TOPO['tolerancia_simplificacao_m']:.0f} m — por isso são "
            "guia de leitura, não medida. O número que vale é o do clique.")

    with st.container(border=True):
        st.markdown("#### Recorte à área de estudo da turma")
        st.markdown(
            "Com **Recortar à área de estudo** ligado (padrão da página Turma), a "
            "contagem, a figura, o mapa e o GeoTIFF só consideram o que cai dentro de "
            "`limite_turma.geojson`. **O recorte é de relato, não de cálculo:** a "
            "conexão com o mar é resolvida antes, no domínio inteiro do MDE — recortar "
            "antes cortaria caminhos de água que entram pela borda. O limite é a área "
            "de estudo que a turma desenhou no QGIS (isóbata de 500 m + unidades de "
            "conservação): o shapefile é versionado em `dados_web/fonte_limite_turma/` "
            "e `09_limite_turma.py` só o converte. Consequências assumidas: (1) fica de "
            "fora a planície continental a oeste, que o domínio inteiro conta; (2) os "
            "km² são a TERRA da área coberta pelo MDE, não a extensão do polígono.")

    if tem_correntes:
        _m = D_CORRENTES["meta"]
        with st.container(border=True):
            st.markdown("#### Procedência das correntes oceânicas")
            st.markdown(
                f"**Produto:** {_m.get('produto')} — dataset `{_m.get('dataset_id')}`, "
                f"{_m.get('variaveis')}, grade {_m.get('grade')}. **Janela:** "
                f"{_m.get('janela')} ({_m.get('anos')} anos). **Período:** "
                f"{_m.get('ponderacao')}; trimestres JFM, AMJ, JAS e OND "
                f"({_m.get('n_meses_por_periodo', {}).get('JFM', '—')} meses cada, "
                f"{_m.get('n_meses_por_periodo', {}).get('climatologia', '—')} na "
                f"climatologia). **Níveis reais usados:** "
                + ", ".join(corr.rotulo_nivel(D_CORRENTES, i)
                            for i in range(len(D_CORRENTES["prof_usada"]))) + ".\n\n"
                f"**Limitação:** {_m.get('limitacao')} Camada VISUAL de contexto "
                "oceânico: não entra em nenhuma conta de exposição ao NMRM e não é "
                f"recortada pela área de estudo. Gerado em {_m.get('gerado_em')}.")

    with st.container(border=True):
        st.markdown("#### Camadas de contexto da turma")
        st.markdown(
            "Isóbatas e unidades de conservação não são produto deste projeto: são só "
            "desenhadas. A camada `limite_turma` é a área de estudo desenhada pela turma.\n\n"
            "- **Unidades de conservação:** CNUC 07/2026 (ICMBio/MMA).\n"
            "- **Isóbatas:** Batimetria do Brasil CPRM/ANP 2013, derivada do GEBCO 925 m.\n\n"
            "As três vêm em EPSG:4674 e são reprojetadas em tempo de execução para a "
            "grade do MDE (diferença SIRGAS 2000 × WGS84 centimétrica).")

    with st.container(border=True):
        st.markdown("#### Fonte de dados")
        st.caption(FONTE["rotulo"])
        _meta_web = FONTE.get("metadados")
        if _meta_web:
            with st.expander("Diagnóstico do recorte (modo web)"):
                st.json(_meta_web.get("diagnostico_recorte", {}))
            for _obs in _meta_web.get("observacoes", []):
                if "TETO" in _obs or "achatado" in _obs:
                    st.warning(_obs, icon="⚠️")

    with st.container(border=True):
        st.markdown("#### Limitações declaradas")
        st.markdown(LIMITACOES_MD)


# =============================================================================
# NAVEGAÇÃO
# =============================================================================

_paginas = [
    st.Page(_pagina_publica, title="Simulador", icon=":material/waves:",
            url_path="simulador", default=True),
    st.Page(_pagina_turma, title="Turma", icon=":material/school:", url_path="turma"),
]
if tem_paleo:
    _paginas.append(st.Page(pagina_paleo, title="Paleoambiente",
                            icon=":material/history_edu:", url_path="paleoambiente"))
_paginas += [
    st.Page(pagina_exposicao, title="Exposição e cenários",
            icon=":material/show_chart:", url_path="exposicao"),
    st.Page(pagina_metadados, title="Metadados", icon=":material/info:",
            url_path="metadados"),
]
st.navigation(_paginas, position="top").run()
