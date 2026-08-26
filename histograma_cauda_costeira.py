#!/usr/bin/env python3
"""
histograma_cauda_costeira.py — Script avulso: histograma fino da cauda
inferior de cota, restrito à planície contígua à costa

NÃO faz parte do pipeline oficial (01_mapa_elevacao.py / 02_simulador_nmrm.py)
e não é importado por nenhum deles.

Reusa exatamente a mesma máscara de 586,37 km² do diagnostico_zeros.py
(terreno com 0 < z <= 6 m conectado hidraulicamente ao oceano, ver
docs/diagnostico_zeros.md) e histograma a elevação desses pixels em passos
de 0,25 m entre 0 e 10 m. Como a máscara é definida por `dem <= 6.0`, os
bins acima de 6,0 m são estruturalmente vazios — isso é esperado e é
justamente o ponto: confirma que a planície contígua à costa não "vaza"
para dentro do intervalo 6-10 m, que no diagnóstico anterior corresponde
aos 11,33 km² de fundos de vale confinados no Grupo Barreiras.

SAÍDA
    saidas/histograma_cauda_costeira_<data>.png

Autor: Helio | Assistência: Claude
"""

import importlib.util
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import config
import src.slr_core as core

CONFIG_HIST = {
    "cota_holocenica_m": 6.0,   # mesma cota de diagnostico_zeros.py (Andrade et al. 2003)
    "z_min":             0.0,
    "z_max":             10.0,
    "passo_m":           0.25,
    "dpi":               150,
}


def _carimbo() -> str:
    return datetime.now().strftime("%Y%m%d")


def _carregar_funcoes_01():
    """Importa 01_mapa_elevacao.py como módulo (mesma técnica do diagnostico_zeros.py)."""
    caminho = config.DIR_RAIZ / "01_mapa_elevacao.py"
    spec = importlib.util.spec_from_file_location("pipeline_01", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def mascara_planicie_contigua(dem: np.ndarray, area_pixel_m2: float) -> np.ndarray:
    """Reconstrói a mesma máscara de 586,37 km² do item 1 (docs/diagnostico_zeros.md)."""
    tol = core.CONFIG_DEM["tol_oceano"]
    mask_zero = np.isclose(dem, 0.0, atol=tol, equal_nan=False)

    dem_terra = dem.copy()
    dem_terra[mask_zero] = np.nan

    cota = CONFIG_HIST["cota_holocenica_m"]
    m6 = core.mascara_inundacao(dem_terra, mask_zero, cota_m=cota, area_pixel_m2=area_pixel_m2)

    area_km2 = float(m6["inundada"].sum()) * area_pixel_m2 / 1e6
    print(f"[MASCARA-PLANICIE] contígua à costa, 0-{cota:g} m: {area_km2:.2f} km²")
    return m6["inundada"], dem_terra


def histograma_fino(dem_terra: np.ndarray, mask_planicie: np.ndarray, area_pixel_m2: float):
    """Histograma de área por faixa de 0,25 m, só dentro da máscara contígua."""
    z = dem_terra[mask_planicie]
    z = z[np.isfinite(z)]

    bins = np.arange(CONFIG_HIST["z_min"], CONFIG_HIST["z_max"] + CONFIG_HIST["passo_m"],
                      CONFIG_HIST["passo_m"])
    contagem, arestas = np.histogram(z, bins=bins)
    area_km2 = contagem * area_pixel_m2 / 1e6

    print(f"[HISTOGRAMA] {len(z)} px válidos | passo={CONFIG_HIST['passo_m']} m | "
          f"faixa=[{CONFIG_HIST['z_min']}, {CONFIG_HIST['z_max']}] m")
    for i in range(len(contagem)):
        print(f"[HISTOGRAMA] {arestas[i]:5.2f}-{arestas[i+1]:5.2f} m: "
              f"{area_km2[i]:8.3f} km² ({contagem[i]} px)")
    print(f"[HISTOGRAMA] soma total: {area_km2.sum():.2f} km²")

    return arestas, area_km2


def salvar_figura(arestas: np.ndarray, area_km2: np.ndarray) -> str:
    centros = (arestas[:-1] + arestas[1:]) / 2
    cota_corte = CONFIG_HIST["cota_holocenica_m"]

    fig, ax = plt.subplots(figsize=(10, 5.5), constrained_layout=True)
    cores = ["#2171b5" if c <= cota_corte else "#bdbdbd" for c in centros]
    ax.bar(centros, area_km2, width=CONFIG_HIST["passo_m"] * 0.9, color=cores)
    ax.axvline(cota_corte, color="#7B0D0D", ls="--", lw=1.2,
               label=f"corte da máscara ({cota_corte:g} m)")

    ax.set_xlabel("Cota (m, EGM2008)")
    ax.set_ylabel("Área (km²) por faixa de 0,25 m")
    ax.set_title("Cauda inferior de cota — planície contígua à costa\n"
                  "(fundos de vale confinados no Grupo Barreiras excluídos)",
                  fontsize=12, weight="bold", loc="left")
    ax.text(0, -0.14, f"Total = {area_km2.sum():.2f} km² | máscara idêntica ao item "
                      f"'contígua à costa' de docs/diagnostico_zeros.md",
            transform=ax.transAxes, fontsize=8, va="top", color="#444444")
    ax.legend(fontsize=9, loc="upper right")
    ax.set_xlim(CONFIG_HIST["z_min"], CONFIG_HIST["z_max"])

    config.DIR_SAIDAS.mkdir(parents=True, exist_ok=True)
    caminho = config.DIR_SAIDAS / f"histograma_cauda_costeira_{_carimbo()}.png"
    fig.savefig(caminho, dpi=CONFIG_HIST["dpi"], bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[EXPORT] figura salva: {caminho}")
    return str(caminho)


def main():
    print("=" * 72)
    print("HISTOGRAMA FINO — cauda inferior de cota, planície contígua à costa")
    print("=" * 72)

    pipeline_01 = _carregar_funcoes_01()
    dem, transform = pipeline_01.mosaicar_e_recortar()
    dem, transform = pipeline_01.reprojetar(dem, transform)
    area_pixel_m2 = config.RESOLUCAO_M ** 2

    print("-" * 72)
    mask_planicie, dem_terra = mascara_planicie_contigua(dem, area_pixel_m2)

    print("-" * 72)
    arestas, area_km2 = histograma_fino(dem_terra, mask_planicie, area_pixel_m2)

    print("-" * 72)
    salvar_figura(arestas, area_km2)

    print("=" * 72)
    print("Concluído.")
    print("=" * 72)


if __name__ == "__main__":
    main()
