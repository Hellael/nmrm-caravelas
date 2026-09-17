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
    incógnita.

NOTA DE MÁSCARA DE ÁGUA (v1.4)
    A detecção do 0.0 exato do FABDEM é feita na GRADE NATIVA (WGS84), logo
    após o mosaico — antes de qualquer reamostragem. Fazer esse teste depois
    do bilinear (como a v1.3 fazia) mistura o 0.0 da água com a cota da
    margem na interpolação, e o pixel deixa de ser exatamente 0.0: a máscara
    perde ~1 px em toda margem e canais de 1-2 px de largura somem por
    completo. Aqui a água vira NaN ANTES da reprojeção (então o bilinear do
    terreno nunca a enxerga).

NOTA DE DUAS MÁSCARAS — ÁREA x CONEXÃO (v1.4b)
    A água nativa é reprojetada DUAS vezes, com propósitos diferentes:

      agua_area    : Resampling.average sobre a máscara em float32 (0.0/1.0),
                     testada contra CONFIG_01["limiar_agua_area"] (0.5). Só
                     sai da terra o pixel cuja MAIORIA da área é água de
                     verdade — é o que mascara o DEM e vira config.MASCARA_AGUA.
      agua_conexao : Resampling.max (CONFIG_01["reamostragem_agua"]). Qualquer
                     fração de água já conta para fins de CONEXÃO.

    A diferença `agua_conexao & ~agua_area` é a MARGEM: pixel que fica como
    TERRA na área (o DEM preserva a cota real), mas tem água real suficiente
    para conduzir a conexão hidráulica. Grava-se em config.MASCARA_MARGEM e
    soma-se ao caminho hidráulico em slr_core.mascara_caminho (mesmas regras
    do canal MapBiomas — conduz, não é fonte — mas SEM a salvaguarda de cota,
    porque aqui é água real medida no próprio FABDEM, não uma classe de
    cobertura que pode estar longe do mar).

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
    "reamostragem":     Resampling.bilinear,
    # A máscara de água é CATEGÓRICA (0/1), não uma grandeza contínua como o
    # terreno. `max` em vez de `nearest`/`bilinear`: qualquer fração de água
    # dentro do pixel de 30 m de destino marca o pixel inteiro como água —
    # é a escolha conservadora para não fechar em silêncio um canal estreito
    # que caiu exatamente na fronteira de dois pixels da grade nativa.
    "reamostragem_agua": Resampling.max,
    # Limiar da reprojeção por Resampling.average (fração de água no pixel de
    # 30 m) que decide se o pixel SAI da terra e vira config.MASCARA_AGUA.
    # 0.5 = maioria da área. Abaixo disso, se ainda houver água (agua_conexao),
    # o pixel vira MARGEM: fica terra, mas conduz conexão. Ver a nota de
    # "duas máscaras" no topo do arquivo.
    "limiar_agua_area": 0.5,
    "valor_oceano":     0.0,
    "tol_oceano":       1e-6,
    "nodata_saida":     -9999.0,
    "compressao":       "lzw",
    "percentil_teto":   99.5,   # corta outliers na escala de cor do mapa
    "z_min_plausivel":  -50.0,  # abaixo disto é sentinela de nodata, não terreno
    "z_max_plausivel":  9000.0,
    "dpi":              300,
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
# 2. MÁSCARA DE ÁGUA NA GRADE NATIVA + REPROJEÇÃO PARA UTM 24S
# =============================================================================

def detectar_agua_nativa(dem: np.ndarray) -> np.ndarray:
    """
    Água (oceano/estuário) do FABDEM: pixel 0.0 exato, testado NA GRADE
    NATIVA (WGS84), antes de qualquer reamostragem — ver "NOTA DE MÁSCARA DE
    ÁGUA" no topo do arquivo.
    """
    return np.isclose(dem, CONFIG_01["valor_oceano"],
                      atol=CONFIG_01["tol_oceano"], equal_nan=False)


def _reprojetar_array(dem: np.ndarray, transform, resampling) -> tuple:
    """Núcleo da reprojeção do terreno, sem print — reaproveitado por
    `reprojetar()` e pelo diagnóstico do método antigo (só para o print de
    comparação de área de água, não entra em nenhum cálculo)."""
    altura, largura = dem.shape
    bbox = config.BBOX_WGS84

    transform_alvo, larg_alvo, alt_alvo = calculate_default_transform(
        config.CRS_FONTE, config.CRS_ALVO, largura, altura,
        left=bbox["lon_min"], bottom=bbox["lat_min"],
        right=bbox["lon_max"], top=bbox["lat_max"],
        resolution=config.RESOLUCAO_M,
    )

    destino = np.full((alt_alvo, larg_alvo), np.nan, dtype="float32")
    reproject(
        source=dem, destination=destino,
        src_transform=transform, src_crs=config.CRS_FONTE,
        dst_transform=transform_alvo, dst_crs=config.CRS_ALVO,
        src_nodata=np.nan, dst_nodata=np.nan,
        resampling=resampling,
    )
    return destino, transform_alvo


def reprojetar(dem: np.ndarray, transform) -> tuple:
    """Reprojeta o terreno para EPSG:31984 na resolução alvo (bilinear).
    Retorna (array, transform). Chamar com a água já zerada para NaN."""
    destino, transform_alvo = _reprojetar_array(dem, transform, CONFIG_01["reamostragem"])
    print(f"[2/5] reprojetado para {config.CRS_ALVO}: "
          f"{destino.shape[0]}x{destino.shape[1]} px @ {config.RESOLUCAO_M:.0f} m")
    return destino, transform_alvo


def reprojetar_mascaras_agua(mascara_nativa: np.ndarray, transform_nativa,
                             transform_alvo, shape_alvo: tuple) -> tuple:
    """
    Reprojeta a água nativa (grade WGS84) para a grade UTM do terreno DUAS
    vezes, com propósitos diferentes — ver "NOTA DE DUAS MÁSCARAS" no topo
    do arquivo:

        agua_area    : Resampling.average sobre a máscara em float32, testada
                       contra CONFIG_01["limiar_agua_area"] (0.5). Conservador
                       — só sai da terra o pixel cuja MAIORIA da área é água.
        agua_conexao : Resampling.max (CONFIG_01["reamostragem_agua"]).
                       Qualquer fração de água já conta para conexão.
        agua_margem  : agua_conexao & ~agua_area — fica como terra na área,
                       mas conduz conexão hidráulica (vira "caminho").

    Reaproveita `transform_alvo`/`shape_alvo` já calculados pela reprojeção
    do terreno — mesma grade exata, sem recomputar `calculate_default_transform`.

    NÃO passar `dst_nodata` aqui: com `src_nodata=None`, declarar `dst_nodata`
    faz o GDAL tratar esse valor como nodata também na leitura/reamostragem —
    em `Resampling.max`/`average`/`nearest` isso corrompe o resultado
    (testado: praticamente todo pixel de destino virava "água", mesmo com a
    fonte majoritariamente 0). Como todo pixel de origem já é 0.0 ou 1.0
    (nunca "sem dado"), não existe nodata real a declarar; os arrays de
    destino já nascem zerados, que é o preenchimento correto fora do domínio.
    """
    fracao = np.zeros(shape_alvo, dtype="float32")
    reproject(
        source=mascara_nativa.astype("float32"), destination=fracao,
        src_transform=transform_nativa, src_crs=config.CRS_FONTE,
        dst_transform=transform_alvo, dst_crs=config.CRS_ALVO,
        resampling=Resampling.average,
    )
    agua_area = fracao >= CONFIG_01["limiar_agua_area"]

    destino_max = np.zeros(shape_alvo, dtype="uint8")
    reproject(
        source=mascara_nativa.astype("uint8"), destination=destino_max,
        src_transform=transform_nativa, src_crs=config.CRS_FONTE,
        dst_transform=transform_alvo, dst_crs=config.CRS_ALVO,
        resampling=CONFIG_01["reamostragem_agua"],
    )
    agua_conexao = destino_max.astype(bool)

    agua_margem = agua_conexao & ~agua_area

    print(f"[2/5] agua_area (average >= {CONFIG_01['limiar_agua_area']:.2f}): "
          f"{int(agua_area.sum())} px na grade UTM")
    print(f"[2/5] agua_conexao (Resampling.max): {int(agua_conexao.sum())} px na grade UTM")
    print(f"[2/5] agua_margem (conexao & ~area): {int(agua_margem.sum())} px na grade UTM "
          "— fica terra na área, conduz conexão")

    return agua_area, agua_conexao, agua_margem


# =============================================================================
# 3. MÁSCARA DE OCEANO E GRAVAÇÃO
# =============================================================================

def _exportar_mascara_agua(agua_area: np.ndarray, transform) -> None:
    """
    Grava a máscara de água DE ÁREA (uint8, 1=água, 0=terra) na mesma grade
    do MDE — a que decide o que sai da terra e vira nodata no MDE_PROCESSADO.

    Existe porque `mascarar_e_salvar` converte pixels de água em NaN e, na
    escrita, em nodata (-9999) — igual ao sentinela usado para "fora do
    bbox, sem tile". O MDE_PROCESSADO sozinho não permite mais distinguir
    as duas coisas; esta máscara preserva a identidade "isto era água".

    Recebida já PRONTA (`agua_area` de `reprojetar_mascaras_agua`: reamostragem
    `Resampling.average` sobre a água nativa, testada contra o limiar de 0.5).
    """
    perfil = {
        "driver": "GTiff", "height": agua_area.shape[0], "width": agua_area.shape[1],
        "count": 1, "dtype": "uint8", "crs": config.CRS_ALVO,
        "transform": transform, "nodata": None,
        "compress": CONFIG_01["compressao"], "tiled": True,
    }
    with rasterio.open(config.MASCARA_AGUA, "w", **perfil) as dst:
        dst.write(agua_area.astype("uint8"), 1)
        dst.update_tags(
            descricao=(
                "1=agua (oceano/estuario/corpo d'agua, dem==0.0 exato no FABDEM), "
                "0=terra. Detectada na grade NATIVA (WGS84), antes da reprojecao, "
                "e reamostrada para a grade UTM com Resampling.average, limiar "
                f">= {CONFIG_01['limiar_agua_area']:.2f} da fracao de agua no "
                "pixel de 30 m (agua_area). Pixels com menos agua que isso mas "
                "ainda com alguma ficam na margem — ver caravelas_mascara_margem_*."
            ),
            gerado_em=datetime.now().isoformat(timespec="seconds"),
        )
    print(f"[3/5] máscara de água salva: {config.MASCARA_AGUA} "
          f"({int(agua_area.sum())} px de água)")


def _exportar_mascara_margem(agua_margem: np.ndarray, transform) -> None:
    """
    Grava a máscara de MARGEM d'água (uint8, 1=margem, 0=demais) — pixels que
    NÃO entraram em agua_area (ficam como terra, com a cota real do MDE) mas
    têm água real suficiente (Resampling.max) para conduzir a conexão
    hidráulica. Consumida por `03_prepara_dem_web.py` e por
    `slr_core.mascara_caminho`: soma-se ao caminho por canal MapBiomas, com
    as mesmas regras (conduz, nunca é fonte), mas SEM a salvaguarda de cota
    do canal — é água real medida no próprio FABDEM, não uma classe de
    cobertura que pode estar longe do mar.
    """
    perfil = {
        "driver": "GTiff", "height": agua_margem.shape[0], "width": agua_margem.shape[1],
        "count": 1, "dtype": "uint8", "crs": config.CRS_ALVO,
        "transform": transform, "nodata": None,
        "compress": CONFIG_01["compressao"], "tiled": True,
    }
    with rasterio.open(config.MASCARA_MARGEM, "w", **perfil) as dst:
        dst.write(agua_margem.astype("uint8"), 1)
        dst.update_tags(
            descricao=(
                "1=margem d'agua (agua_conexao & ~agua_area): fica como terra "
                "na area (dem preserva a cota real) mas conduz conexao "
                "hidraulica em slr_core.mascara_caminho. 0=demais."
            ),
            gerado_em=datetime.now().isoformat(timespec="seconds"),
        )
    print(f"[3/5] máscara de margem salva: {config.MASCARA_MARGEM} "
          f"({int(agua_margem.sum())} px de margem)")


def mascarar_e_salvar(dem: np.ndarray, agua_area: np.ndarray, agua_margem: np.ndarray,
                      transform, agua_antiga_diagnostico: np.ndarray = None,
                      agua_conexao_diagnostico: np.ndarray = None) -> np.ndarray:
    """
    Aplica `agua_area` (já pronta — ver `reprojetar_mascaras_agua`) e grava o
    GeoTIFF processado, mais as duas máscaras (área e margem).

    `agua_antiga_diagnostico`: máscara pelo método antigo (isclose pós-bilinear
    da v1.3), só para o print comparativo. `agua_conexao_diagnostico`: a
    máscara por Resampling.max (antes de subtrair a área), idem — nenhum dos
    dois participa de cálculo.
    """
    dem = dem.copy()
    # Coerência: um pixel nunca é terra e água ao mesmo tempo — a MARGEM fica
    # como terra de propósito (só conduz conexão, não sai da área).
    dem[agua_area] = np.nan

    n_terra = int(np.isfinite(dem).sum())
    area_px = config.RESOLUCAO_M ** 2 / 1e6
    print(f"[3/5] agua_area mascarada: {int(agua_area.sum())} px | "
          f"terra: {n_terra} px ({n_terra * area_px:.1f} km²)")
    print(f"[3/5] agua_margem (fica terra na área, conduz conexão): "
          f"{int(agua_margem.sum())} px ({int(agua_margem.sum()) * area_px:.2f} km²)")

    if agua_antiga_diagnostico is not None:
        n_antiga = int(agua_antiga_diagnostico.sum())
        n_area = int(agua_area.sum())
        ganho_area = n_area - n_antiga
        print(f"[3/5] agua_area: antiga={n_antiga} px | nova={n_area} px | "
              f"ganho=+{ganho_area} px ({ganho_area * area_px:.2f} km²)")
        if agua_conexao_diagnostico is not None:
            n_conexao = int(agua_conexao_diagnostico.sum())
            ganho_conexao = n_conexao - n_antiga
            print(f"[3/5] agua_conexao: antiga={n_antiga} px | nova={n_conexao} px | "
                  f"ganho=+{ganho_conexao} px ({ganho_conexao * area_px:.2f} km²)")

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
            oceano="pixels de agua_area (deteccao na grade nativa) mascarados",
            gerado_em=datetime.now().isoformat(timespec="seconds"),
        )
    print(f"[3/5] MDE salvo: {config.MDE_PROCESSADO}")

    _exportar_mascara_agua(agua_area, transform)
    _exportar_mascara_margem(agua_margem, transform)

    return dem


# =============================================================================
# 4. MAPA HIPSOMÉTRICO
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
# 5. CURVA HIPSOMÉTRICA E TABELA
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

    # Água detectada NA GRADE NATIVA, antes de qualquer reamostragem — ver
    # "NOTA DE MÁSCARA DE ÁGUA" no topo do arquivo.
    agua_nativa = detectar_agua_nativa(dem)
    print(f"[2/5] água nativa (grade WGS84, pré-reprojeção): "
          f"{int(agua_nativa.sum())} px")
    dem_sem_agua = dem.copy()
    dem_sem_agua[agua_nativa] = np.nan

    dem_utm, transform_utm = reprojetar(dem_sem_agua, transform)
    agua_area, agua_conexao, agua_margem = reprojetar_mascaras_agua(
        agua_nativa, transform, transform_utm, dem_utm.shape)

    # Diagnóstico: reproduz o método antigo (isclose pós-bilinear, com a água
    # ainda em 0.0 no momento de reprojetar) só para o print de comparação —
    # não entra em nenhum cálculo daqui em diante.
    dem_utm_antigo, _ = _reprojetar_array(dem, transform, CONFIG_01["reamostragem"])
    agua_antiga = np.isclose(dem_utm_antigo, CONFIG_01["valor_oceano"],
                             atol=CONFIG_01["tol_oceano"], equal_nan=False)

    dem = mascarar_e_salvar(dem_utm, agua_area, agua_margem, transform_utm,
                            agua_antiga_diagnostico=agua_antiga,
                            agua_conexao_diagnostico=agua_conexao)
    figura_mapa(dem)
    curva_e_tabela(dem)

    print("=" * 72)
    print("Concluído. Próximo passo:  streamlit run 02_simulador_nmrm.py")
    print("=" * 72)


if __name__ == "__main__":
    main()
