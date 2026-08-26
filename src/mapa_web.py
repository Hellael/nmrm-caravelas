"""
mapa_web.py — Overlay raster para mapa interativo (Folium)
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB — Caravelas (BA)

Módulo SEM interface: converte a classificação de inundação (grade UTM 24S
do MDE) num PNG RGBA em EPSG:4326, pronto para
`folium.raster_layers.ImageOverlay`. Não desenha mapa nem widgets — quem
chama (a interface) monta o `folium.Map`.

Autor: Helio | Assistência: Claude
"""

from __future__ import annotations

import base64
import io

import numpy as np
from matplotlib.colors import to_rgb
from PIL import Image
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import array_bounds
from rasterio.warp import calculate_default_transform, reproject

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
