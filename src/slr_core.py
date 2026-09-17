"""
slr_core.py — Motor de simulação de exposição ao Nível Médio Relativo do Mar (NMRM)
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB — Caravelas (BA)

Módulo SEM interface gráfica. Toda a lógica científica vive aqui.
As interfaces (Streamlit, ipywidgets/Colab, scripts de linha de comando)
importam este módulo e apenas desenham botões.

Entrada esperada: o GeoTIFF produzido por `01_mapa_elevacao.py`
(FABDEM V1-2 mosaicado, recortado, reprojetado para EPSG:31984 @ 30 m,
com oceano mascarado).

Autor: Helio | Assistência: Claude
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import rasterio
import matplotlib
from matplotlib import cm, colors
from matplotlib.colors import LightSource
from scipy import ndimage

# =============================================================================
# 1. PARÂMETROS CENTRALIZADOS
#    Regra do projeto: nenhum limiar numérico hardcodado dentro de função.
# =============================================================================

CONFIG_DEM = {
    "epsg_projetado":  31984,      # SIRGAS 2000 / UTM 24S
    "resolucao_m":     30.0,       # m — resolução alvo do raster reprojetado
    "valor_oceano":    0.0,        # FABDEM codifica oceano como exatamente 0.0
    "tol_oceano":      1e-6,       # tolerância do teste de igualdade com 0.0
    "datum_vertical":  "EGM2008",  # FABDEM é referenciado ao geoide EGM2008
}

# -----------------------------------------------------------------------------
# Cenários IPCC AR6 (WGI, Cap. 9 / Tabela 9.9) — NÍVEL MÉDIO GLOBAL DO MAR.
# Valores em metros, relativos à linha de base 1995–2014.
#
# ATENÇÃO METODOLÓGICA (ver Bloco 4 da Aula 2):
#   NMGM != NMRM. Estes números são o sinal GLOBAL e NÃO incluem
#   movimento vertical da terra, gravitação/rotação (fingerprints) nem
#   variação estérica regional. Devem ser SUBSTITUÍDOS pelos valores
#   locais de Caravelas extraídos do NASA/IPCC AR6 Sea Level Projection Tool
#   (Garner et al., Zenodo 10.5281/zenodo.5914709), grid point mais próximo.
#   Enquanto isso, `PROVISORIO = True` faz a interface exibir aviso.
# -----------------------------------------------------------------------------
CENARIOS_AR6 = {
    "SSP1-2.6": {
        "rotulo":   "SSP1-2.6 (baixas emissões)",
        "cor":      "#2C7BB6",
        2050: {"mediana": 0.19, "p17": 0.16, "p83": 0.25},
        2100: {"mediana": 0.44, "p17": 0.32, "p83": 0.62},
    },
    "SSP2-4.5": {
        "rotulo":   "SSP2-4.5 (emissões intermediárias)",
        "cor":      "#FDAE61",
        2050: {"mediana": 0.20, "p17": 0.17, "p83": 0.26},
        2100: {"mediana": 0.56, "p17": 0.44, "p83": 0.76},
    },
    "SSP5-8.5": {
        "rotulo":   "SSP5-8.5 (altas emissões)",
        "cor":      "#D7191C",
        2050: {"mediana": 0.23, "p17": 0.20, "p83": 0.29},
        2100: {"mediana": 0.77, "p17": 0.63, "p83": 1.01},
    },
    "SSP5-8.5 LC": {
        "rotulo":   "SSP5-8.5 baixa confiança (instabilidade marinha do gelo)",
        "cor":      "#7B0D0D",
        2050: {"mediana": 0.24, "p17": 0.20, "p83": 0.40},
        2100: {"mediana": 0.88, "p17": 0.63, "p83": 1.60},
    },
}

# -----------------------------------------------------------------------------
# Procedência dos números acima — regra 3 do projeto (declarar limitações).
# NADA em CENARIOS_AR6 foi calculado por nós. São valores AVALIADOS pelo IPCC
# no AR6 WGI, Cap. 9 (Fox-Kemper et al. 2021), Tabela 9.9: mediana e faixa
# provável (17–83 %) do NMGM, em metros, relativos à linha de base 1995–2014.
# A ferramenta apenas SOMA esse número à cota e corta o MDE nessa altura.
# -----------------------------------------------------------------------------
FONTE_CENARIOS = {
    "referencia": (
        "IPCC AR6 WGI, Cap. 9 — Ocean, Cryosphere and Sea Level Change "
        "(Fox-Kemper et al. 2021), Tabela 9.9. Nível médio GLOBAL do mar "
        "(NMGM), mediana e faixa provável 17–83 %, base 1995–2014."
    ),
    "conferido": (
        "Conferido contra o Sumário Executivo do Cap. 9 (set/2026): SSP5-8.5 "
        "= 0,23 [0,20–0,29] m em 2050 e 0,77 [0,63–1,01] m em 2100. Bate com "
        "os valores desta tabela."
    ),
    "a_conferir": (
        "SSP1-2.6, SSP2-4.5 e SSP5-8.5 baixa confiança ainda NÃO foram "
        "conferidos linha a linha contra a Tabela 9.9 impressa."
    ),
    "substituir_por": (
        "Valores LOCAIS do grid point de Caravelas no NASA/IPCC AR6 Sea Level "
        "Projection Tool (Garner et al., Zenodo 10.5281/zenodo.5914709). "
        "Os daqui são globais: NMGM, não NMRM."
    ),
}

# Níveis de sensibilidade definidos pela turma (21/08)
NIVEIS_TURMA = [0.5, 1.0, 2.0]

# -----------------------------------------------------------------------------
# Datums de maré em Caravelas — PLACEHOLDERS.
# Preencher com as constantes harmônicas do BNDO/CHM ou, provisoriamente,
# com o Catálogo de Estações Maregráficas Brasileiras (FEMAR), estação Caravelas.
# Enquanto `PROVISORIO` for True, a interface exibe tarja de aviso e os
# offsets ficam em 0.0 (ou seja, a simulação roda no nível médio).
# -----------------------------------------------------------------------------
NIVEIS_MARE = {
    "PROVISORIO": True,
    "NM":   {"rotulo": "Nível médio (NM)",                       "offset_m": 0.00},
    "PM":   {"rotulo": "Preamar média (MHW)",                    "offset_m": 0.00},
    "PMS":  {"rotulo": "Preamar de sizígia (MHWS)",              "offset_m": 0.00},
    "HAT":  {"rotulo": "Maior maré astronômica (HAT)",           "offset_m": 0.00},
}

# -----------------------------------------------------------------------------
# COMO O "NÍVEL MÉDIO" ENTRA NA CONTA — leia antes de citar o número no relatório.
#
# O nível médio NÃO foi calculado por este projeto. Ele é HERDADO do datum
# vertical do próprio MDE: o FABDEM é referenciado ao geoide EGM2008, e a
# simulação corta o terreno em z = 0 m nesse datum. Ou seja, a v1 assume
#
#       nível médio local  ==  geoide EGM2008        (OFFSET_GEOIDE_NM_M = 0)
#
# Essa igualdade é uma APROXIMAÇÃO. A diferença real entre o geoide e a
# superfície média do mar é a topografia dinâmica média (MDT), sustentada por
# correntes, vento e gradientes de densidade. No Atlântico Sul tropical ela é
# de ordem decimétrica — comparável ao próprio NMRM de 2050. Preencher com
# CMEMS/DTU ou com nivelamento geodésico amarrado ao marégrafo.
#
# Consequência prática: a v1 roda "no nível médio" por CONSTRUÇÃO, não por
# cálculo. Nenhuma constante harmônica foi usada. Os offsets de PM/PMS/HAT em
# NIVEIS_MARE seguem em 0.00 com PROVISORIO = True justamente por isso.
# -----------------------------------------------------------------------------
OFFSET_GEOIDE_NM_M = 0.00

CONFIG_INUNDACAO = {
    "conectividade":   True,   # True = só conta água conectada ao mar (hidrologicamente plausível)
    "semear_bordas":   True,   # bordas do domínio também injetam água (evita falso confinamento)
    "conexao_8":       True,   # vizinhança 8 (diagonal) em vez de 4
    "area_minima_ha":  0.0,    # descarta manchas menores que isto (0 = não descarta)

    # -------------------------------------------------------------------------
    # Canais MapBiomas como caminho hidráulico (v1.4).
    #
    # CONCEITO: um pixel de canal (classe 33 — "Rio, Lago e Oceano" — fora da
    # máscara de água) é CAMINHO, não FONTE. Ele deixa a água atravessar (entra
    # no conjunto `candidato` do flood-fill), mas não injeta água sozinho (não
    # entra em `fonte`). A distinção importa porque a classe 33 também cobre
    # lagoas interiores sem ligação com o mar — se virassem fonte, cada uma
    # criaria uma conexão falsa com qualquer depressão vizinha.
    #
    # SALVAGUARDA: só conta como caminho o pixel de canal com cota FABDEM
    # <= caminho_cota_max_m. Sem isso, um rio ou lago no alto do tabuleiro
    # Barreiras poderia religar uma depressão baixa muito distante através de
    # uma classe 33 que não tem nada a ver com o estuário. 6,0 m é o teto dos
    # terraços holocênicos de Andrade et al. (2003) — o mesmo já usado em
    # `config.FAIXAS_ALTIMETRICAS`. Pixel de canal com cota NaN não é caminho.
    # -------------------------------------------------------------------------
    "caminhos_canais":     True,
    "classes_caminho":     [33],   # MapBiomas Col. 11: "Rio, Lago e Oceano"
    "caminho_cota_max_m":  6.0,
}

# -----------------------------------------------------------------------------
# Paletas de tema da figura (v1.2).
#
# REGRA: o tema mexe só no "papel" da figura — fundo, título, eixos, grade,
# créditos. As cores CARTOGRÁFICAS (inundada, isolada, oceano) NÃO mudam:
# elas carregam significado e precisam ser as mesmas na tela e no relatório.
# Pelo mesmo motivo, o que é desenhado DENTRO do mapa (seta norte, barra de
# escala, legenda) fica preto sobre caixa clara nos dois temas — quem dá o
# contraste ali é o terreno, não o tema.
# -----------------------------------------------------------------------------
CONFIG_TEMA = {
    "claro": {
        "fundo_figura":   "#FFFFFF",
        "texto":          "#1A1A1A",
        "texto_fraco":    "#555555",
        "borda":          "#333333",
        "grade":          "#B0B0B0",
        "hillshade_vmin": 0.0,
        "hillshade_vmax": 1.0,
    },
    "escuro": {
        # Preto azulado, na linha do modo "dim" das redes sociais.
        "fundo_figura":   "#0B1220",
        "texto":          "#E7E9EA",
        "texto_fraco":    "#8B98A5",
        "borda":          "#38444D",
        "grade":          "#38444D",
        # Cinza comprimido: sem isto o hillshade vira um continente branco
        # estourado no meio de uma página preta.
        "hillshade_vmin": 0.05,
        "hillshade_vmax": 1.90,
    },
}


def paleta(tema: str = "claro") -> dict:
    """Paleta de 'papel' da figura. Nome desconhecido cai no claro."""
    return CONFIG_TEMA.get(tema, CONFIG_TEMA["claro"])


CONFIG_MAPA = {
    "exagero_vertical": 50,          # planície de Caravelas é extremamente plana
    "azimute_sol":      315,
    "altura_sol":       35,
    "cmap_topo":        "terrain",
    "cor_inundado":     "#1F6FEB",
    "cor_isolado":      "#8E44AD",   # abaixo da cota, porém sem conexão com o mar
    "cor_oceano":       "#0B3D5C",
    "alpha_agua":       0.62,
    "dpi_export":       300,
}


# =============================================================================
# 1.c PRINT DIAGNÓSTICO À PROVA DE CONSOLE LEGADO
# =============================================================================

def _print(msg: str) -> None:
    """
    Substitui `print` em todo o motor.

    No Windows o console roda em cp1252 e estoura UnicodeEncodeError em
    qualquer caractere fora dessa tabela — a seta de "Geoide → NM local", por
    exemplo. Print de diagnóstico não pode derrubar a simulação, então aqui
    ele degrada para '?' em vez de levantar exceção.

    `config.configurar_console()` resolve na origem (stdout em UTF-8); esta
    função é a rede de segurança para quem importar o motor sem passar pelo
    config — notebook, teste, outro projeto.
    """
    try:
        print(msg)
    except UnicodeEncodeError:
        codificacao = getattr(sys.stdout, "encoding", None) or "ascii"
        print(msg.encode(codificacao, errors="replace")
                 .decode(codificacao, errors="replace"))


# =============================================================================
# 2. LEITURA DO MDE
# =============================================================================

def carregar_dem(caminho: str) -> dict:
    """
    Lê o GeoTIFF de elevação gerado por `01_mapa_elevacao.py`.

    Retorna dicionário com:
        dem          : ndarray float32, np.nan onde não há terreno válido
        mask_oceano  : ndarray bool, True nos pixels de oceano
        transform, crs, res_x, res_y, area_pixel_m2, perfil
    """
    if not os.path.exists(caminho):
        raise FileNotFoundError(f"MDE não encontrado: {caminho}")

    with rasterio.open(caminho) as src:
        dem = src.read(1).astype("float32")
        perfil = src.profile.copy()
        transform = src.transform
        crs = src.crs
        nodata = src.nodata

    # nodata -> NaN
    if nodata is not None and not np.isnan(nodata):
        dem[dem == nodata] = np.nan

    # Oceano do FABDEM: exatamente 0.0 (regra confirmada no script 01)
    mask_oceano = np.isclose(
        dem, CONFIG_DEM["valor_oceano"], atol=CONFIG_DEM["tol_oceano"], equal_nan=False
    )
    dem[mask_oceano] = np.nan

    res_x, res_y = abs(transform.a), abs(transform.e)
    area_pixel = res_x * res_y

    n_terra = int(np.isfinite(dem).sum())
    _print(f"[DEM] {os.path.basename(caminho)} | {dem.shape[0]}x{dem.shape[1]} px "
          f"| res={res_x:.1f}x{res_y:.1f} m | CRS={crs.to_string() if crs else 'indefinido'}")
    _print(f"[DEM] terra={n_terra} px ({n_terra * area_pixel / 1e6:.1f} km²) | "
          f"oceano={int(mask_oceano.sum())} px | "
          f"z: min={np.nanmin(dem):.2f} m | mediana={np.nanmedian(dem):.2f} m | "
          f"max={np.nanmax(dem):.2f} m")

    if crs is not None and crs.to_epsg() != CONFIG_DEM["epsg_projetado"]:
        _print(f"[AVISO] CRS != EPSG:{CONFIG_DEM['epsg_projetado']}. "
              f"Áreas em km² podem estar distorcidas.")

    return {
        "dem": dem,
        "mask_oceano": mask_oceano,
        "transform": transform,
        "crs": crs,
        "res_x": res_x,
        "res_y": res_y,
        "area_pixel_m2": area_pixel,
        "perfil": perfil,
        "caminho": caminho,
    }


def carregar_mascara_agua(caminho: str) -> np.ndarray | None:
    """
    Lê a máscara de água exportada por `01_mapa_elevacao.py`
    (1=água/oceano/estuário na mesma grade do MDE, 0=terra).

    Retorna None se o arquivo não existir. Quem chama decide como cair para
    o comportamento antigo em `mascara_inundacao` (mask_oceano recomputado
    do MDE, que após o round-trip por nodata só reconhece água que ainda
    seja 0.0 exato no array — ou seja, tipicamente nenhuma).
    """
    if not os.path.exists(caminho):
        return None
    with rasterio.open(caminho) as src:
        mascara = src.read(1).astype(bool)
    _print(f"[MASCARA_AGUA] {os.path.basename(caminho)} | {int(mascara.sum())} px de água")
    return mascara


def carregar_mascara_margem(caminho: str) -> np.ndarray | None:
    """
    Lê a máscara de MARGEM d'água exportada por `01_mapa_elevacao.py`
    (v1.4b): `agua_conexao & ~agua_area` — pixel que fica como TERRA na área
    (o MDE preserva a cota real) mas tem água real suficiente para conduzir a
    conexão hidráulica. Soma-se ao caminho por canal MapBiomas em
    `mascara_caminho()`/`mascara_inundacao()`, com as mesmas regras (conduz,
    nunca é fonte) — mas SEM a salvaguarda de cota do canal, porque aqui é
    água real medida no próprio FABDEM, não uma classe de cobertura que pode
    estar longe do mar.

    Retorna None se o arquivo não existir (camada opcional).
    """
    if not os.path.exists(caminho):
        return None
    with rasterio.open(caminho) as src:
        mascara = src.read(1).astype(bool)
    _print(f"[MASCARA_MARGEM] {os.path.basename(caminho)} | {int(mascara.sum())} px de margem")
    return mascara


# =============================================================================
# 3. COMPOSIÇÃO DA COTA DE INUNDAÇÃO
# =============================================================================

def cota_limiar(nmrm_m: float,
                mare_m: float = 0.0,
                offset_geoide_m: float = OFFSET_GEOIDE_NM_M,
                sobrelevacao_m: float = 0.0) -> dict:
    """
    Empilha as parcelas que definem a cota d'água, no mesmo datum do MDE.

        cota = NMRM + maré + (NM - geoide) + sobrelevação meteorológica

    Retorna dicionário com a cota final e a decomposição, para citar na legenda.
    """
    cota = float(nmrm_m) + float(mare_m) + float(offset_geoide_m) + float(sobrelevacao_m)
    parcelas = {
        "NMRM (cenário)":         float(nmrm_m),
        "Maré (datum)":           float(mare_m),
        "Geoide → NM local":      float(offset_geoide_m),
        "Sobrelevação":           float(sobrelevacao_m),
        "COTA TOTAL":             cota,
    }
    _print("[COTA] " + " + ".join(
        f"{k}={v:+.2f}" for k, v in parcelas.items() if k != "COTA TOTAL"
    ) + f" => {cota:.2f} m")
    return {"cota_m": cota, "parcelas": parcelas}


# =============================================================================
# 4. MÁSCARA DE INUNDAÇÃO (bathtub simples vs. hidrologicamente conectada)
# =============================================================================

def mascara_caminho(dem: np.ndarray,
                    mascara_agua: np.ndarray,
                    cobertura: np.ndarray = None,
                    classes: list = None,
                    cota_max_m: float = None) -> np.ndarray | None:
    """
    Pixels de canal do MapBiomas (fora da máscara de água) que servem de
    CAMINHO hidráulico — ver o conceito completo em
    `CONFIG_INUNDACAO["caminhos_canais"]`: caminho ≠ fonte, e só conta até
    `caminho_cota_max_m` (salvaguarda contra religar depressões distantes
    através de um lago/rio no alto do tabuleiro Barreiras).

    `cobertura` precisa estar na MESMA grade do `dem` (mesmo shape) — nunca
    reamostrada aqui em silêncio. Devolve None se `cobertura` for None (a
    camada é opcional; a simulação segue sem canais).
    """
    if cobertura is None:
        _print("[CAMINHO] cobertura ausente — conectividade sem canais")
        return None

    if cobertura.shape != dem.shape:
        raise ValueError(
            f"Cobertura {cobertura.shape} não tem o mesmo shape do MDE {dem.shape}. "
            "Rode 04_prepara_cobertura.py para gerar o recorte alinhado à grade "
            "do MDE — cobertura nunca deve ser reamostrada em silêncio aqui."
        )

    cfg = CONFIG_INUNDACAO
    classes = cfg["classes_caminho"] if classes is None else classes
    cota_max_m = cfg["caminho_cota_max_m"] if cota_max_m is None else cota_max_m

    caminho = (np.isin(cobertura, classes)
              & ~mascara_agua.astype(bool)
              & np.isfinite(dem)
              & (dem <= cota_max_m))
    _print(f"[CAMINHO] classes={classes} | cota_max={cota_max_m:.1f} m | "
          f"{int(caminho.sum())} px de caminho")
    return caminho


def mascara_inundacao(dem: np.ndarray,
                      mask_oceano: np.ndarray,
                      cota_m: float,
                      conectividade: bool = None,
                      semear_bordas: bool = None,
                      conexao_8: bool = None,
                      area_pixel_m2: float = None,
                      area_minima_ha: float = None,
                      mascara_agua: np.ndarray = None,
                      mascara_caminho: np.ndarray = None) -> dict:
    """
    Separa o terreno abaixo da cota em duas classes fisicamente distintas:

        inundada : conectada ao oceano (ou à borda do domínio) → água chega
        isolada  : abaixo da cota, mas sem caminho hidráulico → depressão fechada

    Esta separação é justamente o que os simuladores online NÃO fazem
    (ver FAQ do runcell: "why do some inland areas appear flooded?").

    Conectividade via `scipy.ndimage.label`, mesma lógica usada na detecção
    de núcleos de corrente do Proj 26.05.

    `mascara_agua`: máscara binária (1=água) exportada por
    `01_mapa_elevacao.py`, na mesma grade do `dem`. É a fonte de água
    preferencial: o oceano/estuário entra no PRÓPRIO conjunto rotulado
    (não só como vizinho externo), para que a água propague através de
    canais e não só toque a borda de manchas de terra isoladas. Necessária
    porque `mask_oceano` (recomputado do MDE via dem==0.0) já não enxerga
    água nenhuma depois que `01_mapa_elevacao.py` grava esses pixels como
    nodata — indistinguível de "fora do bbox, sem tile". Se `mascara_agua`
    não for passada, cai no método antigo com `mask_oceano` (aviso impresso).

    `mascara_caminho`: máscara de canais MapBiomas (ver `mascara_caminho()` /
    `CONFIG_INUNDACAO["caminhos_canais"]`). Entra em `candidato` — a água
    atravessa por ela — mas NUNCA em `fonte`: um canal conduz, não injeta
    água sozinho. Se `caminhos_canais` estiver desligado ou esta máscara for
    None, o resultado é IDÊNTICO ao comportamento anterior à v1.4.
    """
    cfg = CONFIG_INUNDACAO
    conectividade = cfg["conectividade"] if conectividade is None else conectividade
    semear_bordas = cfg["semear_bordas"] if semear_bordas is None else semear_bordas
    conexao_8 = cfg["conexao_8"] if conexao_8 is None else conexao_8
    area_minima_ha = cfg["area_minima_ha"] if area_minima_ha is None else area_minima_ha
    usar_canais = bool(cfg["caminhos_canais"]) and (mascara_caminho is not None)

    valido = np.isfinite(dem)
    abaixo = valido & (dem <= cota_m)

    if not conectividade:
        inundada = abaixo
        isolada = np.zeros_like(abaixo)
        _print(f"[MASCARA] modo=bathtub | cota={cota_m:.2f} m | "
              f"abaixo={int(abaixo.sum())} px (sem teste de conectividade)")
        return _empacota_mascaras(inundada, isolada, abaixo, area_pixel_m2)

    estrutura = np.ones((3, 3), dtype=bool) if conexao_8 else ndimage.generate_binary_structure(2, 1)

    usa_mascara_agua = mascara_agua is not None
    if usa_mascara_agua:
        agua = mascara_agua.astype(bool)
    else:
        agua = mask_oceano
        _print("[MASCARA] aviso: mascara_agua ausente, caindo para mask_oceano "
              "recomputado do MDE (dem==0.0) — SUBESTIMA a conectividade real, "
              "pois o oceano já vira nodata no MDE_PROCESSADO. Rode "
              "01_mapa_elevacao.py de novo para gerar caravelas_mascara_agua_*.tif.")

    # A água propaga pelos próprios pixels de água: eles entram no conjunto
    # rotulado junto com o terreno abaixo da cota, não só como "fonte"
    # externa. Sem isso, dois pedaços de terra em lados opostos de um canal
    # nunca caem no mesmo componente conexo, mesmo ambos estando molhados.
    candidato = abaixo | agua

    # Canal MapBiomas: entra em `candidato` (conduz), nunca em `fonte`
    # (não injeta água sozinho) — ver docstring e CONFIG_INUNDACAO.
    n_px_caminho = 0
    if usar_canais:
        caminho = mascara_caminho.astype(bool)
        candidato = candidato | caminho
        n_px_caminho = int(caminho.sum())

    # Água pode entrar pela água real e, opcionalmente, pelas bordas do recorte
    fonte = agua.copy()
    if semear_bordas:
        borda = np.zeros_like(fonte)
        borda[0, :] = borda[-1, :] = True
        borda[:, 0] = borda[:, -1] = True
        fonte |= borda

    # Rotula terreno abaixo da cota + água, com conectividade 8
    rotulos, n_rot = ndimage.label(candidato, structure=estrutura)

    # Um componente é "conectado ao mar" se contém pelo menos um pixel de
    # água (a dilatação só serve para alcançar componentes que apenas
    # tocam a borda do recorte sem ela própria estar abaixo da cota).
    fonte_dilatada = ndimage.binary_dilation(fonte, structure=estrutura)
    rot_conectados = np.unique(rotulos[fonte_dilatada & (rotulos > 0)])
    rot_conectados = rot_conectados[rot_conectados > 0]

    # Tabela de consulta em vez de np.isin: O(n) direto, ~6x mais rápido
    # quando o MDE gera milhões de manchas (ver benchmark no README).
    lut = np.zeros(n_rot + 1, dtype=bool)
    lut[rot_conectados] = True
    conectada = lut[rotulos]
    isolada = abaixo & ~conectada
    # "abaixo" já exclui os pixels que eram água (dem=NaN ali), então
    # "inundada" nunca reconta o que já era mar — só o que a água alcançou.
    inundada = abaixo & conectada

    # Filtro opcional de área mínima (remove pixels-ruído do MDE)
    if area_minima_ha > 0 and area_pixel_m2:
        n_min = int(np.ceil(area_minima_ha * 1e4 / area_pixel_m2))
        inundada = _remove_manchas_pequenas(inundada, estrutura, n_min)
        isolada = _remove_manchas_pequenas(isolada, estrutura, n_min)

    _txt_canais = f"canais=sim ({n_px_caminho} px de caminho)" if usar_canais else "canais=nao"
    _print(f"[MASCARA] modo=conectado ({'mascara_agua' if usa_mascara_agua else 'mask_oceano (fallback)'}) "
          f"| {_txt_canais} | cota={cota_m:.2f} m | manchas={n_rot} | "
          f"conectadas={len(rot_conectados)} | inundada={int(inundada.sum())} px | "
          f"isolada={int(isolada.sum())} px")

    return _empacota_mascaras(inundada, isolada, abaixo, area_pixel_m2)


def _remove_manchas_pequenas(mask: np.ndarray, estrutura, n_min: int) -> np.ndarray:
    if n_min <= 1:
        return mask
    rot, n = ndimage.label(mask, structure=estrutura)
    if n == 0:
        return mask
    tamanhos = np.bincount(rot.ravel(), minlength=n + 1)
    lut = tamanhos >= n_min
    lut[0] = False
    return lut[rot]


def _empacota_mascaras(inundada, isolada, abaixo, area_pixel_m2):
    return {
        "inundada": inundada,
        "isolada": isolada,
        "abaixo": abaixo,
        "area_pixel_m2": area_pixel_m2,
    }


# =============================================================================
# 5. ESTATÍSTICAS E TABELAS
# =============================================================================

def estatisticas_area(mascaras: dict, dem: np.ndarray, area_pixel_m2: float) -> dict:
    """Converte contagem de pixels em km² e percentuais da área emersa atual."""
    a = area_pixel_m2 / 1e6  # km² por pixel
    area_terra = float(np.isfinite(dem).sum()) * a
    area_inund = float(mascaras["inundada"].sum()) * a
    area_isol = float(mascaras["isolada"].sum()) * a
    area_bath = float(mascaras["abaixo"].sum()) * a

    est = {
        "area_terra_km2":        area_terra,
        "area_inundada_km2":     area_inund,
        "area_isolada_km2":      area_isol,
        "area_bathtub_km2":      area_bath,
        "area_remanescente_km2": area_terra - area_inund,
        "pct_inundada":          100.0 * area_inund / area_terra if area_terra else np.nan,
        "pct_isolada":           100.0 * area_isol / area_terra if area_terra else np.nan,
        "superestimativa_bathtub_km2": area_bath - area_inund,
    }
    _print(f"[AREA] terra={area_terra:.1f} km² | inundada={area_inund:.1f} km² "
          f"({est['pct_inundada']:.1f}%) | isolada={area_isol:.1f} km² | "
          f"bathtub ingênuo superestima em {est['superestimativa_bathtub_km2']:.1f} km²")
    return est


def tabela_cenarios(dados_dem: dict,
                    cenarios: list = None,
                    horizontes: list = (2050, 2100),
                    percentis: list = ("mediana", "p83"),
                    mare_m: float = 0.0,
                    conectividade: bool = True,
                    mascara_agua: np.ndarray = None,
                    mascara_caminho: np.ndarray = None) -> pd.DataFrame:
    """
    Roda a simulação para a matriz cenário × horizonte × percentil e
    devolve a tabela pronta para o relatório.
    """
    cenarios = list(CENARIOS_AR6.keys()) if cenarios is None else cenarios
    linhas = []

    for nome in cenarios:
        for ano in horizontes:
            for p in percentis:
                nmrm = CENARIOS_AR6[nome][ano][p]
                c = cota_limiar(nmrm, mare_m=mare_m)
                m = mascara_inundacao(
                    dados_dem["dem"], dados_dem["mask_oceano"], c["cota_m"],
                    conectividade=conectividade,
                    area_pixel_m2=dados_dem["area_pixel_m2"],
                    mascara_agua=mascara_agua,
                    mascara_caminho=mascara_caminho,
                )
                e = estatisticas_area(m, dados_dem["dem"], dados_dem["area_pixel_m2"])
                linhas.append({
                    "Cenário": nome, "Horizonte": str(ano), "Percentil": p,
                    "NMRM (m)": nmrm, "Cota total (m)": round(c["cota_m"], 2),
                    "Área inundada (km²)": round(e["area_inundada_km2"], 2),
                    "% da área emersa": round(e["pct_inundada"], 2),
                    "Depressões isoladas (km²)": round(e["area_isolada_km2"], 2),
                })

    # Níveis de sensibilidade da turma
    for nivel in NIVEIS_TURMA:
        c = cota_limiar(nivel, mare_m=mare_m)
        m = mascara_inundacao(dados_dem["dem"], dados_dem["mask_oceano"], c["cota_m"],
                              conectividade=conectividade,
                              area_pixel_m2=dados_dem["area_pixel_m2"],
                              mascara_agua=mascara_agua,
                              mascara_caminho=mascara_caminho)
        e = estatisticas_area(m, dados_dem["dem"], dados_dem["area_pixel_m2"])
        linhas.append({
            "Cenário": "Sensibilidade (turma)", "Horizonte": "—", "Percentil": "—",
            "NMRM (m)": nivel, "Cota total (m)": round(c["cota_m"], 2),
            "Área inundada (km²)": round(e["area_inundada_km2"], 2),
            "% da área emersa": round(e["pct_inundada"], 2),
            "Depressões isoladas (km²)": round(e["area_isolada_km2"], 2),
        })

    return pd.DataFrame(linhas)


def curva_exposicao(dados_dem: dict,
                    cotas: np.ndarray = None,
                    mare_m: float = 0.0,
                    conectividade: bool = True,
                    mascara_agua: np.ndarray = None,
                    mascara_caminho: np.ndarray = None) -> pd.DataFrame:
    """
    Curva contínua área inundada × NMRM — a "curva hipsométrica efetiva".
    É o gráfico que transforma três mapas soltos em uma leitura de sensibilidade.
    """
    cotas = np.arange(0.0, 3.01, 0.10) if cotas is None else np.asarray(cotas)
    reg = []
    for nmrm in cotas:
        c = cota_limiar(float(nmrm), mare_m=mare_m)
        m = mascara_inundacao(dados_dem["dem"], dados_dem["mask_oceano"], c["cota_m"],
                              conectividade=conectividade,
                              area_pixel_m2=dados_dem["area_pixel_m2"],
                              mascara_agua=mascara_agua,
                              mascara_caminho=mascara_caminho)
        e = estatisticas_area(m, dados_dem["dem"], dados_dem["area_pixel_m2"])
        reg.append({"NMRM (m)": round(float(nmrm), 2),
                    "Cota (m)": round(c["cota_m"], 2),
                    "Área inundada (km²)": e["area_inundada_km2"],
                    "% da área emersa": e["pct_inundada"]})
    return pd.DataFrame(reg)


# =============================================================================
# 6. EXPORTAÇÃO
# =============================================================================

def _carimbo() -> str:
    return datetime.now().strftime("%Y%m%d")


def exportar_geotiff(mascaras: dict, dados_dem: dict, caminho_saida: str,
                     cota_m: float) -> str:
    """
    Grava raster classificado (0=terra, 1=inundada, 2=depressão isolada,
    3=oceano atual) em GeoTIFF, pronto para o QGIS e para o cruzamento
    com MapBiomas na Parte 2.
    """
    classes = np.zeros(dados_dem["dem"].shape, dtype="uint8")
    classes[np.isfinite(dados_dem["dem"])] = 0
    classes[mascaras["isolada"]] = 2
    classes[mascaras["inundada"]] = 1
    classes[dados_dem["mask_oceano"]] = 3

    perfil = dados_dem["perfil"].copy()
    perfil.update(dtype="uint8", count=1, nodata=255, compress="lzw")

    os.makedirs(os.path.dirname(caminho_saida) or ".", exist_ok=True)
    with rasterio.open(caminho_saida, "w", **perfil) as dst:
        dst.write(classes, 1)
        dst.update_tags(
            cota_m=f"{cota_m:.3f}",
            datum_vertical=CONFIG_DEM["datum_vertical"],
            fonte_mde="FABDEM V1-2 (Univ. Bristol)",
            classes="0=terra 1=inundada 2=depressao_isolada 3=oceano_atual",
            gerado_em=datetime.now().isoformat(timespec="seconds"),
        )
    _print(f"[EXPORT] GeoTIFF salvo: {caminho_saida}")
    return caminho_saida


def exportar_tabela(df: pd.DataFrame, prefixo: str, pasta: str = "saidas") -> str:
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, f"{prefixo}_{_carimbo()}.csv")
    df.to_csv(caminho, index=False, encoding="utf-8-sig")
    _print(f"[EXPORT] CSV salvo: {caminho}")
    return caminho


# =============================================================================
# 7. CARTOGRAFIA
# =============================================================================

def hillshade(dem: np.ndarray, res_m: float, exagero: int = None,
              azimute: int = None, altura: int = None) -> np.ndarray:
    """Sombreamento com exagero vertical — indispensável na planície de Caravelas."""
    exagero = CONFIG_MAPA["exagero_vertical"] if exagero is None else exagero
    azimute = CONFIG_MAPA["azimute_sol"] if azimute is None else azimute
    altura = CONFIG_MAPA["altura_sol"] if altura is None else altura

    z = np.where(np.isfinite(dem), dem, 0.0)
    ls = LightSource(azdeg=azimute, altdeg=altura)
    return ls.hillshade(z, vert_exag=exagero, dx=res_m, dy=res_m)


def _barra_escala(ax, transform, largura_px, comprimento_km=5):
    """Barra de escala simples em coordenadas de pixel."""
    res = abs(transform.a)
    n_px = comprimento_km * 1000 / res
    x0 = largura_px * 0.06
    y0 = ax.get_ylim()[0] * 0.94 if ax.get_ylim()[0] > ax.get_ylim()[1] else ax.get_ylim()[1] * 0.94
    ax.plot([x0, x0 + n_px], [y0, y0], color="k", lw=3, solid_capstyle="butt", zorder=10)
    ax.text(x0 + n_px / 2, y0, f"{comprimento_km} km", ha="center", va="bottom",
            fontsize=8, zorder=10,
            bbox=dict(fc="white", ec="none", alpha=0.75, pad=1.5))


def figura_mapa(dados_dem: dict, mascaras: dict, cota: dict,
                titulo: str = "Exposição ao NMRM — Caravelas (BA)",
                subtitulo: str = "",
                mostrar_isoladas: bool = True,
                fundo: str = "hipsometrico",
                hs: np.ndarray = None,
                tema: str = "claro",
                figsize=(11, 9)):
    """
    Monta a figura de relatório: hillshade + hipsometria + lâmina d'água,
    com legenda, barra de escala, seta norte e créditos de fonte.

    `fundo`: "hipsometrico" | "hillshade" | "limpo"
    `tema`:  "claro" | "escuro" — muda só o papel da figura (ver CONFIG_TEMA).
    `hs`: sombreamento pré-calculado (evita recomputar a cada movimento
          do slider na interface; use `hillshade()` uma única vez).

    Retorna (fig, ax) — quem chamou decide se salva ou exibe.
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    dem = dados_dem["dem"]
    res = dados_dem["res_x"]
    hs = hillshade(dem, res) if hs is None else hs

    pal = paleta(tema)

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    fig.patch.set_facecolor(pal["fundo_figura"])
    ax.set_facecolor(CONFIG_MAPA["cor_oceano"])

    if fundo == "hipsometrico":
        vmax = float(np.nanpercentile(dem, 99.5))
        norm = colors.Normalize(vmin=0, vmax=max(vmax, 1.0))
        cmap_topo = matplotlib.colormaps[CONFIG_MAPA["cmap_topo"]]
        rgb = cmap_topo(norm(np.nan_to_num(dem)))
        rgb[..., :3] *= (0.35 + 0.65 * hs)[..., None]
        rgb[..., 3] = np.isfinite(dem).astype(float)
        ax.imshow(rgb, interpolation="nearest")
        mapa_cores = cm.ScalarMappable(norm=norm, cmap=CONFIG_MAPA["cmap_topo"])
        cb = fig.colorbar(mapa_cores, ax=ax, shrink=0.62, pad=0.01)
        cb.set_label(f"Elevação (m, {CONFIG_DEM['datum_vertical']})", fontsize=9,
                     color=pal["texto"])
        cb.ax.tick_params(colors=pal["texto_fraco"])
        cb.outline.set_edgecolor(pal["borda"])
    elif fundo == "hillshade":
        ax.imshow(np.where(np.isfinite(dem), hs, np.nan), cmap="gray",
                  vmin=pal["hillshade_vmin"], vmax=pal["hillshade_vmax"],
                  interpolation="nearest")

    # Lâmina d'água conectada
    ax.imshow(np.ma.masked_where(~mascaras["inundada"], mascaras["inundada"]),
              cmap=colors.ListedColormap([CONFIG_MAPA["cor_inundado"]]),
              alpha=CONFIG_MAPA["alpha_agua"], interpolation="nearest")

    if mostrar_isoladas and mascaras["isolada"].any():
        ax.imshow(np.ma.masked_where(~mascaras["isolada"], mascaras["isolada"]),
                  cmap=colors.ListedColormap([CONFIG_MAPA["cor_isolado"]]),
                  alpha=CONFIG_MAPA["alpha_agua"], interpolation="nearest")

    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_linewidth(0.8)
        s.set_color(pal["borda"])

    ax.set_title(titulo, fontsize=13, weight="bold", loc="left", pad=24,
                 color=pal["texto"])
    if subtitulo:
        ax.text(0, 1.010, subtitulo, transform=ax.transAxes, fontsize=9,
                va="bottom", color=pal["texto_fraco"])

    # Seta norte (raster já está em UTM, norte = topo)
    ax.annotate("N", xy=(0.965, 0.955), xytext=(0.965, 0.875),
                xycoords="axes fraction", ha="center", fontsize=11, weight="bold",
                arrowprops=dict(arrowstyle="-|>", color="k", lw=1.6))

    _barra_escala(ax, dados_dem["transform"], dem.shape[1])

    itens = [Patch(fc=CONFIG_MAPA["cor_inundado"], alpha=CONFIG_MAPA["alpha_agua"],
                   label="Inundação conectada ao mar")]
    if mostrar_isoladas and mascaras["isolada"].any():
        itens.append(Patch(fc=CONFIG_MAPA["cor_isolado"], alpha=CONFIG_MAPA["alpha_agua"],
                           label="Abaixo da cota, sem conexão hidráulica"))
    itens.append(Patch(fc=CONFIG_MAPA["cor_oceano"], label="Oceano atual (FABDEM)"))
    ax.legend(handles=itens, loc="lower right", fontsize=8, framealpha=0.9)

    creditos = (f"MDE: FABDEM V1-2 (Hawker et al. 2022) · datum vertical {CONFIG_DEM['datum_vertical']} · "
                f"EPSG:{CONFIG_DEM['epsg_projetado']} @ {res:.0f} m · "
                f"cota = {cota['cota_m']:.2f} m\n"
                f"Cenários: IPCC AR6 WGI Cap. 9 · Exposição potencial, não previsão de inundação real.")
    ax.text(0, -0.028, creditos, transform=ax.transAxes, fontsize=7,
            va="top", color=pal["texto_fraco"])

    return fig, ax


def salvar_figura(fig, prefixo: str, pasta: str = "saidas", dpi: int = None) -> str:
    os.makedirs(pasta, exist_ok=True)
    dpi = CONFIG_MAPA["dpi_export"] if dpi is None else dpi
    caminho = os.path.join(pasta, f"{prefixo}_{_carimbo()}.png")
    # Respeita o tema com que a figura foi montada — gravar sempre em branco
    # deixaria um retângulo branco em volta de um mapa de fundo escuro.
    fig.savefig(caminho, dpi=dpi, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    _print(f"[EXPORT] Figura salva: {caminho} ({dpi} dpi)")
    return caminho
