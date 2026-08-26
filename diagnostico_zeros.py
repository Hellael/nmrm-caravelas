#!/usr/bin/env python3
"""
diagnostico_zeros.py — Script avulso de diagnóstico do pipeline NMRM Caravelas

NÃO faz parte do pipeline oficial (01_mapa_elevacao.py / 02_simulador_nmrm.py)
e não é importado por nenhum deles. Existe só para responder uma pergunta:
os pixels == 0.0 do FABDEM (que o 01 trata como "oceano" e apaga) são todos
mesmo oceano aberto, ou existem manguezais / planícies de maré / lagunas /
canais internos sendo apagados junto por coincidirem com o mesmo valor?

Reproduz o pipeline do 01_mapa_elevacao.py até a reprojeção (mesmo bbox,
mesmo CRS, mesma resolução) IMPORTANDO as funções de lá em vez de duplicar
a lógica de mosaico/reprojeção — assim qualquer correção futura no 01
(ex.: o fix do nodata) se propaga automaticamente pra este diagnóstico.

SAÍDA
    saidas/diagnostico_zeros_<data>.png   mapa dos dois grupos de pixels=0.0

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

# =============================================================================
# PARÂMETROS
# =============================================================================

CONFIG_DIAG = {
    "tol_zero":          core.CONFIG_DEM["tol_oceano"],  # mesma tolerância do resto do projeto
    "cota_holocenica_m": 6.0,   # limite terraços holocênicos (Andrade et al. 2003)
    "dpi":               150,
}


def _carimbo() -> str:
    return datetime.now().strftime("%Y%m%d")


# =============================================================================
# 0. REUSA O PIPELINE DO 01 ATÉ A REPROJEÇÃO (sem duplicar a lógica)
# =============================================================================

def _carregar_funcoes_01():
    """Importa 01_mapa_elevacao.py como módulo (nome começa com dígito,
    não dá pra fazer `import 01_mapa_elevacao` direto)."""
    caminho = config.DIR_RAIZ / "01_mapa_elevacao.py"
    spec = importlib.util.spec_from_file_location("pipeline_01", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)  # roda só as definições; main() é __main__-guarded
    return modulo


# =============================================================================
# 1 e 2. PIXELS ==0.0 ANTES DA MÁSCARA + CONECTIVIDADE À BORDA LESTE
# =============================================================================

def analisar_zeros(dem: np.ndarray, area_pixel_m2: float) -> dict:
    """
    Separa os pixels ==0.0 (antes de qualquer máscara) em dois grupos por
    conectividade de 8 vizinhos com a borda leste do recorte:
        grupo_a : conectado à borda leste -> oceano aberto
        grupo_b : não conectado -> candidato a manguezal/maré/laguna/canal
    Reusa src/slr_core.mascara_inundacao tratando a borda leste como a
    única "fonte de água" (semear_bordas=False propositalmente: só a
    borda leste conta, não as bordas norte/sul/oeste).
    """
    tol = CONFIG_DIAG["tol_zero"]
    mask_zero = np.isclose(dem, 0.0, atol=tol, equal_nan=False)
    area_total_km2 = float(mask_zero.sum()) * area_pixel_m2 / 1e6
    print(f"[ZEROS] pixels ==0.0 antes da máscara: {int(mask_zero.sum())} px "
          f"({area_total_km2:.2f} km²)")

    # dem sintético em que só os pixels de zero são "terreno válido" (=0.0);
    # o resto vira NaN. Assim `abaixo` (dentro de mascara_inundacao) coincide
    # exatamente com mask_zero, e não com "qualquer coisa <= 0".
    dem_zero = np.where(mask_zero, 0.0, np.nan).astype(dem.dtype)

    mask_borda_leste = np.zeros_like(mask_zero)
    mask_borda_leste[:, -1] = True

    m = core.mascara_inundacao(
        dem_zero, mask_borda_leste, cota_m=0.0,
        conectividade=True, semear_bordas=False, conexao_8=True,
        area_pixel_m2=area_pixel_m2, area_minima_ha=0.0,
    )
    grupo_a, grupo_b = m["inundada"], m["isolada"]

    area_a_km2 = float(grupo_a.sum()) * area_pixel_m2 / 1e6
    area_b_km2 = float(grupo_b.sum()) * area_pixel_m2 / 1e6
    print(f"[ZEROS] grupo (a) oceano aberto, conectado à borda leste: "
          f"{int(grupo_a.sum())} px ({area_a_km2:.2f} km²)")
    print(f"[ZEROS] grupo (b) candidatos a manguezal/maré/laguna/canal, "
          f"sem conexão com a borda leste: {int(grupo_b.sum())} px "
          f"({area_b_km2:.2f} km²)")

    assert int(grupo_a.sum() + grupo_b.sum()) == int(mask_zero.sum()), (
        "Partição grupo_a + grupo_b deveria cobrir exatamente mask_zero"
    )

    return {
        "mask_zero": mask_zero, "grupo_a": grupo_a, "grupo_b": grupo_b,
        "area_total_km2": area_total_km2,
        "area_a_km2": area_a_km2, "area_b_km2": area_b_km2,
    }


def salvar_mapa_zeros(dem: np.ndarray, zeros: dict) -> str:
    """PNG do MDE sombreado com os dois grupos de pixels=0.0 sobrepostos."""
    hs = core.hillshade(dem, config.RESOLUCAO_M)
    cor_a = matplotlib.colors.to_rgb(core.CONFIG_MAPA["cor_inundado"])
    cor_b = matplotlib.colors.to_rgb(core.CONFIG_MAPA["cor_isolado"])
    alpha = core.CONFIG_MAPA["alpha_agua"]

    rgb = np.stack([hs, hs, hs], axis=-1)
    rgb[np.isnan(dem)] = (1.0, 1.0, 1.0)  # sem cobertura de tile (fora do BBOX)
    for mask, cor in ((zeros["grupo_a"], cor_a), (zeros["grupo_b"], cor_b)):
        for c in range(3):
            rgb[..., c] = np.where(mask, (1 - alpha) * rgb[..., c] + alpha * cor[c], rgb[..., c])

    fig, ax = plt.subplots(figsize=(11, 9), constrained_layout=True)
    ax.imshow(rgb, interpolation="nearest")
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title("Diagnóstico — pixels ==0.0 antes da máscara de oceano",
                 fontsize=13, weight="bold", loc="left")
    ax.text(0, 1.01,
            f"Azul = grupo (a) oceano aberto (conectado à borda leste) · "
            f"Roxo = grupo (b) candidato a manguezal/maré/laguna/canal (isolado)",
            transform=ax.transAxes, fontsize=9, va="bottom")

    legenda = [
        plt.Line2D([0], [0], marker="s", color="w", markerfacecolor=cor_a, markersize=12,
                   label=f"(a) oceano aberto — {zeros['area_a_km2']:.1f} km²"),
        plt.Line2D([0], [0], marker="s", color="w", markerfacecolor=cor_b, markersize=12,
                   label=f"(b) candidatos internos — {zeros['area_b_km2']:.1f} km²"),
    ]
    ax.legend(handles=legenda, loc="lower left", fontsize=9, framealpha=0.9)

    config.DIR_SAIDAS.mkdir(parents=True, exist_ok=True)
    caminho = config.DIR_SAIDAS / f"diagnostico_zeros_{_carimbo()}.png"
    fig.savefig(caminho, dpi=CONFIG_DIAG["dpi"], bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[EXPORT] mapa salvo: {caminho}")
    return str(caminho)


# =============================================================================
# 4. FAIXA 0-6 m: CONTÍGUA À COSTA x DESCONECTADA (fundos de vale no Barreiras)
# =============================================================================

def analisar_faixa_holocenica(dem: np.ndarray, mask_zero: np.ndarray, area_pixel_m2: float) -> dict:
    """
    Da área com 0 < z <= 6 m, separa o que está hidraulicamente conectado ao
    oceano (a planície costeira propriamente dita) do que está confinado
    (fundos de vale dentro dos tabuleiros do Grupo Barreiras). Usa a MESMA
    lógica de conectividade do resto do projeto (CONFIG_INUNDACAO em
    src/slr_core.py: conexão-8, bordas do domínio semeiam água) — aqui a
    "fonte" é o oceano real (mask_zero), não só a borda leste.
    """
    dem_terra = dem.copy()
    dem_terra[mask_zero] = np.nan  # mesmo passo de mascarar_e_salvar() no 01

    cota = CONFIG_DIAG["cota_holocenica_m"]
    m6 = core.mascara_inundacao(dem_terra, mask_zero, cota_m=cota, area_pixel_m2=area_pixel_m2)

    area_contigua_km2 = float(m6["inundada"].sum()) * area_pixel_m2 / 1e6
    area_confinada_km2 = float(m6["isolada"].sum()) * area_pixel_m2 / 1e6
    print(f"[FAIXA-0-{cota:g}M] contígua à costa (planície propriamente dita): "
          f"{area_contigua_km2:.2f} km²")
    print(f"[FAIXA-0-{cota:g}M] desconectada (fundos de vale no Barreiras): "
          f"{area_confinada_km2:.2f} km²")

    return {"area_contigua_km2": area_contigua_km2, "area_confinada_km2": area_confinada_km2}


# =============================================================================
# EXECUÇÃO
# =============================================================================

def main():
    print("=" * 72)
    print("DIAGNÓSTICO — pixels ==0.0 no MDE, antes da máscara de oceano")
    print("=" * 72)

    pipeline_01 = _carregar_funcoes_01()
    dem, transform = pipeline_01.mosaicar_e_recortar()
    dem, transform = pipeline_01.reprojetar(dem, transform)
    area_pixel_m2 = config.RESOLUCAO_M ** 2

    print("-" * 72)
    zeros = analisar_zeros(dem, area_pixel_m2)

    print("-" * 72)
    salvar_mapa_zeros(dem, zeros)

    print("-" * 72)
    analisar_faixa_holocenica(dem, zeros["mask_zero"], area_pixel_m2)

    print("=" * 72)
    print("Concluído.")
    print("=" * 72)


if __name__ == "__main__":
    main()
