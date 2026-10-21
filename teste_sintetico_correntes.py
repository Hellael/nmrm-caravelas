"""
teste_sintetico_correntes.py — valida o pipeline das correntes SEM o CMEMS
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB — Caravelas (BA)

Gera NetCDFs falsos no formato do CMEMS (uo/vo mensais, 10 anos, uma
profundidade por arquivo; jato "tipo Corrente do Brasil" para o sul sobre o
talude, com modulação sazonal), roda o `12_prepara_correntes.py` sobre eles e
confere a saída. Tudo em saidas/ — NUNCA grava em dados_web/.

    python teste_sintetico_correntes.py

Autor: Helio | Assistência: Claude
"""

import subprocess
import sys

import numpy as np
import pandas as pd
import xarray as xr

import config

CFG = config.CONFIG_CORRENTES
BOX = config.BBOX_CORRENTES
DIR = config.DIR_SAIDAS / "teste_correntes"
PROFS_FAKE = [0.494, 49.47, 222.48, 1062.44]   # níveis "reais" do GLORYS12


def gerar() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    lat = np.arange(BOX["lat_min"], BOX["lat_max"] + 1e-6, 1 / 12)
    lon = np.arange(BOX["lon_min"], BOX["lon_max"] + 1e-6, 1 / 12)
    LON, LAT = np.meshgrid(lon, lat)
    tempo = pd.date_range(f"{CFG['ano_inicio']}-01-01", f"{CFG['ano_fim']}-12-01", freq="MS")
    terra = LON < (-39.1 + 0.18 * (LAT + 18))                      # costa fictícia
    rng = np.random.default_rng(42)
    for alvo, z in zip(CFG["profundidades_m"], PROFS_FAKE):
        fator_z = np.exp(-z / 600.0)
        eixo_jato = -38.0 + 0.2 * (LAT + 18)                       # no talude
        base = np.exp(-((LON - eixo_jato) / 0.45) ** 2)
        uo = np.zeros((len(tempo),) + LON.shape, "float32")
        vo = np.zeros_like(uo)
        for it, t in enumerate(tempo):
            sazonal = 1 + 0.35 * np.cos(2 * np.pi * (t.month - 2) / 12)   # máx. no verão
            v = -0.6 * sazonal * base * fator_z + rng.normal(0, 0.04, LON.shape)
            u = 0.08 * np.sin(LAT * 6 + it) * fator_z + rng.normal(0, 0.03, LON.shape)
            uo[it], vo[it] = u, v
        uo[:, terra], vo[:, terra] = np.nan, np.nan
        ds = xr.Dataset(
            {n: (("time", "depth", "latitude", "longitude"), a[:, None]) for n, a in
             (("uo", uo), ("vo", vo))},
            coords={"time": tempo, "depth": [z], "latitude": lat, "longitude": lon})
        from importlib import import_module
        b = import_module("11_baixa_correntes")
        ds.to_netcdf(DIR / b.nome_arquivo(alvo))
    print(f"[TESTE] NetCDFs sintéticos em {DIR}")


def main() -> int:
    gerar()
    saida = config.DIR_SAIDAS / "correntes_caravelas_SINTETICO.npz"
    r = subprocess.run([sys.executable, "12_prepara_correntes.py",
                        "--entrada", str(DIR), "--saida", str(saida)])
    if r.returncode:
        return r.returncode
    with np.load(saida, allow_pickle=False) as z:
        u, v, per = z["u"], z["v"], [str(x) for x in z["periodos"]]
        assert u.shape == (5, 4, 97, 97) or u.shape[0] == 5, u.shape
        rap = np.hypot(u, v)
        i_jfm, i_jas = per.index("JFM"), per.index("JAS")
        verao, inverno = np.nanmax(rap[i_jfm, 0]), np.nanmax(rap[i_jas, 0])
        print(f"[TESTE] rapidez max superfície: JFM={verao:.2f} | JAS={inverno:.2f} m/s")
        assert verao > inverno, "o ciclo sazonal sintético (máx. no verão) sumiu"
        assert np.nanmax(rap[0, 0]) > np.nanmax(rap[0, 3]) * 3, "o jato não decai com a profundidade"
    print("[TESTE] OK — pipeline coerente. Produto de TESTE em", saida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
