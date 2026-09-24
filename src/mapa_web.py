"""
mapa_web.py — Overlay raster para mapa interativo (Folium)
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB — Caravelas (BA)

Módulo SEM interface. Produz, a partir das grades UTM 24S do projeto, as
camadas que o mapa interativo consome:

    1. overlay de classificação de inundação  -> PNG RGBA em EPSG:4326
    2. overlay hipsométrico do próprio FABDEM  -> PNG RGBA em EPSG:4326
    3. isolinhas do próprio FABDEM             -> GeoJSON em EPSG:4326
    4. leitura de valor num ponto (lat/lon)    -> float | int | None

Não desenha mapa nem widgets — quem chama (a interface) monta o `folium.Map`.

v1.3 — as camadas 2 e 3 são derivadas do MESMO raster que alimenta a
simulação. É deliberado: a regra 2 do projeto proíbe trocar o FABDEM por
tiles genéricas de terreno (Terrarium, Terrain-RGB, SRTM), porque em planície
com manguezal o viés de dossel dessas fontes é maior que o próprio sinal de
NMRM simulado. Aqui a topografia que o usuário vê é, por construção, a
topografia que o modelo corta.

Autor: Helio | Assistência: Claude
"""

from __future__ import annotations

import base64
import io
import json
import os

import numpy as np
from matplotlib.colors import to_rgb
from PIL import Image
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import array_bounds, rowcol
from rasterio.warp import calculate_default_transform, reproject, transform as warp_transform
from scipy import ndimage

import config

# =============================================================================
# PARÂMETROS
# =============================================================================

CONFIG_MAPA_WEB = {
    "epsg_saida": 4326,   # lat/lon — exigido pelo folium.raster_layers.ImageOverlay
}

# Códigos do array de classes (0 = nada / transparente)
CODIGOS_CLASSE = {
    "inundada":    1,   # abaixo da cota, conectada ao mar
    "isolada":     2,   # abaixo da cota, sem conexão hidráulica
    "agua_atual":  3,   # oceano/estuário hoje (mascara_agua)
}


# =============================================================================
# CLASSIFICAÇÃO
# =============================================================================

def classificar_overlay(mascaras: dict, mask_agua: np.ndarray = None) -> np.ndarray:
    """
    Monta o array uint8 de classes a partir do dict retornado por
    `slr_core.mascara_inundacao`. Água atual tem prioridade visual sobre
    inundada/isolada na sobreposição (não há conflito de fato, já que
    `abaixo` — base de inundada/isolada — já exclui pixels de água por
    construção, mas a ordem de escrita deixa isso explícito).
    """
    classes = np.zeros(mascaras["inundada"].shape, dtype="uint8")
    classes[mascaras["isolada"]] = CODIGOS_CLASSE["isolada"]
    classes[mascaras["inundada"]] = CODIGOS_CLASSE["inundada"]
    if mask_agua is not None:
        classes[mask_agua] = CODIGOS_CLASSE["agua_atual"]
    return classes


# =============================================================================
# REPROJEÇÃO + PNG
# =============================================================================

def _hex_para_rgb(cor_hex: str) -> tuple:
    r, g, b = to_rgb(cor_hex)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def gerar_overlay_web(classes: np.ndarray, transform, crs, cores: dict) -> tuple:
    """
    Reprojeta o array de classes (grade UTM do MDE) para EPSG:4326 e monta
    um PNG RGBA com fundo totalmente transparente, uma cor sólida por classe.

    `classes`  : uint8, 0 = nada (transparente), demais códigos em `cores`.
    `cores`    : {codigo: "#RRGGBB"}.

    ATENÇÃO: `classes` é raster CATEGÓRICO (código de classe, não grandeza
    contínua). Reamostragem usa `Resampling.nearest` — bilinear misturaria
    códigos vizinhos (ex.: 1 e 3) em valores intermediários sem sentido
    (2, 2.5...) nas bordas de cada mancha.

    Retorna (png_data_uri, bounds):
        png_data_uri : string "data:image/png;base64,..." — aceita
                       diretamente por `folium.raster_layers.ImageOverlay`.
        bounds        : [[sul, oeste], [norte, leste]] em graus decimais.
    """
    epsg_saida = CONFIG_MAPA_WEB["epsg_saida"]
    crs_saida = CRS.from_epsg(epsg_saida)

    altura, largura = classes.shape
    esquerda, baixo, direita, cima = array_bounds(altura, largura, transform)

    transform_alvo, larg_alvo, alt_alvo = calculate_default_transform(
        crs, crs_saida, largura, altura,
        left=esquerda, bottom=baixo, right=direita, top=cima,
    )

    destino = np.zeros((alt_alvo, larg_alvo), dtype="uint8")
    reproject(
        source=classes, destination=destino,
        src_transform=transform, src_crs=crs,
        dst_transform=transform_alvo, dst_crs=crs_saida,
        resampling=Resampling.nearest,
        src_nodata=0, dst_nodata=0,
    )

    rgba = np.zeros((alt_alvo, larg_alvo, 4), dtype="uint8")
    for codigo, cor_hex in cores.items():
        r, g, b = _hex_para_rgb(cor_hex)
        sel = destino == codigo
        rgba[sel] = (r, g, b, 255)

    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
    png_data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    oeste, sul, leste, norte = array_bounds(alt_alvo, larg_alvo, transform_alvo)
    bounds = [[sul, oeste], [norte, leste]]

    n_pintado = int((destino > 0).sum())
    print(f"[MAPA_WEB] overlay reprojetado: {alt_alvo}x{larg_alvo} px | "
          f"EPSG:{epsg_saida} | {n_pintado} px pintados | bounds={bounds}")

    return png_data_uri, bounds


# =============================================================================
# TOPOGRAFIA — camada hipsométrica derivada do PRÓPRIO FABDEM
# =============================================================================

# Faixas pensadas para a planície de Caravelas, não para relevo genérico: a
# metade da área útil está abaixo de 5 m, então o degrau é decimétrico embaixo
# e vai afrouxando. `faixas_m[i]` é o piso da faixa i; a última faixa é aberta
# (>= último valor). `cores` tem obrigatoriamente o mesmo comprimento.
#
# A rampa imita a leitura clássica de carta topográfica (verde nas cotas
# baixas -> amarelo -> marrom nas altas), que é também a do topographic-map.com
# usado como referência. As cores NÃO são as do MapBiomas nem as da lâmina
# d'água: nenhuma das duas leituras pode ser confundida com a outra.
CONFIG_TOPO = {
    "faixas_m": [0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0],
    "cores": [
        "#0E5B3A", "#1F7A4C", "#3E9A5F", "#6DB56B", "#9DCB79",
        "#C9DC8A", "#E6D992", "#DEBB77", "#C79A62", "#A97A4E", "#8A5E3C",
    ],

    # Isolinhas. `niveis_m` inclui as cotas que a disciplina usa (0,5 / 1 / 2 m)
    # para a isolinha ser lida junto com o cenário, não como enfeite.
    "niveis_m": [0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0],
    "niveis_destaque_m": [1.0, 2.0, 5.0, 10.0],
    "cor_isolinha": "#4A3B2A",
    "largura_isolinha": 0.8,
    "largura_isolinha_destaque": 1.6,

    # Geração das isolinhas. Sem estes três a camada fica pesada demais para o
    # navegador: a grade tem ~5 milhões de pixels e o contorno bruto de uma
    # planície ruidosa gera dezenas de milhares de vértices por nível.
    "subamostragem": 3,          # 1 = grade cheia; 3 -> ~90 m entre nós
    "suavizacao_sigma_px": 1.5,  # gaussiano ANTES do contorno (ruído decimétrico do MDE)
    "tolerancia_simplificacao_m": 45.0,  # Douglas-Peucker, em metros
    "comprimento_minimo_m": 500.0,       # descarta fiapo de isolinha
}


def _codificar_png(rgba: np.ndarray) -> str:
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def faixas_hipsometricas(teto_m: float | None = None) -> list[dict]:
    """
    Itens de legenda da camada topográfica: rótulo textual + cor.

    `teto_m` : teto de confiança do MDE (modo web = `clamp_m`, ver
    `03_prepara_dem_web.py`). Terreno acima disso foi achatado no clamp, então
    a faixa cujo piso é esse teto deixa de significar "piso–próximo piso" (a
    faixa seguinte não existe de verdade) e vira um catch-all aberto — as
    faixas ACIMA do teto (piso > teto_m) são descartadas por serem
    inalcançáveis. Assume que `CONFIG_TOPO["faixas_m"]` contém `teto_m` como
    um dos pisos (é o caso do clamp de 20 m); só então o corte cai exatamente
    na fronteira certa.
    """
    faixas = CONFIG_TOPO["faixas_m"]
    cores = CONFIG_TOPO["cores"]
    itens = []
    for i, (piso, cor) in enumerate(zip(faixas, cores)):
        if teto_m is not None and piso > teto_m:
            continue
        if i + 1 < len(faixas):
            rotulo = f"{piso:g} – {faixas[i + 1]:g} m"
        else:
            rotulo = f"> {piso:g} m"
        itens.append({"faixa": rotulo, "cor": cor, "piso_m": piso})
    if teto_m is not None and itens:
        itens[-1] = {**itens[-1], "faixa": f"≥ {teto_m:g} m (teto do modo web)"}
    return itens


def faixa_da_cota(z: float, teto_m: float | None = None) -> dict | None:
    """
    Em qual faixa hipsométrica cai uma cota. Serve para o popup do mapa dizer
    a mesma coisa que a cor embaixo do cursor — se o número e a cor
    discordassem, a legenda perderia serventia.

    `teto_m` repassado para `faixas_hipsometricas` — com ele, uma cota no teto
    do clamp (ou acima, por segurança) cai na faixa catch-all "≥ teto_m", não
    numa faixa que o clamp já tornou inalcançável.

    Retorna {faixa, cor, piso_m} ou None se `z` não for número válido.
    """
    if z is None or not np.isfinite(z):
        return None
    faixas = CONFIG_TOPO["faixas_m"]
    itens = faixas_hipsometricas(teto_m=teto_m)
    i = int(np.clip(np.searchsorted(np.asarray(faixas, dtype="float64"),
                                    float(z), side="right") - 1,
                    0, len(itens) - 1))
    return itens[i]


def gerar_overlay_hipsometrico(dem: np.ndarray, transform, crs) -> tuple:
    """
    Overlay de elevação em faixas, no mesmo esquema do overlay de inundação.

    ATENÇÃO ao motivo de classificar ANTES de reprojetar: a faixa é um dado
    CATEGÓRICO, então a reprojeção pode usar `nearest` e nenhum pixel muda de
    faixa no caminho. Reprojetar a elevação contínua com bilinear e classificar
    depois criaria, na borda do nodata, cotas interpoladas entre terreno real e
    vazio — cota inventada, exatamente o que a regra 1 do projeto proíbe.

    Retorna (png_data_uri, bounds) — bounds em [[sul, oeste], [norte, leste]].
    """
    faixas = np.asarray(CONFIG_TOPO["faixas_m"], dtype="float64")
    valido = np.isfinite(dem)

    # searchsorted devolve 1..n para z >= faixas[0]; z negativo (raro, mas o
    # FABDEM tem pixels abaixo do geoide) cai em 0 e é puxado para a 1ª faixa.
    idx = np.searchsorted(faixas, np.where(valido, dem, 0.0), side="right")
    idx = np.clip(idx, 1, len(faixas)).astype("uint8")
    idx[~valido] = 0  # 0 = transparente

    cores = {i + 1: cor for i, cor in enumerate(CONFIG_TOPO["cores"])}
    uri, bounds = gerar_overlay_web(idx, transform, crs, cores)
    print(f"[TOPO] hipsométrico: {len(cores)} faixas | "
          f"z de {np.nanmin(dem):.2f} a {np.nanmax(dem):.2f} m")
    return uri, bounds


# =============================================================================
# ISOLINHAS — contorno do próprio FABDEM, em GeoJSON
# =============================================================================

def _simplifica_rdp(pontos: np.ndarray, tolerancia: float) -> np.ndarray:
    """
    Douglas-Peucker iterativo (sem recursão, para não estourar a pilha em
    linhas longas). `pontos` em metros; `tolerancia` em metros.
    """
    n = len(pontos)
    if n < 3 or tolerancia <= 0:
        return pontos

    manter = np.zeros(n, dtype=bool)
    manter[0] = manter[-1] = True
    pilha = [(0, n - 1)]

    while pilha:
        ini, fim = pilha.pop()
        if fim <= ini + 1:
            continue
        p0, p1 = pontos[ini], pontos[fim]
        seg = p1 - p0
        norma = float(np.hypot(*seg))
        trecho = pontos[ini + 1:fim]
        if norma < 1e-9:
            dist = np.hypot(*(trecho - p0).T)
        else:
            # distância ponto-reta pelo determinante 2x2 (equivalente ao
            # produto vetorial 2D, que o numpy 2 deprecou para vetores 2D)
            d = trecho - p0
            dist = np.abs(seg[0] * d[:, 1] - seg[1] * d[:, 0]) / norma
        if dist.size == 0:
            continue
        k = int(np.argmax(dist))
        if dist[k] > tolerancia:
            corte = ini + 1 + k
            manter[corte] = True
            pilha.append((ini, corte))
            pilha.append((corte, fim))

    return pontos[manter]


def gerar_isolinhas_geojson(dem: np.ndarray, transform, crs,
                            niveis: list = None) -> dict:
    """
    Isolinhas do FABDEM em GeoJSON (EPSG:4326), uma Feature por nível.

    O oceano (nodata no MDE) é preenchido com 0,0 m ANTES do contorno. Não é
    chute: 0,0 é como o próprio FABDEM codifica oceano, e o efeito prático é
    que a isolinha de 0,5 m acompanha a linha de costa em vez de morrer nela.
    A área preenchida não vira terreno em lugar nenhum da simulação — este
    preenchimento existe só dentro desta função.

    Retorna um FeatureCollection; cada Feature tem `cota_m` e `destaque`.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    niveis = CONFIG_TOPO["niveis_m"] if niveis is None else niveis
    f = max(1, int(CONFIG_TOPO["subamostragem"]))
    sigma = CONFIG_TOPO["suavizacao_sigma_px"]

    z = np.where(np.isfinite(dem), dem, 0.0).astype("float32")
    if sigma > 0:
        z = ndimage.gaussian_filter(z, sigma=sigma)
    z = z[::f, ::f]

    # Coordenadas UTM do centro de cada pixel da grade subamostrada.
    res_x, res_y = abs(transform.a), abs(transform.e)
    x0, y0 = transform.c + res_x / 2.0, transform.f - res_y / 2.0
    xs = x0 + np.arange(z.shape[1]) * res_x * f
    ys = y0 - np.arange(z.shape[0]) * res_y * f

    fig = plt.figure()
    ax = fig.add_subplot(111)
    cs = ax.contour(xs, ys, z, levels=sorted(niveis))
    tol = CONFIG_TOPO["tolerancia_simplificacao_m"]
    comp_min = CONFIG_TOPO["comprimento_minimo_m"]
    destaque = set(CONFIG_TOPO["niveis_destaque_m"])

    feicoes = []
    n_vertices = 0
    for nivel, segmentos in zip(cs.levels, cs.allsegs):
        linhas = []
        for seg in segmentos:
            if len(seg) < 2:
                continue
            comp = float(np.hypot(*np.diff(seg, axis=0).T).sum())
            if comp < comp_min:
                continue
            simples = _simplifica_rdp(np.asarray(seg, dtype="float64"), tol)
            if len(simples) < 2:
                continue
            lons, lats = warp_transform(crs, CRS.from_epsg(CONFIG_MAPA_WEB["epsg_saida"]),
                                        simples[:, 0].tolist(), simples[:, 1].tolist())
            linhas.append([[round(lo, 6), round(la, 6)] for lo, la in zip(lons, lats)])
            n_vertices += len(simples)
        if not linhas:
            continue
        feicoes.append({
            "type": "Feature",
            "geometry": {"type": "MultiLineString", "coordinates": linhas},
            "properties": {
                "cota_m": float(nivel),
                "rotulo": f"{nivel:g} m",
                "destaque": bool(float(nivel) in destaque),
            },
        })
    plt.close(fig)

    print(f"[TOPO] isolinhas: {len(feicoes)} níveis | {n_vertices} vértices "
          f"| subamostragem={f} | tolerância={tol:.0f} m")
    return {"type": "FeatureCollection", "features": feicoes}


# =============================================================================
# LEITURA PONTUAL — clique no mapa
# =============================================================================

def valor_no_ponto(arr: np.ndarray, transform, crs, lat: float, lon: float):
    """
    Valor do raster no ponto (lat, lon) em graus decimais.

    Usa `nearest` puro: devolve o valor DO PIXEL, sem interpolar. Numa planície
    onde 30 cm decidem o cenário, um número interpolado entre dois pixels não é
    medição de lugar nenhum. Retorna None fora da grade ou em nodata.
    """
    if arr is None or crs is None:
        return None
    xs, ys = warp_transform(CRS.from_epsg(CONFIG_MAPA_WEB["epsg_saida"]), crs,
                            [float(lon)], [float(lat)])
    linha, coluna = rowcol(transform, xs[0], ys[0])
    linha, coluna = int(linha), int(coluna)
    if not (0 <= linha < arr.shape[0] and 0 <= coluna < arr.shape[1]):
        return None
    valor = arr[linha, coluna]
    if isinstance(valor, np.floating) and not np.isfinite(valor):
        return None
    return valor.item()


# =============================================================================
# CAMADAS DA ÁREA DE TRABALHO DA TURMA — vetoriais, EXTERNAS ao projeto
# =============================================================================

# A área da turma (UCs + plataforma até a isóbata de 500 m, ver
# config.BBOX_TURMA) é quase toda oceânica e fora do domínio do FABDEM — ela
# entra só como contexto vetorial por cima do mapa, nunca como raster.
# Nenhum destes três GeoJSON é gerado por este projeto: são consumidos como
# vieram (CNUC 07/2026 e Batimetria do Brasil CPRM/ANP 2013).
CONFIG_CAMADAS_TURMA = {
    "area_turma": {
        "cor_preenchimento":   "#A9D6E5",
        "alpha_preenchimento": 0.15,
        "cor_borda":           "#2C7DA0",
        "espessura_borda":     2.0,
    },
    "isobatas": {
        # profundidade absoluta (m) -> cor, do claro (raso) ao escuro (fundo)
        "cores_por_profundidade_m": {
            20:  "#BEE3F8",
            50:  "#8FD0EF",
            100: "#4FB6E0",
            200: "#1D7FB8",
            500: "#0B3D5C",
        },
        "cor_padrao":     "#4FB6E0",   # profundidade fora da lista acima
        "espessura":      1.3,
        "espessura_500m": 2.4,         # a mais funda se destaca das demais
    },
    "ucs": {
        "cor_borda":           "#1B7A3D",
        "cor_preenchimento":   "#3FA85C",
        "alpha_preenchimento": 0.18,
        "espessura_borda":     1.6,
    },
}


def carregar_camadas_turma(dir_dados) -> dict:
    """
    Lê os três GeoJSON da área de trabalho da turma com `json` da stdlib —
    arquivos pequenos e estáticos, então não justificam adicionar geopandas
    ao requirements.txt; `folium.GeoJson` aceita dict puro.

    Nenhum dos três é gerado por este projeto (regra: só consumir):
    `config.ARQ_UCS_TURMA` vem do CNUC 07/2026 (ICMBio/MMA);
    `config.ARQ_ISOBATAS_TURMA` e `config.ARQ_AREA_TURMA` vêm da Batimetria
    do Brasil CPRM/ANP 2013 (derivada do GEBCO 925 m).

    Dois ajustes de propriedade, só para o tooltip funcionar sem recalcular
    geodésia nem puxar geopandas:
      - `area_turma`: injeta `area_km2_fmt` a partir de `config.AREA_TURMA_KM2`
        (o GeoJSON só traz o nome).
      - `ucs`: injeta `ha_total_fmt`, o campo `ha_total` (string) formatado
        com separador de milhar, no mesmo estilo `:,.0f` usado no resto da
        interface (`02_simulador_nmrm.py`).

    Retorna {"area_turma": dict|None, "isobatas": dict|None, "ucs": dict|None}.
    Arquivo ausente ou ilegível não levanta exceção — a camada correspondente
    volta `None` e um aviso é impresso; quem chama decide como reagir (a
    interface simplesmente deixa de desenhar aquela camada).
    """
    dir_dados = str(dir_dados)
    arquivos = {
        "area_turma": config.ARQ_AREA_TURMA,
        "isobatas":   config.ARQ_ISOBATAS_TURMA,
        "ucs":        config.ARQ_UCS_TURMA,
    }

    camadas: dict = {}
    for chave, nome_arq in arquivos.items():
        caminho = os.path.join(dir_dados, nome_arq)
        if not os.path.exists(caminho):
            print(f"[MAPA_WEB] camada da turma ausente: {caminho}")
            camadas[chave] = None
            continue
        try:
            with open(caminho, encoding="utf-8") as f:
                camadas[chave] = json.load(f)
        except (OSError, ValueError) as erro:
            print(f"[MAPA_WEB] falha ao ler {caminho}: {erro}")
            camadas[chave] = None

    if camadas.get("area_turma") is not None:
        for feicao in camadas["area_turma"].get("features", []):
            feicao.setdefault("properties", {})["area_km2_fmt"] = \
                f"{config.AREA_TURMA_KM2:,.0f}"

    if camadas.get("ucs") is not None:
        for feicao in camadas["ucs"].get("features", []):
            propriedades = feicao.setdefault("properties", {})
            try:
                propriedades["ha_total_fmt"] = f"{float(propriedades.get('ha_total')):,.0f}"
            except (TypeError, ValueError):
                propriedades["ha_total_fmt"] = "—"

    n_ok = sum(v is not None for v in camadas.values())
    print(f"[MAPA_WEB] camadas da turma: {n_ok}/3 carregadas")
    return camadas
