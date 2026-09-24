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
import textwrap
from datetime import datetime

import numpy as np
import pandas as pd
import rasterio
import matplotlib
from matplotlib import cm, colors
from matplotlib.colors import LightSource
from matplotlib.lines import Line2D
from matplotlib.path import Path as _MplPath
from matplotlib.patches import PathPatch
from rasterio.warp import transform as _warp_transform
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
#   Enquanto isso, a interface avisa via `FONTE_CENARIOS` (logo abaixo) que
#   o valor é NMGM, não NMRM.
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
# Datums de maré em Caravelas — TPXO9-atlas v5 (OSU), extraídos em 22/09/2026
# por `07_mare_tpxo.py` (roda fora deste repo, contra o atlas de ~10 GB; só o
# JSON de saída — `dados_web/mare_caravelas_tpxo9v5.json` — é versionado
# aqui, como proveniência auditável). A tabela deixou de ser PLACEHOLDER
# (0.00 com `PROVISORIO = True`) para ser MODELO: `MEDIDA = False` continua
# acionando a tarja de aviso na interface, só que por outro motivo agora —
# ver `FONTE` abaixo e a ressalva gravada no JSON.
#
# Três coisas deliberadas nesta tabela, registradas aqui e não só no pedido
# que gerou a troca:
#   - PMQ (preamar de quadratura) é nível NOVO. Entra porque a disciplina
#     precisa do contraste sizígia x quadratura para ler exposição — não é
#     preenchimento de tabela.
#   - O rótulo do HAT diz "(estimada)" porque 1,676 m é a SOMA das 8
#     amplitudes lidas (Q1, O1, P1, K1, N2, M2, S2, K2): é um LIMITE
#     SUPERIOR, não o HAT real. Ignora a modulação nodal (ciclo de 18,6
#     anos) e não inclui constituintes de água rasa (M4, MS4) nem de longo
#     período (MF, MM). Nunca reportar como HAT sem esse qualificador.
#   - `MEDIDA = False`: TPXO é reanálise/modelo global assimilado a
#     altimetria e marégrafos — não é o marégrafo de Caravelas. A célula tem
#     ~3,7 km e fica AO LARGO da barra; não resolve amplificação nem
#     defasagem dentro dos canais do estuário (ver `dist_do_alvo_km` e
#     `ressalva` no JSON).
# -----------------------------------------------------------------------------
NIVEIS_MARE = {
    "MEDIDA": False,   # modelo global, não marégrafo — ver ressalvas acima
    "FONTE": "TPXO9-atlas v5 (OSU), 1/30°, ponto ao largo da barra",
    "NM":   {"rotulo": "Nível médio (NM)",                  "offset_m": 0.000},
    "PMQ":  {"rotulo": "Preamar de quadratura",             "offset_m": 0.456},
    "PM":   {"rotulo": "Preamar média (MHW)",               "offset_m": 0.913},
    "PMS":  {"rotulo": "Preamar de sizígia (MHWS)",         "offset_m": 1.244},
    "HAT":  {"rotulo": "Maior maré astronômica (estimada)", "offset_m": 1.676},
}

# -----------------------------------------------------------------------------
# COMO O "NÍVEL MÉDIO" ENTRA NA CONTA — leia antes de citar o número no relatório.
#
# Dois problemas INDEPENDENTES. A troca de 22/09/2026 (PROVISORIO -> TPXO)
# resolveu só o segundo — ninguém deve ler o primeiro como resolvido por
# causa do segundo.
#
# (a) DATUM VERTICAL DO MDE — continua em aberto, continua 0.00.
#     O nível médio NÃO foi calculado por este projeto. Ele é HERDADO do
#     datum vertical do próprio MDE: o FABDEM é referenciado ao geoide
#     EGM2008, e a simulação corta o terreno em z = 0 m nesse datum. Ou seja:
#
#         nível médio local  ==  geoide EGM2008        (OFFSET_GEOIDE_NM_M = 0)
#
#     Essa igualdade é uma APROXIMAÇÃO. A diferença real entre o geoide e a
#     superfície média do mar é a topografia dinâmica média (MDT), sustentada
#     por correntes, vento e gradientes de densidade — de ordem decimétrica
#     no Atlântico Sul tropical, comparável ao próprio NMRM de 2050. A maré
#     do TPXO NÃO fecha esse buraco: ela é referenciada ao nível médio LOCAL
#     do próprio modelo de maré, não ao geoide EGM2008. Preencher com
#     CMEMS/DTU ou com nivelamento geodésico amarrado a marégrafo.
#
# (b) DATUMS DE MARÉ — esses sim deixaram de ser placeholder em 22/09/2026.
#     Antes, PM/PMS/HAT viviam em 0.00 com `PROVISORIO = True` porque
#     nenhuma constante harmônica tinha sido usada. Agora `NIVEIS_MARE` vem
#     do TPXO9-atlas v5 (bloco acima) — real, mas ainda MODELO, não medição
#     (`MEDIDA = False`), com as ressalvas de célula de ~3,7 km e ponto ao
#     largo da barra.
# -----------------------------------------------------------------------------
OFFSET_GEOIDE_NM_M = 0.00

CONFIG_INUNDACAO = {
    "conectividade":   True,   # True = só conta água conectada ao mar (hidrologicamente plausível)
    "semear_bordas":   True,   # bordas do domínio também injetam água (evita falso confinamento)
    "conexao_8":       True,   # vizinhança 8 (diagonal) em vez de 4
    "area_minima_ha":  0.0,    # descarta manchas menores que isto (0 = não descarta)
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
    # Recorte do modo Turma (só na figura): terreno fora do polígono fica
    # esmaecido, não apagado; margem em fração do bbox do recorte.
    "alpha_fora_recorte":   0.25,
    "margem_enquadramento": 0.02,
    # Espelho de config.AREA_TURMA_KM2 (o motor não importa config): só
    # para o rodapé dizer que os km² NÃO são os da área da turma.
    "area_turma_km2":       21955.0,
}

# -----------------------------------------------------------------------------
# Camadas de contexto da turma (área de trabalho, isóbatas, UCs) na figura
# estática. Mesmas cores de `mapa_web.CONFIG_CAMADAS_TURMA`, para o mapa
# interativo e a figura de relatório contarem a mesma história — mas
# declaradas de novo AQUI, não importadas de lá: o motor não importa módulo
# de interface (regra 5 do projeto). Vetorial e externo ao projeto: nenhuma
# destas três camadas é gerada aqui, só desenhada.
CONFIG_CAMADAS_FIG = {
    "area_turma": {
        "cor_borda": "#2C7DA0",   # só contorno — ver nota em figura_mapa
        "espessura": 1.6,
        "zorder":    4,
    },
    "isobatas": {
        "cores_por_profundidade_m": {
            20:  "#BEE3F8",
            50:  "#8FD0EF",
            100: "#4FB6E0",
            200: "#1D7FB8",
            500: "#0B3D5C",
        },
        "cor_padrao":     "#4FB6E0",   # profundidade fora da lista acima
        "espessura":      1.0,
        "espessura_500m": 2.0,         # a mais funda se destaca das demais
        "zorder":         5,
    },
    "ucs": {
        "cor_borda":           "#1B7A3D",
        "cor_preenchimento":   "#3FA85C",
        "alpha_preenchimento": 0.18,
        "espessura_borda":     1.3,
        "zorder":              6,
    },
    # Contorno externo da união (`08_limite_turma.py`) — desenhado POR ÚLTIMO,
    # por cima de tudo, só a borda.
    "limite": {
        "cor_borda": "#0B3D5C",
        "espessura": 2.6,
        "zorder":    7,
    },
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

def mascara_inundacao(dem: np.ndarray,
                      mask_oceano: np.ndarray,
                      cota_m: float,
                      conectividade: bool = None,
                      semear_bordas: bool = None,
                      conexao_8: bool = None,
                      area_pixel_m2: float = None,
                      area_minima_ha: float = None,
                      mascara_agua: np.ndarray = None) -> dict:
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
    """
    cfg = CONFIG_INUNDACAO
    conectividade = cfg["conectividade"] if conectividade is None else conectividade
    semear_bordas = cfg["semear_bordas"] if semear_bordas is None else semear_bordas
    conexao_8 = cfg["conexao_8"] if conexao_8 is None else conexao_8
    area_minima_ha = cfg["area_minima_ha"] if area_minima_ha is None else area_minima_ha

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

    _print(f"[MASCARA] modo=conectado ({'mascara_agua' if usa_mascara_agua else 'mask_oceano (fallback)'}) "
          f"| cota={cota_m:.2f} m | manchas={n_rot} | conectadas={len(rot_conectados)} | "
          f"inundada={int(inundada.sum())} px | isolada={int(isolada.sum())} px")

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

def mascara_recorte(geojson: dict, dados_dem: dict) -> np.ndarray:
    """
    Rasteriza o limite da turma (`limite_turma.geojson`, EPSG:4674) na grade
    do MDE. Devolve bool na forma de `dados_dem["dem"]`: True = dentro.

    RECORTE É DE RELATO, NÃO DE CÁLCULO. A conectividade hidráulica é sempre
    resolvida no domínio INTEIRO do MDE (no modo web, `limiar_conexao_web.tif`
    já vem pré-computado assim); esta máscara só entra DEPOIS, para contar
    área e desenhar. Recortar o MDE antes do flood-fill cortaria caminhos de
    água que entram pela borda e inventaria pixels "isolados" que não são.
    Não inverta essa ordem numa refatoração.

    Só rasterio (já dependência do app) — nada de shapely no runtime.
    """
    from rasterio.features import geometry_mask
    from rasterio.warp import transform_geom

    dem = dados_dem["dem"]
    geoms = [transform_geom("EPSG:4674", dados_dem["crs"], f["geometry"])
             for f in geojson.get("features", [])]
    dentro = geometry_mask(geoms, out_shape=dem.shape,
                           transform=dados_dem["transform"], invert=True)

    a = dados_dem["area_pixel_m2"] / 1e6
    terra = np.isfinite(dem)
    terra_dentro = float((terra & dentro).sum()) * a
    terra_total = float(terra.sum()) * a
    pct = 100.0 * terra_dentro / terra_total if terra_total else float("nan")
    _print(f"[RECORTE] dentro={int(dentro.sum())} px | terra dentro={terra_dentro:.1f} km² "
           f"({pct:.1f}% da terra do domínio, {terra_total:.1f} km²)")
    return dentro


def estatisticas_area(mascaras: dict, dem: np.ndarray, area_pixel_m2: float,
                      recorte: np.ndarray = None) -> dict:
    """
    Converte contagem de pixels em km² e percentuais da área emersa atual.

    `recorte` (opcional, bool na forma do dem): conta só o que cai dentro dele.
    Sem recorte o comportamento é idêntico ao anterior.
    """
    a = area_pixel_m2 / 1e6  # km² por pixel
    if recorte is None:
        area_terra = float(np.isfinite(dem).sum()) * a
        area_inund = float(mascaras["inundada"].sum()) * a
        area_isol = float(mascaras["isolada"].sum()) * a
        area_bath = float(mascaras["abaixo"].sum()) * a
    else:
        area_terra = float((np.isfinite(dem) & recorte).sum()) * a
        area_inund = float((mascaras["inundada"] & recorte).sum()) * a
        area_isol = float((mascaras["isolada"] & recorte).sum()) * a
        area_bath = float((mascaras["abaixo"] & recorte).sum()) * a

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
    _print(f"[AREA]{' (recorte)' if recorte is not None else ''} "
          f"terra={area_terra:.1f} km² | inundada={area_inund:.1f} km² "
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
                    recorte: np.ndarray = None) -> pd.DataFrame:
    """
    `recorte`: ver `estatisticas_area` (só na contagem; o flood-fill roda
    no domínio inteiro).

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
                )
                e = estatisticas_area(m, dados_dem["dem"], dados_dem["area_pixel_m2"],
                              recorte=recorte)
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
                              mascara_agua=mascara_agua)
        e = estatisticas_area(m, dados_dem["dem"], dados_dem["area_pixel_m2"],
                              recorte=recorte)
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
                    recorte: np.ndarray = None) -> pd.DataFrame:
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
                              mascara_agua=mascara_agua)
        e = estatisticas_area(m, dados_dem["dem"], dados_dem["area_pixel_m2"],
                              recorte=recorte)
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
                     cota_m: float, recorte: np.ndarray = None) -> str:
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
    if recorte is not None:
        classes[~recorte] = 255   # nodata: fora da área da turma

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
            recorte_turma=("sim: 255 (nodata) fora da area da turma"
                           if recorte is not None else "nao"),
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


def _barra_escala(ax, transform, largura_px, comprimento_km=5, quadro=None):
    """
    Barra de escala simples em coordenadas de pixel. `quadro` = (col_min,
    col_max, lin_topo, lin_base) do enquadramento recortado; sem ele, a
    posição é a de sempre (relativa ao raster inteiro).
    """
    res = abs(transform.a)
    n_px = comprimento_km * 1000 / res
    if quadro is not None:
        c0, c1, l_topo, l_base = quadro
        x0 = c0 + 0.06 * (c1 - c0)
        y0 = l_base - 0.06 * (l_base - l_topo)
        ax.plot([x0, x0 + n_px], [y0, y0], color="k", lw=3, solid_capstyle="butt", zorder=10)
        ax.text(x0 + n_px / 2, y0, f"{comprimento_km} km", ha="center", va="bottom",
                fontsize=8, zorder=10,
                bbox=dict(fc="white", ec="none", alpha=0.75, pad=1.5))
        return
    x0 = largura_px * 0.06
    y0 = ax.get_ylim()[0] * 0.94 if ax.get_ylim()[0] > ax.get_ylim()[1] else ax.get_ylim()[1] * 0.94
    ax.plot([x0, x0 + n_px], [y0, y0], color="k", lw=3, solid_capstyle="butt", zorder=10)
    ax.text(x0 + n_px / 2, y0, f"{comprimento_km} km", ha="center", va="bottom",
            fontsize=8, zorder=10,
            bbox=dict(fc="white", ec="none", alpha=0.75, pad=1.5))


# -----------------------------------------------------------------------------
# Camadas de contexto da turma na figura estática — auxiliares geométricas.
#
# `ax.imshow(rgb)` em `figura_mapa` é chamado SEM `extent`, então os eixos da
# figura estão em coordenadas de PIXEL (x=coluna, y=linha, origem no canto
# superior esquerdo), não em metros UTM. Os GeoJSON da turma vêm em
# EPSG:4674 (SIRGAS 2000 geográfico). `_geo_para_pixel` faz as duas
# conversões em sequência: reprojeta para a grade do MDE e aplica a inversa
# do affine para cair em pixel.
# -----------------------------------------------------------------------------

def _geo_para_pixel(coords, transform, crs_origem: str = "EPSG:4674") -> list:
    """
    Converte [(lon, lat), ...] em [(col, lin), ...] no referencial de pixel
    da figura.

    Usa `rasterio.warp.transform` para a reprojeção (rasterio já é
    dependência do projeto — nada de pyproj nem geopandas só para isto) e a
    inversa do affine (`~transform`) para ir de metros UTM a pixel; o
    operador aceita arrays numpy diretamente. NÃO usa
    `rasterio.transform.rowcol`: ele arredonda para inteiro e serrilha a
    linha da geometria — aqui o traço tem que ficar suave.

    `crs_origem` é o CRS da geometria de entrada (EPSG:4674 nos três GeoJSON
    da turma); o destino é sempre a grade do MDE (`CONFIG_DEM["epsg_projetado"]`).
    """
    coords = np.asarray(coords, dtype="float64")
    if coords.shape[0] == 0:
        return []
    lons, lats = coords[:, 0], coords[:, 1]
    xs, ys = _warp_transform(crs_origem, f"EPSG:{CONFIG_DEM['epsg_projetado']}",
                             lons.tolist(), lats.tolist())
    cols, lins = ~transform * (np.asarray(xs), np.asarray(ys))
    return list(zip(cols.tolist(), lins.tolist()))


def _dentro_do_quadro(pontos_px, xlim, ylim) -> bool:
    """
    True se a caixa envolvente dos pontos cruza o quadro atual dos eixos.
    Usado para decidir se uma camada LIGADA ganha item de legenda — ligar o
    toggle não implica a geometria realmente cruzar o recorte do MDE (ex.:
    a isóbata de 50 m já está a leste da borda do recorte).

    Teste por CAIXA ENVOLVENTE, não por vértice: a área de trabalho da
    turma e as isóbatas vêm de geometria de baixa resolução (GEBCO 925 m),
    com vértices espaçados por vários km — um segmento cruza o quadro do
    raster sem que nenhum dos seus vértices caia dentro dele. Testar só
    vértice perdia exatamente esse caso (a borda oeste da área da turma,
    por exemplo, ficava sem item de legenda mesmo desenhada na figura).
    """
    if not pontos_px:
        return False
    cols, lins = np.asarray(pontos_px).T
    xmin, xmax = sorted(xlim)
    ymin, ymax = sorted(ylim)
    return bool(cols.min() <= xmax and cols.max() >= xmin
                and lins.min() <= ymax and lins.max() >= ymin)


def _path_poligono(coordenadas, transform, crs_origem: str) -> _MplPath | None:
    """
    Monta um único `matplotlib.path.Path` a partir dos anéis de um Polygon
    GeoJSON (`coordenadas[0]` é o anel externo, os demais são buracos).

    Um Path só, com o anel externo e os buracos concatenados e cada anel
    fechado por `CLOSEPOLY`, deixa o matplotlib recortar os buracos pela
    regra do número de voltas (nonzero): o GeoJSON exige anel externo
    anti-horário e buracos em sentido horário (RFC 7946), e é essa
    orientação oposta que faz o preenchimento padrão do matplotlib deixar o
    buraco vazio — sem isso uma UC com enclave apareceria pintada por cima
    dele.
    """
    vertices, codigos = [], []
    for anel in coordenadas:
        pts = _geo_para_pixel(anel, transform, crs_origem)
        if len(pts) < 4:   # anel GeoJSON fechado tem no mínimo 4 pontos (3 + repetição do 1º)
            continue
        vertices.extend(pts)
        codigos.extend([_MplPath.MOVETO] + [_MplPath.LINETO] * (len(pts) - 2) + [_MplPath.CLOSEPOLY])
    if not vertices:
        return None
    return _MplPath(vertices, codigos)


def _path_geometria(geometria, transform, crs_origem: str) -> _MplPath | None:
    """`_path_poligono` para Polygon OU MultiPolygon — um Path composto no
    segundo caso, uma chamada de `ax.add_patch` cobre a feature inteira."""
    tipo = geometria.get("type")
    if tipo == "Polygon":
        return _path_poligono(geometria["coordinates"], transform, crs_origem)
    if tipo == "MultiPolygon":
        sub = [_path_poligono(poly, transform, crs_origem) for poly in geometria["coordinates"]]
        sub = [p for p in sub if p is not None]
        return _MplPath.make_compound_path(*sub) if sub else None
    return None


def _linhas_geometria(geometria, transform, crs_origem: str) -> list:
    """Pontos de pixel de um LineString OU MultiLineString, uma lista de
    trechos (cada um plotável direto com `ax.plot`)."""
    tipo = geometria.get("type")
    if tipo == "LineString":
        return [_geo_para_pixel(geometria["coordinates"], transform, crs_origem)]
    if tipo == "MultiLineString":
        return [_geo_para_pixel(trecho, transform, crs_origem) for trecho in geometria["coordinates"]]
    return []


def _desenhar_camadas_turma(ax, transform, camadas_turma: dict,
                            ver_area_turma: bool, ver_isobatas_turma: bool,
                            ver_ucs_turma: bool,
                            ver_limite_turma: bool = False) -> list:
    """
    Desenha as camadas de contexto da turma por cima da lâmina d'água,
    em pixel (ver `_geo_para_pixel`). Ordem de zorder (`CONFIG_CAMADAS_FIG`):
    área de trabalho (só contorno) -> isóbatas (linhas) -> UCs (contorno +
    preenchimento translúcido).

    `camadas_turma` é o MESMO dict que `mapa_web.carregar_camadas_turma`
    devolve — passado por quem chama, porque o motor não lê arquivo de
    interface (regra 5 do projeto).

    Retorna a lista de itens de legenda (dict com "tipo" e "rotulo") só das
    camadas que estavam LIGADAS *e* tiveram pelo menos um ponto dentro do
    quadro atual — ligar o toggle não garante que a geometria cruze o
    recorte do MDE (a isóbata de 50 m, por exemplo, fica a leste da borda).
    """
    camadas_turma = camadas_turma or {}
    cfg = CONFIG_CAMADAS_FIG
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    itens_legenda = []

    geo_area = camadas_turma.get("area_turma")
    if ver_area_turma and geo_area is not None:
        c = cfg["area_turma"]
        visivel = False
        for feicao in geo_area.get("features", []):
            path = _path_geometria(feicao["geometry"], transform, "EPSG:4674")
            if path is None:
                continue
            ax.add_patch(PathPatch(path, facecolor="none", edgecolor=c["cor_borda"],
                                   linewidth=c["espessura"], zorder=c["zorder"]))
            visivel = visivel or _dentro_do_quadro(path.vertices.tolist(), xlim, ylim)
        if visivel:
            itens_legenda.append({"tipo": "linha", "cor": c["cor_borda"],
                                  "rotulo": "Área de trabalho da turma"})

    geo_iso = camadas_turma.get("isobatas")
    if ver_isobatas_turma and geo_iso is not None:
        c = cfg["isobatas"]
        visivel = False
        for feicao in geo_iso.get("features", []):
            prof = int(round(abs(feicao["properties"].get("prof", 0))))
            cor = c["cores_por_profundidade_m"].get(prof, c["cor_padrao"])
            peso = c["espessura_500m"] if prof == 500 else c["espessura"]
            for trecho in _linhas_geometria(feicao["geometry"], transform, "EPSG:4674"):
                if len(trecho) < 2:
                    continue
                cols, lins = zip(*trecho)
                ax.plot(cols, lins, color=cor, lw=peso, zorder=c["zorder"])
                visivel = visivel or _dentro_do_quadro(trecho, xlim, ylim)
        if visivel:
            itens_legenda.append({"tipo": "linha", "cor": c["cor_padrao"],
                                  "rotulo": "Isóbatas (20–500 m)"})

    geo_ucs = camadas_turma.get("ucs")
    if ver_ucs_turma and geo_ucs is not None:
        c = cfg["ucs"]
        visivel = False
        for feicao in geo_ucs.get("features", []):
            path = _path_geometria(feicao["geometry"], transform, "EPSG:4674")
            if path is None:
                continue
            ax.add_patch(PathPatch(path, facecolor=c["cor_preenchimento"],
                                   alpha=c["alpha_preenchimento"], edgecolor=c["cor_borda"],
                                   linewidth=c["espessura_borda"], zorder=c["zorder"]))
            visivel = visivel or _dentro_do_quadro(path.vertices.tolist(), xlim, ylim)
        if visivel:
            itens_legenda.append({"tipo": "area", "cor_borda": c["cor_borda"],
                                  "cor_preenchimento": c["cor_preenchimento"],
                                  "alpha": c["alpha_preenchimento"],
                                  "rotulo": "Unidades de conservação"})

    # Limite único da turma — por último, por cima das demais.
    geo_limite = camadas_turma.get("limite")
    if ver_limite_turma and geo_limite is not None:
        c = cfg["limite"]
        visivel = False
        for feicao in geo_limite.get("features", []):
            path = _path_geometria(feicao["geometry"], transform, "EPSG:4674")
            if path is None:
                continue
            ax.add_patch(PathPatch(path, facecolor="none", edgecolor=c["cor_borda"],
                                   linewidth=c["espessura"], zorder=c["zorder"]))
            visivel = visivel or _dentro_do_quadro(path.vertices.tolist(), xlim, ylim)
        if visivel:
            itens_legenda.append({"tipo": "linha", "cor": c["cor_borda"],
                                  "rotulo": "Limite da área da turma"})

    # `add_patch`/`plot` podem alargar xlim/ylim automaticamente (autoscale) —
    # restaura o quadro do raster, senão o estuário vira um ponto perdido no
    # meio da plataforma continental.
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)

    return itens_legenda


def figura_mapa(dados_dem: dict, mascaras: dict, cota: dict,
                titulo: str = "Exposição ao NMRM — Caravelas (BA)",
                subtitulo: str = "",
                mostrar_isoladas: bool = True,
                fundo: str = "hipsometrico",
                hs: np.ndarray = None,
                tema: str = "claro",
                figsize=(11, 9),
                camadas_turma: dict = None,
                ver_area_turma: bool = False,
                ver_isobatas_turma: bool = False,
                ver_ucs_turma: bool = False,
                ver_limite_turma: bool = False,
                recorte: np.ndarray = None):
    """
    Monta a figura de relatório: hillshade + hipsometria + lâmina d'água,
    com legenda, barra de escala, seta norte e créditos de fonte.

    `fundo`: "hipsometrico" | "hillshade" | "limpo"
    `tema`:  "claro" | "escuro" — muda só o papel da figura (ver CONFIG_TEMA).
    `hs`: sombreamento pré-calculado (evita recomputar a cada movimento
          do slider na interface; use `hillshade()` uma única vez).

    `camadas_turma`: o MESMO dict que `mapa_web.carregar_camadas_turma`
    devolve ({"area_turma", "isobatas", "ucs", "limite"}), passado por quem chama — o
    motor não lê arquivo de interface (regra 5 do projeto). Os quatro
    `ver_*_turma` ligam cada camada, todos desligados por padrão; ver
    `_desenhar_camadas_turma` para a lógica de desenho e de legenda.

    `recorte`: bool na forma do MDE (`mascara_recorte`). As lâminas d'água
    ficam só dentro dele; o MDE fora fica ESMAECIDO
    (`CONFIG_MAPA["alpha_fora_recorte"]`), não apagado, para o leitor ver que
    há terreno que não entrou na conta; e o enquadramento fecha no bbox do
    recorte. A máscara em si foi resolvida no domínio inteiro (ver
    `mascara_recorte`).

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

    alpha_dem = np.isfinite(dem).astype(float)
    if recorte is not None:
        alpha_dem = np.where(recorte, alpha_dem,
                             alpha_dem * CONFIG_MAPA["alpha_fora_recorte"])

    if fundo == "hipsometrico":
        vmax = float(np.nanpercentile(dem, 99.5))
        norm = colors.Normalize(vmin=0, vmax=max(vmax, 1.0))
        cmap_topo = matplotlib.colormaps[CONFIG_MAPA["cmap_topo"]]
        rgb = cmap_topo(norm(np.nan_to_num(dem)))
        rgb[..., :3] *= (0.35 + 0.65 * hs)[..., None]
        rgb[..., 3] = alpha_dem
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
                  interpolation="nearest",
                  alpha=alpha_dem if recorte is not None else None)

    # Lâmina d'água conectada. Com recorte, o corte é feito AQUI, no desenho.
    inundada = mascaras["inundada"] if recorte is None else mascaras["inundada"] & recorte
    isolada = mascaras["isolada"] if recorte is None else mascaras["isolada"] & recorte
    ax.imshow(np.ma.masked_where(~inundada, inundada),
              cmap=colors.ListedColormap([CONFIG_MAPA["cor_inundado"]]),
              alpha=CONFIG_MAPA["alpha_agua"], interpolation="nearest")

    if mostrar_isoladas and isolada.any():
        ax.imshow(np.ma.masked_where(~isolada, isolada),
                  cmap=colors.ListedColormap([CONFIG_MAPA["cor_isolado"]]),
                  alpha=CONFIG_MAPA["alpha_agua"], interpolation="nearest")

    # Contexto da turma — DEPOIS da lâmina d'água, ANTES da barra de escala e
    # da legenda (que ainda vai ganhar os itens destas camadas, se alguma
    # tiver desenhado algo dentro do quadro). `_desenhar_camadas_turma` já
    # restaura xlim/ylim no fim — o quadro aqui embaixo é o mesmo de antes.
    itens_turma = _desenhar_camadas_turma(
        ax, dados_dem["transform"], camadas_turma,
        ver_area_turma, ver_isobatas_turma, ver_ucs_turma, ver_limite_turma,
    )

    # Enquadramento: bbox do recorte (∩ grade do MDE) + margem. Vem depois de
    # `_desenhar_camadas_turma`, que restaura o quadro do raster inteiro.
    quadro = None
    if recorte is not None and recorte.any():
        lins = np.where(recorte.any(axis=1))[0]
        cols = np.where(recorte.any(axis=0))[0]
        marg = CONFIG_MAPA["margem_enquadramento"]
        c0, c1, l0, l1 = cols.min(), cols.max() + 1, lins.min(), lins.max() + 1
        dc, dl = marg * (c1 - c0), marg * (l1 - l0)
        quadro = (max(c0 - dc, -0.5), min(c1 + dc, dem.shape[1] - 0.5),
                  max(l0 - dl, -0.5), min(l1 + dl, dem.shape[0] - 0.5))
        ax.set_xlim(quadro[0], quadro[1])
        ax.set_ylim(quadro[3], quadro[2])   # linha cresce para baixo

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

    _barra_escala(ax, dados_dem["transform"], dem.shape[1], quadro=quadro)

    itens = [Patch(fc=CONFIG_MAPA["cor_inundado"], alpha=CONFIG_MAPA["alpha_agua"],
                   label="Inundação conectada ao mar")]
    if mostrar_isoladas and isolada.any():
        itens.append(Patch(fc=CONFIG_MAPA["cor_isolado"], alpha=CONFIG_MAPA["alpha_agua"],
                           label="Abaixo da cota, sem conexão hidráulica"))
    itens.append(Patch(fc=CONFIG_MAPA["cor_oceano"], label="Oceano atual (FABDEM)"))
    if recorte is not None:
        itens.append(Patch(fc="#888888", alpha=CONFIG_MAPA["alpha_fora_recorte"],
                           label="Terreno fora da área da turma (não contado)"))

    # Itens de legenda das camadas da turma — só as que `_desenhar_camadas_turma`
    # confirmou visíveis dentro do quadro (ligar o toggle não garante isso).
    for item in itens_turma:
        if item["tipo"] == "linha":
            itens.append(Line2D([0], [0], color=item["cor"], lw=2, label=item["rotulo"]))
        else:  # "area" — contorno + preenchimento, caso das UCs
            itens.append(Patch(fc=item["cor_preenchimento"], alpha=item["alpha"],
                               ec=item["cor_borda"], label=item["rotulo"]))

    ax.legend(handles=itens, loc="lower right", fontsize=8, framealpha=0.9)

    creditos = (f"MDE: FABDEM V1-2 (Hawker et al. 2022) · datum vertical {CONFIG_DEM['datum_vertical']} · "
                f"EPSG:{CONFIG_DEM['epsg_projetado']} @ {res:.0f} m · "
                f"cota = {cota['cota_m']:.2f} m\n"
                f"Cenários: IPCC AR6 WGI Cap. 9 · Exposição potencial, não previsão de inundação real.")
    if recorte is not None:
        a_km2 = dados_dem["area_pixel_m2"] / 1e6
        t_dentro = float((np.isfinite(dem) & recorte).sum()) * a_km2
        t_total = float(np.isfinite(dem).sum()) * a_km2
        aviso_recorte = (f"Recorte à área da turma: km² = interseção da área da turma com o "
                         f"domínio do MDE ({t_dentro:,.0f} km² de terra, de {t_total:,.0f} km² do domínio) "
                         f"— não são os {CONFIG_MAPA['area_turma_km2']:,.0f} km² da área da turma. "
                         f"Deixa de fora uma faixa estreita da borda oeste do domínio (terreno alto, "
                         f"Grupo Barreiras) que o modo Livre conta.")
        # Linhas curtas: uma linha longa alarga o layout e o constrained_layout
        # desiste ("axes sizes collapsed to zero").
        creditos += "\n" + textwrap.fill(aviso_recorte, width=125)
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
