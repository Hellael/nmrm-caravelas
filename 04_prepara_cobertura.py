#!/usr/bin/env python3
"""
04_prepara_cobertura.py — Recorte do MapBiomas Coleção 11 para Caravelas
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB — Caravelas (BA)

Substitui o exploratório `abrir_tiff_mapbiomas.py` e passa a ser a etapa
oficial do pipeline: 01 (elevação) -> 03 (dados leves) -> 04 (cobertura).

O QUE FAZ
    1. Lê do GeoTIFF nacional do MapBiomas (vários GB) apenas a janela que
       cobre o BBOX de Caravelas, sem carregar o arquivo inteiro.
    2. Reprojeta essa janela para a grade do projeto com reamostragem NEAREST.
    3. ALINHA o resultado, pixel a pixel, à grade do MDE de referência — o
       produto do 01 no modo local e/ou o `dados_web/dem_30m_web.tif`. Sem
       esse alinhamento a camada de cobertura fica meio pixel deslocada da
       máscara de inundação, e o cruzamento da Parte 2 nasce torto.
    4. Grava GeoTIFF(s) e uma figura de conferência com a LEGENDA OFICIAL
       (nome e cor de classe vindos de `src/cobertura.py`).

SAÍDAS
    dados/auxiliar/caravelas_mapbiomas_col11_2025_utm24s_30m.tif   (modo local)
    dados_web/cobertura_web.tif                                    (ferramenta pública)
    saidas/fig_cobertura_mapbiomas_col11_<data>.png
    saidas/cobertura_classes_col11_<data>.csv

USO
    python 04_prepara_cobertura.py      (lê DIR_AUXILIAR / config.ARQ_MAPBIOMAS_NACIONAL)
    python 04_prepara_cobertura.py "D:\\outro\\brazil_coverage-col11_2025.tif"

NOTA CIENTÍFICA
    Cobertura é dado CATEGÓRICO. Toda reamostragem aqui é `nearest`; bilinear
    ou cúbica misturariam códigos de classes vizinhas e criariam classes que
    não existem (média entre 5=Mangue e 33=Rio não é classe nenhuma).

Autor: Helio | Assistência: Claude
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.patches import Patch
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject, transform_bounds
from rasterio.windows import from_bounds

import config
import src.cobertura as cob

# =============================================================================
# PARÂMETROS DO SCRIPT
# =============================================================================

CONFIG_PREPARA = {
    "arq_saida_local": "caravelas_mapbiomas_col11_2025_utm24s_30m.tif",
    "arq_saida_web":   "cobertura_web.tif",
    "dir_web":         "dados_web",
    "dem_web":         "dem_30m_web.tif",
    "dtype_saida":     "uint8",
    "reamostragem":    Resampling.nearest,   # categórico — NUNCA bilinear/cúbica
    "compressao":      "DEFLATE",
    "predictor":       2,
    "nivel_zlib":      9,
    "tamanho_bloco":   512,
    "dpi_figura":      200,
}


def _carimbo() -> str:
    return datetime.now().strftime("%Y%m%d")


def _resolver_entrada(argumento: str = None) -> Path:
    if argumento:
        caminho = Path(argumento)
        if not caminho.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")
        return caminho
    # Um lugar só (sem varredura silenciosa): DIR_AUXILIAR / ARQ_MAPBIOMAS_NACIONAL.
    caminho = config.DIR_AUXILIAR / config.ARQ_MAPBIOMAS_NACIONAL
    if not caminho.exists():
        raise FileNotFoundError(
            f"GeoTIFF nacional do MapBiomas não encontrado em:\n  {caminho}\n"
            f"Esse caminho vem de config.DIR_AUXILIAR, que segue a variável de ambiente "
            f"NMRM_DIR_DADOS (valor atual: {os.environ.get('NMRM_DIR_DADOS') or 'não definida'}; "
            f"sem ela, dados/ dentro do repositório).\n"
            f"Coloque o arquivo lá ou passe o caminho como argumento: "
            f"python 04_prepara_cobertura.py <caminho>"
        )
    return caminho


# =============================================================================
# 1. GRADES DE REFERÊNCIA
# =============================================================================

def grades_alvo() -> list[dict]:
    """
    Lista as grades para as quais vale gerar recorte, cada uma com o caminho
    de saída correspondente. Uma grade = (transform, largura, altura, crs).

    Se nenhum MDE existir, cai numa grade calculada do BBOX — serve para
    conferir a legenda, mas NÃO alinha com nada e não deve alimentar cruzamento.
    """
    alvos = []

    if Path(config.MDE_PROCESSADO).exists():
        with rasterio.open(config.MDE_PROCESSADO) as ref:
            alvos.append({
                "rotulo": "grade do MDE local (produto do 01)",
                "transform": ref.transform, "largura": ref.width,
                "altura": ref.height, "crs": ref.crs,
                "saida": config.DIR_AUXILIAR / CONFIG_PREPARA["arq_saida_local"],
                "alinhado": True,
            })

    dem_web = config.DIR_RAIZ / CONFIG_PREPARA["dir_web"] / CONFIG_PREPARA["dem_web"]
    if dem_web.exists():
        with rasterio.open(dem_web) as ref:
            alvos.append({
                "rotulo": "grade dos dados leves (dados_web)",
                "transform": ref.transform, "largura": ref.width,
                "altura": ref.height, "crs": ref.crs,
                "saida": dem_web.parent / CONFIG_PREPARA["arq_saida_web"],
                "alinhado": True,
            })

    if not alvos:
        bbox = config.BBOX_WGS84
        transform, larg, alt = calculate_default_transform(
            config.CRS_FONTE, config.CRS_ALVO, 1, 1,
            left=bbox["lon_min"], bottom=bbox["lat_min"],
            right=bbox["lon_max"], top=bbox["lat_max"],
            resolution=config.RESOLUCAO_M,
        )
        alvos.append({
            "rotulo": "grade calculada do BBOX (SEM MDE de referência)",
            "transform": transform, "largura": larg, "altura": alt,
            "crs": rasterio.crs.CRS.from_string(config.CRS_ALVO),
            "saida": config.DIR_AUXILIAR / CONFIG_PREPARA["arq_saida_local"],
            "alinhado": False,
        })
        print("[GRADE] AVISO: nenhum MDE encontrado. O recorte sai numa grade "
              "própria e NÃO está alinhado pixel a pixel com a simulação.")

    return alvos


# =============================================================================
# 2. LEITURA POR JANELA DO RASTER NACIONAL
# =============================================================================

def ler_janela(caminho: Path) -> tuple:
    """Lê só a janela que cobre o BBOX do projeto, com uma folga de segurança."""
    bbox = config.BBOX_WGS84
    with rasterio.open(caminho) as src:
        print(f"[1/5] {caminho.name} | {src.width}x{src.height} px | "
              f"dtype={src.dtypes[0]} | CRS={src.crs.to_string()}")

        esquerda, baixo, direita, cima = transform_bounds(
            config.CRS_FONTE, src.crs,
            bbox["lon_min"], bbox["lat_min"], bbox["lon_max"], bbox["lat_max"],
        )
        # Folga de 1 km em graus (~0,01°): a grade de destino pode pedir
        # pixel um pouco além da borda do BBOX, e sem folga a reprojeção
        # devolveria nodata numa faixa fina da margem.
        folga = 0.01
        janela = from_bounds(esquerda - folga, baixo - folga,
                             direita + folga, cima + folga,
                             transform=src.transform)
        janela = janela.round_offsets().round_lengths()

        nodata = src.nodata if src.nodata is not None else cob.CONFIG_COBERTURA["nodata"]
        if src.nodata is None:
            print(f"[1/5] raster não declara nodata — assumindo {nodata} "
                  "(convenção MapBiomas)")

        dado = src.read(1, window=janela, boundless=True, fill_value=nodata)
        transform_janela = src.window_transform(janela)
        crs_fonte = src.crs

    n_valido = int((dado != nodata).sum())
    print(f"[2/5] janela lida: {dado.shape[0]}x{dado.shape[1]} px | "
          f"{n_valido} px com classe válida")
    return dado, transform_janela, crs_fonte, nodata


# =============================================================================
# 3. REPROJEÇÃO ALINHADA + GRAVAÇÃO
# =============================================================================

def reprojetar_para(dado, transform, crs_fonte, nodata, alvo: dict) -> np.ndarray:
    destino = np.full((alvo["altura"], alvo["largura"]), nodata,
                      dtype=CONFIG_PREPARA["dtype_saida"])
    reproject(
        source=dado, destination=destino,
        src_transform=transform, src_crs=crs_fonte,
        dst_transform=alvo["transform"], dst_crs=alvo["crs"],
        src_nodata=nodata, dst_nodata=nodata,
        resampling=CONFIG_PREPARA["reamostragem"],
    )
    n_valido = int((destino != nodata).sum())
    print(f"[3/5] {alvo['rotulo']}: {destino.shape[0]}x{destino.shape[1]} px | "
          f"{n_valido} px classificados | reamostragem nearest")
    return destino


def gravar(dado: np.ndarray, alvo: dict, nodata: int, entrada: Path) -> Path:
    caminho = Path(alvo["saida"])
    caminho.parent.mkdir(parents=True, exist_ok=True)
    perfil = {
        "driver": "GTiff", "height": dado.shape[0], "width": dado.shape[1],
        "count": 1, "dtype": CONFIG_PREPARA["dtype_saida"], "crs": alvo["crs"],
        "transform": alvo["transform"], "nodata": nodata,
        "compress": CONFIG_PREPARA["compressao"],
        "predictor": CONFIG_PREPARA["predictor"],
        "zlevel": CONFIG_PREPARA["nivel_zlib"],
        "tiled": True,
        "blockxsize": CONFIG_PREPARA["tamanho_bloco"],
        "blockysize": CONFIG_PREPARA["tamanho_bloco"],
    }
    with rasterio.open(caminho, "w", **perfil) as dst:
        dst.write(dado, 1)
        dst.update_tags(
            fonte=cob.FONTE_COBERTURA["referencia"],
            arquivo_origem=entrada.name,
            legenda=cob.FONTE_COBERTURA["legenda"],
            reamostragem="nearest (dado categórico)",
            grade=alvo["rotulo"],
            alinhado_ao_mde=str(alvo["alinhado"]),
            gerado_em=datetime.now().isoformat(timespec="seconds"),
        )
    print(f"[4/5] gravado: {caminho} ({caminho.stat().st_size / 1e6:.1f} MB)")
    return caminho


# =============================================================================
# 4. CONFERÊNCIA — figura com legenda oficial e tabela de área
# =============================================================================

def conferir(caminho_tif: Path) -> None:
    dados = cob.carregar_cobertura(str(caminho_tif))
    df = cob.resumo_classes(dados)

    arr, nodata = dados["classes"], dados["nodata"]
    rgba = np.zeros((*arr.shape, 4), dtype="float32")
    rgba[...] = (0.90, 0.90, 0.90, 1.0)
    for _, linha in df.iterrows():
        cor = cob.classe(int(linha["Código"]))["cor"]
        r = int(cor[1:3], 16) / 255, int(cor[3:5], 16) / 255, int(cor[5:7], 16) / 255
        rgba[arr == int(linha["Código"])] = (*r, 1.0)
    rgba[arr == nodata] = (1.0, 1.0, 1.0, 1.0)

    fig, ax = plt.subplots(figsize=(9, 8), constrained_layout=True)
    ax.imshow(rgba, interpolation="nearest")
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(f"{cob.CONFIG_COBERTURA['colecao']} "
                 f"({cob.CONFIG_COBERTURA['ano_referencia']}) — Caravelas (BA)",
                 fontsize=12, weight="bold", loc="left", pad=18)
    ax.text(0, 1.010,
            f"{config.CRS_ALVO} @ {config.RESOLUCAO_M:.0f} m · reamostragem nearest · "
            "legenda oficial da Coleção 11 conferida",
            transform=ax.transAxes, fontsize=8, va="bottom", color="#444444")

    itens = [Patch(facecolor=cob.classe(int(l["Código"]))["cor"],
                   edgecolor="#333333", linewidth=0.3,
                   label=f"{l['Classe']} — {l['Área (km²)']:.1f} km² "
                         f"({l['% da área classificada']:.1f}%)")
             for _, l in df.iterrows()]
    ax.legend(handles=itens, loc="upper left", bbox_to_anchor=(1.01, 1.0),
              fontsize=7.5, frameon=False, title="Classes presentes")

    config.DIR_SAIDAS.mkdir(parents=True, exist_ok=True)
    fig_saida = config.DIR_SAIDAS / f"fig_cobertura_mapbiomas_col11_{_carimbo()}.png"
    fig.savefig(fig_saida, dpi=CONFIG_PREPARA["dpi_figura"], bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    print(f"[5/5] figura de conferência: {fig_saida}")

    csv_saida = config.DIR_SAIDAS / f"cobertura_classes_col11_{_carimbo()}.csv"
    df.to_csv(csv_saida, index=False, encoding="utf-8-sig")
    print(f"[5/5] tabela de classes: {csv_saida}")

    print("\n  Código | Classe                              |  Área (km²) |     %")
    print("  " + "-" * 74)
    for _, l in df.iterrows():
        print(f"  {int(l['Código']):6d} | {l['Classe'][:35]:35s} | "
              f"{l['Área (km²)']:11.2f} | {l['% da área classificada']:5.1f}")


# =============================================================================
# EXECUÇÃO
# =============================================================================

def main():
    print("=" * 78)
    print(f"{cob.CONFIG_COBERTURA['colecao']} — recorte para Caravelas (BA)")
    print("=" * 78)
    config.criar_estrutura()

    entrada = _resolver_entrada(sys.argv[1] if len(sys.argv) > 1 else None)
    dado, transform, crs_fonte, nodata = ler_janela(entrada)

    gerados = []
    for alvo in grades_alvo():
        recorte = reprojetar_para(dado, transform, crs_fonte, nodata, alvo)
        gerados.append(gravar(recorte, alvo, nodata, entrada))

    conferir(gerados[0])

    print("=" * 78)
    print("Concluído. A camada aparece no simulador em "
          "'Cobertura MapBiomas' — por ora apenas visual (v1.3).")
    print("=" * 78)


if __name__ == "__main__":
    main()
