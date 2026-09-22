#!/usr/bin/env python3
"""
01_mapa_elevacao.py — Modelo Digital de Elevação da planície de Caravelas (BA)
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB

Primeira etapa do pipeline. Transforma os tiles brutos do FABDEM no raster
único que alimenta todo o resto do projeto, e produz o mapa base da entrega.

ENTRADA
    dados/fabdem/*.tif   tiles FABDEM V1-2 (ver instruções abaixo)

SAÍDA
    dados/processado/caravelas_fabdem_utm24s_30m.tif   MDE recortado, UTM 24S
    saidas/fig01_mapa_elevacao_<data>.png              mapa hipsométrico sombreado
    saidas/fig02_curva_hipsometrica_<data>.png         curva + histograma
    saidas/tabela_faixas_altimetricas_<data>.csv       área por faixa de cota

COMO OBTER OS TILES
    1. Abra a página do dataset (config.FABDEM_PAGINA), aceite a licença
       CC BY-NC-SA 4.0 e baixe o bloco S20W040-S10W030_FABDEM_V1-2.zip
    2. Extraia e copie para dados/fabdem/ apenas os tiles:
       S18W040, S18W039, S19W040, S19W039
    3. Rode:  python 01_mapa_elevacao.py

NOTA DE DATUM
    FABDEM: horizontal WGS84 / vertical EGM2008 (ortométrico, ~nível médio
    global). NÃO é o datum de maré local (NR da DHN). Até a amarração ao
    NR/NM de Caravelas, tratar a cota 0 como aproximação do nível médio.

    O FABDEM atribui 0.0 exato ao oceano. O script mascara isso, o que também
    apaga planícies de maré/manguezal legitimamente próximas de zero — mas
    quantificado (ver docs/diagnostico_zeros.md): apenas 1,00 km² (289
    manchas isoladas) dos 2.125,4 km² mascarados não tem conexão hidráulica
    com o oceano aberto. Limitação real, porém marginal (~0,05%), não uma
    incógnita. NÚMERO A REVALIDAR: foi calculado antes da mudança de ordem
    de operações descrita abaixo — a máscara agora captura mais água (rios
    estreitos), então a pegada mascarada cresce.

NOTA DE ORDEM DE OPERAÇÕES — rios estreitos (set/2026)
    A classificação "isto é água" roda ANTES da reprojeção, na grade nativa
    do FABDEM — não depois, como em versões anteriores. Reprojetar a
    elevação com bilinear e só então testar dem==0.0 apagava o 0.0 exato de
    qualquer canal mais estreito que a vizinhança do reamostrador: um rio de
    1 pixel de largura quase nunca sobrevive ao blend bilinear, porque ele
    mistura o valor do pixel de água com o dos vizinhos de terra. Isso fazia
    a grade de conectividade hidráulica não reconhecer rios/canais estreitos
    como água, mesmo quando o FABDEM os via como tal.

    Agora: `classificar_agua()` testa dem==0.0 no mosaico bruto (grade
    nativa, antes de reprojetar); `reprojetar()` leva essa máscara para a
    grade UTM com reamostragem `nearest` (categórica — preserva bordas, não
    borra), enquanto a elevação continua reprojetada com `bilinear`
    (contínua). Mesmo princípio já usado para a camada hipsométrica em
    `src/mapa_web.py`: classificar antes de reprojetar, para poder usar
    `nearest`. Limite real que continua existindo: canal mais estreito que
    ~30 m (a resolução nativa do FABDEM) nunca vira pixel de água — isso é
    limite do dado bruto, não desta pipeline.

Autor: Helio | Assistência: Claude
"""

from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import BoundaryNorm, ListedColormap
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.warp import calculate_default_transform, reproject

import config
from src.slr_core import CONFIG_MAPA, hillshade

# =============================================================================
# PARÂMETROS DO SCRIPT
# =============================================================================

CONFIG_01 = {
    "reamostragem":          Resampling.bilinear,  # MDE: elevação é contínua
    "reamostragem_mascara":  Resampling.nearest,    # água: classificação categórica
    "valor_oceano":          0.0,
    "tol_oceano":            1e-6,
    "nodata_saida":          -9999.0,
    "compressao":            "lzw",
    "percentil_teto":        99.5,   # corta outliers na escala de cor do mapa
    "z_min_plausivel":       -50.0,  # abaixo disto é sentinela de nodata, não terreno
    "z_max_plausivel":       9000.0,
    "dpi":                   300,
}


def _carimbo() -> str:
    return datetime.now().strftime("%Y%m%d")


# =============================================================================
# 1. MOSAICO E RECORTE
# =============================================================================

def mosaicar_e_recortar() -> tuple:
    """Lê os tiles FABDEM, mosaica e recorta ao BBOX. Retorna (array, transform)."""
    tiles = sorted(config.DIR_FABDEM.glob("*.tif"))
    if not tiles:
        raise FileNotFoundError(
            f"Nenhum .tif em {config.DIR_FABDEM}\n\n"
            f"Baixe o bloco {config.FABDEM_BLOCO} em:\n"
            f"  {config.FABDEM_PAGINA}\n"
            f"Extraia e copie para essa pasta os tiles: "
            f"{', '.join(config.TILES_NECESSARIOS)}"
        )

    print(f"[1/5] {len(tiles)} tile(s) na pasta")

    bbox = config.BBOX_WGS84
    limites = (bbox["lon_min"], bbox["lat_min"], bbox["lon_max"], bbox["lat_max"])

    # Só abre o que realmente intersecta o recorte. Permite deixar o bloco
    # FABDEM inteiro extraído em dados/fabdem/ sem custo de leitura.
    uteis = []
    for t in tiles:
        with rasterio.open(t) as src:
            b = src.bounds
        if (b.left < limites[2] and b.right > limites[0]
                and b.bottom < limites[3] and b.top > limites[1]):
            uteis.append(t)

    if not uteis:
        raise ValueError(
            f"Nenhum dos {len(tiles)} tiles intersecta o BBOX "
            f"{limites}. Esperados: {', '.join(config.TILES_NECESSARIOS)}"
        )
    print(f"[1/5] {len(uteis)} intersecta(m) o recorte: {[t.stem for t in uteis]}")

    abertos = [rasterio.open(t) for t in uteis]
    try:
        # Guarda o nodata declarado por cada tile antes de fechar os arquivos.
        valores_nodata = {src.nodata for src in abertos if src.nodata is not None}
        # nodata=np.nan preenche com NaN a área do BBOX sem cobertura de tile
        # (no nosso caso, o canto SE, sobre o mar, onde o FABDEM não tem tile).
        mosaico, transform = merge(abertos, bounds=limites, nodata=np.nan)
    finally:
        for src in abertos:
            src.close()

    dem = mosaico[0].astype("float32")

    # CRÍTICO: o sentinela de nodata dos tiles (tipicamente -9999) é um número
    # finito. Se não virar NaN aqui, ele passa pela reprojeção, entra em
    # `np.isfinite()` como se fosse terreno e contamina TODA a estatística de
    # área — inclusive "área abaixo da cota", já que -9999 <= qualquer cota.
    n_antes = int(np.isfinite(dem).sum())
    for valor in valores_nodata:
        if np.isfinite(valor):
            dem[dem == valor] = np.nan
    # Rede de segurança para sentinelas não declarados no perfil do tile.
    dem[(dem < CONFIG_01["z_min_plausivel"]) | (dem > CONFIG_01["z_max_plausivel"])] = np.nan

    n_nodata = n_antes - int(np.isfinite(dem).sum())
    if n_nodata:
        print(f"[1/5] {n_nodata} px de nodata convertidos para NaN "
              f"(sentinelas: {sorted(valores_nodata)})")
    print(f"[1/5] mosaico recortado: {dem.shape[0]}x{dem.shape[1]} px em "
          f"{config.CRS_FONTE}")
    return dem, transform


# =============================================================================
# 2. CLASSIFICAÇÃO DE ÁGUA (grade nativa, ANTES da reprojeção)
# =============================================================================

def classificar_agua(dem: np.ndarray) -> np.ndarray:
    """
    Marca como água (True) os pixels com elevação 0.0 exata — convenção do
    próprio FABDEM para oceano/estuário/corpo d'água.

    Roda na grade NATIVA do FABDEM (WGS84, ~30 m), antes de qualquer
    reprojeção. Fazer esse teste depois da reprojeção bilinear (como nas
    versões anteriores) borra o 0.0 exato em qualquer canal mais estreito
    que a vizinhança do reamostrador — um rio de 1 pixel de largura quase
    nunca sobrevive ao blend. `reprojetar()` leva esta máscara para a grade
    UTM com `nearest`, preservando os canais que sobreviverem aqui.

    Limite real: canal mais estreito que a resolução nativa do FABDEM
    (~30 m) nunca chega a virar pixel de água — isso é limite do dado
    bruto, não desta função.
    """
    mask = np.isclose(dem, CONFIG_01["valor_oceano"], atol=CONFIG_01["tol_oceano"],
                      equal_nan=False)
    print(f"[1/5] água classificada na grade nativa ({config.CRS_FONTE}): "
          f"{int(mask.sum())} px")
    return mask


# =============================================================================
# 3. REPROJEÇÃO PARA UTM 24S (MDE bilinear + máscara nearest)
# =============================================================================

def reprojetar(dem: np.ndarray, mask_agua: np.ndarray, transform) -> tuple:
    """
    Reprojeta para EPSG:31984 na resolução alvo. Retorna
    (dem_reprojetado, mask_agua_reprojetada, transform_alvo).

    O MDE usa `CONFIG_01["reamostragem"]` (bilinear — elevação é contínua).
    A máscara de água usa `CONFIG_01["reamostragem_mascara"]` (nearest —
    é uma classificação categórica; misturá-la com os vizinhos como se
    fosse elevação contínua é o que apagava os canais estreitos nas
    versões anteriores, que só testavam dem==0.0 depois do bilinear). As
    duas saem na MESMA grade de destino, então continuam alinhadas pixel a
    pixel.
    """
    altura, largura = dem.shape
    bbox = config.BBOX_WGS84

    transform_alvo, larg_alvo, alt_alvo = calculate_default_transform(
        config.CRS_FONTE, config.CRS_ALVO, largura, altura,
        left=bbox["lon_min"], bottom=bbox["lat_min"],
        right=bbox["lon_max"], top=bbox["lat_max"],
        resolution=config.RESOLUCAO_M,
    )

    dem_alvo = np.full((alt_alvo, larg_alvo), np.nan, dtype="float32")
    reproject(
        source=dem, destination=dem_alvo,
        src_transform=transform, src_crs=config.CRS_FONTE,
        dst_transform=transform_alvo, dst_crs=config.CRS_ALVO,
        src_nodata=np.nan, dst_nodata=np.nan,
        resampling=CONFIG_01["reamostragem"],
    )

    mask_alvo_u8 = np.zeros((alt_alvo, larg_alvo), dtype="uint8")
    reproject(
        source=mask_agua.astype("uint8"), destination=mask_alvo_u8,
        src_transform=transform, src_crs=config.CRS_FONTE,
        dst_transform=transform_alvo, dst_crs=config.CRS_ALVO,
        resampling=CONFIG_01["reamostragem_mascara"],
    )
    mask_alvo = mask_alvo_u8.astype(bool)

    print(f"[2/5] reprojetado para {config.CRS_ALVO}: "
          f"{alt_alvo}x{larg_alvo} px @ {config.RESOLUCAO_M:.0f} m "
          f"(MDE=bilinear, água=nearest)")
    print(f"[2/5] água após reprojeção: {int(mask_alvo.sum())} px "
          f"(antes, grade nativa: {int(mask_agua.sum())} px)")
    return dem_alvo, mask_alvo, transform_alvo


# =============================================================================
# 4. APLICAÇÃO DA MÁSCARA E GRAVAÇÃO
# =============================================================================

def _exportar_mascara_agua(mask_oceano: np.ndarray, transform) -> None:
    """
    Grava a máscara de água (uint8, 1=água, 0=terra) na mesma grade do MDE.

    Existe porque `mascarar_e_salvar` converte pixels de água em NaN e, na
    escrita, em nodata (-9999) — igual ao sentinela usado para "fora do
    bbox, sem tile". O MDE_PROCESSADO sozinho não permite mais distinguir
    as duas coisas; esta máscara preserva a identidade "isto era água"
    classificada na grade nativa (`classificar_agua`) e levada para cá por
    `nearest` (`reprojetar`) — antes desse round-trip apagar o valor 0.0
    exato.
    """
    perfil = {
        "driver": "GTiff", "height": mask_oceano.shape[0], "width": mask_oceano.shape[1],
        "count": 1, "dtype": "uint8", "crs": config.CRS_ALVO,
        "transform": transform, "nodata": None,
        "compress": CONFIG_01["compressao"], "tiled": True,
    }
    with rasterio.open(config.MASCARA_AGUA, "w", **perfil) as dst:
        dst.write(mask_oceano.astype("uint8"), 1)
        dst.update_tags(
            descricao=("1=agua (oceano/estuario/corpo d'agua; dem==0.0 exato no "
                       "FABDEM, classificado na grade nativa ANTES da reprojecao "
                       "e levado por nearest), 0=terra"),
            gerado_em=datetime.now().isoformat(timespec="seconds"),
        )
    print(f"[3/5] máscara de água salva: {config.MASCARA_AGUA} "
          f"({int(mask_oceano.sum())} px de água)")


def mascarar_e_salvar(dem: np.ndarray, mask_oceano: np.ndarray, transform) -> np.ndarray:
    """
    Aplica a máscara de água (já classificada na grade nativa e reprojetada
    por `reprojetar` com `nearest`) como NaN e grava o GeoTIFF processado.
    """
    dem = dem.copy()
    dem[mask_oceano] = np.nan

    n_terra = int(np.isfinite(dem).sum())
    area_px = config.RESOLUCAO_M ** 2 / 1e6
    print(f"[3/5] água mascarada: {int(mask_oceano.sum())} px | "
          f"terra: {n_terra} px ({n_terra * area_px:.1f} km²)")

    # Se algum sentinela escapou, TODA a estatística de área fica errada.
    # Melhor falhar aqui do que publicar tabela com número inflado.
    z_min = float(np.nanmin(dem))
    if z_min < CONFIG_01["z_min_plausivel"]:
        raise ValueError(
            f"Elevação mínima implausível ({z_min:.2f} m). Provável nodata "
            f"não mascarado contaminando o raster — não prossiga com a análise."
        )
    print(f"[3/5] z: min={np.nanmin(dem):.2f} | mediana={np.nanmedian(dem):.2f} | "
          f"p99={np.nanpercentile(dem, 99):.2f} | max={np.nanmax(dem):.2f} m")

    config.DIR_PROCESSADO.mkdir(parents=True, exist_ok=True)
    saida = np.where(np.isfinite(dem), dem, CONFIG_01["nodata_saida"]).astype("float32")

    perfil = {
        "driver": "GTiff", "height": dem.shape[0], "width": dem.shape[1],
        "count": 1, "dtype": "float32", "crs": config.CRS_ALVO,
        "transform": transform, "nodata": CONFIG_01["nodata_saida"],
        "compress": CONFIG_01["compressao"], "tiled": True,
    }
    with rasterio.open(config.MDE_PROCESSADO, "w", **perfil) as dst:
        dst.write(saida, 1)
        dst.update_tags(
            fonte="FABDEM V1-2 (Hawker et al. 2022, ERL 17:024016)",
            licenca="CC BY-NC-SA 4.0",
            datum_vertical="EGM2008",
            oceano="pixels 0.0 exatos mascarados (classificados na grade nativa)",
            gerado_em=datetime.now().isoformat(timespec="seconds"),
        )
    print(f"[3/5] MDE salvo: {config.MDE_PROCESSADO}")

    _exportar_mascara_agua(mask_oceano, transform)

    return dem


# =============================================================================
# 5. MAPA HIPSOMÉTRICO
# =============================================================================

def figura_mapa(dem: np.ndarray) -> str:
    """Mapa de elevação classificado, com relevo sombreado exagerado."""
    faixas = config.FAIXAS_ALTIMETRICAS
    cmap = ListedColormap(config.CORES_FAIXAS[:len(faixas) - 1])
    norm = BoundaryNorm(faixas, cmap.N)

    hs = hillshade(dem, config.RESOLUCAO_M)

    fig, ax = plt.subplots(figsize=(11, 9), constrained_layout=True)
    ax.set_facecolor("#0B3D5C")

    rgb = cmap(norm(np.nan_to_num(dem)))
    rgb[..., :3] *= (0.35 + 0.65 * hs)[..., None]
    rgb[..., 3] = np.isfinite(dem).astype(float)
    ax.imshow(rgb, interpolation="nearest")

    barra = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap),
                         ax=ax, ticks=faixas, shrink=0.75, pad=0.01)
    barra.set_label("Elevação (m, EGM2008)", fontsize=9)

    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title("Planície costeira de Caravelas (BA) — modelo digital de terreno",
                 fontsize=13, weight="bold", loc="left", pad=22)
    ax.text(0, 1.010,
            f"FABDEM V1-2 · {config.CRS_ALVO} @ {config.RESOLUCAO_M:.0f} m · "
            f"exagero vertical {CONFIG_MAPA['exagero_vertical']}x no sombreamento",
            transform=ax.transAxes, fontsize=9, va="bottom", color="#444444")

    ax.annotate("N", xy=(0.965, 0.955), xytext=(0.965, 0.875),
                xycoords="axes fraction", ha="center", fontsize=11, weight="bold",
                arrowprops=dict(arrowstyle="-|>", color="k", lw=1.6))

    n_px = 5000 / config.RESOLUCAO_M
    x0 = dem.shape[1] * 0.06
    y0 = dem.shape[0] * 0.94
    ax.plot([x0, x0 + n_px], [y0, y0], color="k", lw=3, solid_capstyle="butt")
    ax.text(x0 + n_px / 2, y0, "5 km", ha="center", va="bottom", fontsize=8,
            bbox=dict(fc="white", ec="none", alpha=0.75, pad=1.5))

    config.DIR_SAIDAS.mkdir(parents=True, exist_ok=True)
    caminho = config.DIR_SAIDAS / f"fig01_mapa_elevacao_{_carimbo()}.png"
    fig.savefig(caminho, dpi=CONFIG_01["dpi"], bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[4/5] figura salva: {caminho}")
    return str(caminho)


# =============================================================================
# 6. CURVA HIPSOMÉTRICA E TABELA
# =============================================================================

def curva_e_tabela(dem: np.ndarray) -> str:
    """Curva hipsométrica acumulada, histograma e tabela de faixas."""
    z = dem[np.isfinite(dem)]
    area_px = config.RESOLUCAO_M ** 2 / 1e6
    area_total = z.size * area_px

    cotas = np.arange(0, 12.01, 0.05)
    acumulada = np.array([(z <= c).sum() for c in cotas]) * area_px

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5), constrained_layout=True)

    ax1.plot(cotas, acumulada, color="#08306b", lw=2)
    ax1.fill_between(cotas, 0, acumulada, color="#4292c6", alpha=0.3)
    for nivel, cor in zip([0.5, 1.0, 2.0], ["#2C7BB6", "#FDAE61", "#D7191C"]):
        a = (z <= nivel).sum() * area_px
        ax1.axvline(nivel, color=cor, ls="--", lw=1.2)
        ax1.annotate(f"+{nivel:g} m\n{a:.1f} km² ({100*a/area_total:.1f}%)",
                     xy=(nivel, a), xytext=(nivel + 0.35, a),
                     fontsize=8, color=cor, va="center")
    ax1.set_xlabel("Cota (m, EGM2008)")
    ax1.set_ylabel("Área abaixo da cota (km²)")
    ax1.set_title("Curva hipsométrica acumulada", fontsize=11, weight="bold")
    ax1.grid(alpha=0.25)

    ax2.hist(z[z <= 20], bins=120, color="#31a354", edgecolor="none")
    ax2.set_xlabel("Elevação (m)")
    ax2.set_ylabel("Nº de pixels")
    ax2.set_title("Distribuição altimétrica (0–20 m)", fontsize=11, weight="bold")
    ax2.grid(alpha=0.25)

    caminho_fig = config.DIR_SAIDAS / f"fig02_curva_hipsometrica_{_carimbo()}.png"
    fig.savefig(caminho_fig, dpi=CONFIG_01["dpi"], bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[5/5] figura salva: {caminho_fig}")

    faixas = config.FAIXAS_ALTIMETRICAS
    linhas = []
    for i in range(len(faixas) - 1):
        lo, hi = faixas[i], faixas[i + 1]
        n = int(((z >= lo) & (z < hi)).sum())
        linhas.append({
            "Faixa (m)": f"{lo:g} – {hi:g}",
            "Área (km²)": round(n * area_px, 3),
            "% da área emersa": round(100 * n * area_px / area_total, 2),
        })
    df = pd.DataFrame(linhas)
    caminho_csv = config.DIR_SAIDAS / f"tabela_faixas_altimetricas_{_carimbo()}.csv"
    df.to_csv(caminho_csv, index=False, encoding="utf-8-sig")
    print(f"[5/5] tabela salva: {caminho_csv}")
    print(df.to_string(index=False))
    return str(caminho_csv)


# =============================================================================
# EXECUÇÃO
# =============================================================================

def main():
    print("=" * 72)
    print("MDE — Planície costeira de Caravelas (BA) | FABDEM V1-2")
    print("=" * 72)
    config.criar_estrutura()

    dem, transform = mosaicar_e_recortar()
    mask_agua = classificar_agua(dem)
    dem, mask_agua, transform = reprojetar(dem, mask_agua, transform)
    dem = mascarar_e_salvar(dem, mask_agua, transform)
    figura_mapa(dem)
    curva_e_tabela(dem)

    print("=" * 72)
    print("Concluído. Próximo passo:  streamlit run 02_simulador_nmrm.py")
    print("=" * 72)


if __name__ == "__main__":
    main()
