"""
src/correntes.py — Camada de correntes oceânicas do simulador (v3.1)

Lê `dados_web/correntes_caravelas.npz` (produto do `12_prepara_correntes.py`:
climatologia e médias trimestrais de 10 anos de GLORYS12 mensal) e entrega ao
mapa interativo:

    - overlay raster da rapidez (m/s) com escala de cor FIXA por profundidade,
      para os períodos serem comparáveis entre si;
    - setas de direção (GeoJSON), com comprimento proporcional à rapidez;
    - leitura pontual (clique): u, v, rapidez, direção e constância.

Só numpy + scipy + PIL + matplotlib (já estão no requirements.txt do app):
o NetCDF nunca chega ao Cloud — o `12` já grava um npz leve.

É camada VISUAL de contexto: não entra em nenhuma conta de exposição ao NMRM
(a Parte 1 é exposição estática por cota). Correntes são MODELO assimilativo
em grade de ~8 km, não medição.
"""

from __future__ import annotations

import json
import os

import numpy as np
from matplotlib import colormaps
from scipy import ndimage

import config
from src.mapa_web import _codificar_png

# -----------------------------------------------------------------------------
# PARÂMETROS DE VISUALIZAÇÃO (nada de número solto dentro de função)
# -----------------------------------------------------------------------------
CONFIG_CORRENTES_VIZ = {
    "cmap": "viridis",
    "percentil_vmax": 99.0,          # teto da escala de cor, por profundidade
    "vmax_arredonda_ms": 0.05,       # arredonda o teto p/ cima em passos disto
    "vmax_minimo_ms": 0.10,          # evita escala degenerada em níveis fundos
    "fator_suavizacao": 4,           # upsample bilinear do raster (blocos -> suave)
    "limite_mascara_terra": 0.5,     # fração de células válidas p/ pixel contar
    "setas_passo_celulas": 3,        # 1 seta a cada N células (3 -> ~0,25°)
    "seta_rapidez_minima_ms": 0.03,  # abaixo disto não desenha seta
    "seta_comprimento_max_graus": 0.22,  # comprimento da seta na rapidez vmax
    "seta_cabeca_fracao": 0.32,      # tamanho da cabeça em relação ao corpo
    "seta_cabeca_abertura_graus": 25.0,
    "seta_cor": "#FFFFFF",
    "seta_espessura": 1.3,
    "opacidade_padrao": 0.75,
}


def caminho_produto(dir_web) -> str:
    return os.path.join(str(dir_web), config.ARQ_CORRENTES_WEB)


def carregar(caminho: str) -> dict | None:
    """Lê o npz. Devolve None se não existe ou não bate com o esperado —
    a camada é opcional e o simulador nunca depende dela."""
    if not caminho or not os.path.exists(caminho):
        return None
    try:
        with np.load(caminho, allow_pickle=False) as z:
            d = {
                "u": z["u"].astype("float32"), "v": z["v"].astype("float32"),
                "constancia": z["constancia"].astype("float32"),
                "lat": z["lat"].astype("float64"), "lon": z["lon"].astype("float64"),
                "periodos": [str(x) for x in z["periodos"]],
                "prof_alvo": [float(x) for x in z["profundidade_alvo_m"]],
                "prof_usada": [float(x) for x in z["profundidade_usada_m"]],
                "meta": json.loads(str(z["metadados"])),
            }
    except Exception:  # noqa: BLE001 — arquivo corrompido não pode derrubar o app
        return None
    n_p, n_z, n_y, n_x = d["u"].shape
    if (n_p != len(d["periodos"]) or n_z != len(d["prof_usada"])
            or n_y != d["lat"].size or n_x != d["lon"].size):
        return None
    if d["lat"][0] > d["lat"][-1]:          # garante lat crescente
        d["lat"] = d["lat"][::-1]
        for c in ("u", "v", "constancia"):
            d[c] = d[c][:, :, ::-1, :]
    d["passo_lat"] = float(np.abs(np.diff(d["lat"])).mean())
    d["passo_lon"] = float(np.abs(np.diff(d["lon"])).mean())
    return d


def rotulo_periodo(chave: str) -> str:
    return config.CONFIG_CORRENTES["rotulos_periodos"].get(chave, chave)


def rotulo_nivel(d: dict, iz: int) -> str:
    """'Superfície (0,5 m)' ou '186 m' — com a profundidade REAL do nível."""
    z = d["prof_usada"][iz]
    if z < 5:
        return f"Superfície ({z:.1f} m)".replace(".", ",")
    return f"{z:.0f} m"


def limites_graus(d: dict) -> list:
    """[[lat_sul, lon_oeste], [lat_norte, lon_leste]] — bordas das células."""
    mh_lat, mh_lon = d["passo_lat"] / 2, d["passo_lon"] / 2
    return [[float(d["lat"][0] - mh_lat), float(d["lon"][0] - mh_lon)],
            [float(d["lat"][-1] + mh_lat), float(d["lon"][-1] + mh_lon)]]


def campo(d: dict, ip: int, iz: int):
    """u, v, rapidez e constância de um (período, nível)."""
    u, v = d["u"][ip, iz], d["v"][ip, iz]
    return u, v, np.hypot(u, v), d["constancia"][ip, iz]


def vmax_nivel(d: dict, iz: int) -> float:
    """Teto da escala de cor do nível, COMUM a todos os períodos — é isso que
    torna a climatologia e os trimestres comparáveis a olho."""
    viz = CONFIG_CORRENTES_VIZ
    rap = np.hypot(d["u"][:, iz], d["v"][:, iz])
    base = float(np.nanpercentile(rap, viz["percentil_vmax"])) if np.isfinite(rap).any() else 0.0
    passo = viz["vmax_arredonda_ms"]
    return max(viz["vmax_minimo_ms"], float(np.ceil(base / passo) * passo))


def _suaviza(arr_u, arr_v, fator: int):
    """Upsample bilinear de u e v respeitando a terra (NaN): interpola
    valor*mascara e mascara, divide — a costa não escurece nem 'vaza'."""
    viz = CONFIG_CORRENTES_VIZ
    valido = np.isfinite(arr_u) & np.isfinite(arr_v)
    m = ndimage.zoom(valido.astype("float32"), fator, order=1)
    saida = []
    for a in (arr_u, arr_v):
        num = ndimage.zoom(np.where(valido, a, 0.0).astype("float32"), fator, order=1)
        saida.append(np.where(m > viz["limite_mascara_terra"], num / np.maximum(m, 1e-6), np.nan))
    return saida[0], saida[1]


def gerar_overlay(d: dict, ip: int, iz: int, vmax: float | None = None) -> tuple:
    """PNG RGBA (data URI) da rapidez + limites em graus. Terra transparente."""
    viz = CONFIG_CORRENTES_VIZ
    u, v, _, _ = campo(d, ip, iz)
    us, vs = _suaviza(u, v, viz["fator_suavizacao"])
    rap = np.hypot(us, vs)
    vmax = vmax or vmax_nivel(d, iz)
    norm = np.clip(rap / vmax, 0, 1)
    rgba = (colormaps[viz["cmap"]](norm) * 255).astype("uint8")
    rgba[..., 3] = np.where(np.isfinite(rap), 255, 0)
    rgba = rgba[::-1]                         # lat cresce p/ cima no mapa, linha 0 no topo
    return _codificar_png(np.ascontiguousarray(rgba)), limites_graus(d)


def gerar_setas_geojson(d: dict, ip: int, iz: int, vmax: float | None = None) -> dict:
    """Setas (corpo + duas linhas de cabeça) como MultiLineString por célula
    amostrada. Comprimento proporcional à rapidez; a cabeça é fixa em graus,
    então seta lenta e seta rápida têm a mesma 'cara'."""
    viz = CONFIG_CORRENTES_VIZ
    u, v, rap, _ = (a.astype('float64') for a in campo(d, ip, iz))  # float32 não vai p/ JSON
    vmax = vmax or vmax_nivel(d, iz)
    passo = viz["setas_passo_celulas"]
    ab = np.radians(viz["seta_cabeca_abertura_graus"])
    feicoes = []
    for j in range(passo // 2, u.shape[0], passo):
        for i in range(passo // 2, u.shape[1], passo):
            if not np.isfinite(rap[j, i]) or rap[j, i] < viz["seta_rapidez_minima_ms"]:
                continue
            lat0, lon0 = float(d["lat"][j]), float(d["lon"][i])
            # direção em graus no plano lon/lat; corrige o encolhimento de lon
            cos_lat = np.cos(np.radians(lat0))
            ang = np.arctan2(v[j, i], u[j, i])
            comp = viz["seta_comprimento_max_graus"] * min(rap[j, i] / vmax, 1.0)
            dx, dy = np.cos(ang) * comp / cos_lat, np.sin(ang) * comp
            # centraliza a seta na célula: da cauda (-meia) à ponta (+meia)
            cauda = (lon0 - dx / 2, lat0 - dy / 2)
            ponta = (lon0 + dx / 2, lat0 + dy / 2)
            cab = comp * viz["seta_cabeca_fracao"]
            linhas = [[cauda, ponta]]
            for sinal in (-1, 1):
                a = ang + np.pi + sinal * ab
                linhas.append([ponta, (ponta[0] + np.cos(a) * cab / cos_lat,
                                       ponta[1] + np.sin(a) * cab)])
            direcao = (np.degrees(np.arctan2(u[j, i], v[j, i])) + 360) % 360
            feicoes.append({
                "type": "Feature",
                "properties": {"rap": f"{rap[j, i]:.2f} m/s".replace(".", ","),
                               "dir": f"{direcao:.0f}°"},
                "geometry": {"type": "MultiLineString",
                             "coordinates": [[[round(float(x), 4), round(float(y), 4)] for x, y in ln]
                                             for ln in linhas]}})
    return {"type": "FeatureCollection", "features": feicoes}


def valor_no_ponto(d: dict, ip: int, iz: int, lat: float, lon: float) -> dict | None:
    """Leitura da célula mais próxima. None fora do domínio ou em terra."""
    lat_ok = d["lat"][0] - d["passo_lat"] / 2 <= lat <= d["lat"][-1] + d["passo_lat"] / 2
    lon_ok = d["lon"][0] - d["passo_lon"] / 2 <= lon <= d["lon"][-1] + d["passo_lon"] / 2
    if not (lat_ok and lon_ok):
        return None
    j = int(np.abs(d["lat"] - lat).argmin())
    i = int(np.abs(d["lon"] - lon).argmin())
    u, v, rap, const = (a[j, i] for a in campo(d, ip, iz))
    if not np.isfinite(rap):
        return {"terra": True}
    direcao = (np.degrees(np.arctan2(u, v)) + 360) % 360   # PARA onde flui, 0° = norte
    pontos = ["N", "NE", "L", "SE", "S", "SO", "O", "NO"]
    return {"terra": False, "u": float(u), "v": float(v), "rapidez": float(rap),
            "direcao": float(direcao), "rosa": pontos[int(((direcao + 22.5) % 360) // 45)],
            "constancia": float(const) if np.isfinite(const) else None}


def legenda_html(vmax: float, titulo: str) -> str:
    """Barra de cor contínua em CSS (mesma paleta do overlay)."""
    viz = CONFIG_CORRENTES_VIZ
    cmap = colormaps[viz["cmap"]]
    paradas = ", ".join(
        "#%02x%02x%02x" % tuple(int(c * 255) for c in cmap(t)[:3]) for t in np.linspace(0, 1, 6))
    f = lambda x: f"{x:.2f}".replace(".", ",")   # noqa: E731
    return (f'<div style="font-size:.85rem"><b>{titulo}</b>'
            f'<div style="height:12px;margin:6px 0 2px;border-radius:3px;'
            f'background:linear-gradient(to right,{paradas});"></div>'
            f'<div style="display:flex;justify-content:space-between;opacity:.85;">'
            f'<span>0</span><span>{f(vmax / 2)}</span><span>≥ {f(vmax)} m/s</span></div></div>')
