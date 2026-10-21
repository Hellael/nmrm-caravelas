"""
12_prepara_correntes.py — Climatologia e médias trimestrais das correntes
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB — Caravelas (BA)

ENTRADA   NetCDFs do `11_baixa_correntes.py` (uo, vo mensais, 10 anos).
SAÍDA     dados_web/correntes_caravelas.npz  (leve, versionado — é o que o
          simulador lê) + saidas/correntes_previa_<data>.png (conferência).

O QUE CALCULA (para cada profundidade e cada período)
    u, v          média dos meses do período nos 10 anos, ponderada pelos dias
                  de cada mês. Períodos: climatologia (12 meses) e os
                  trimestres JFM, AMJ, JAS, OND (30 meses cada, 3 x 10 anos).
    constancia    |vetor médio| / média da rapidez mensal (0 a 1). Perto de 1 =
                  corrente estável em direção e intensidade (típico do núcleo
                  da Corrente do Brasil); perto de 0 = meandros e reversões.
    A rapidez que o mapa mostra é |(u, v)| da MÉDIA — o campo médio, não a
    média das rapidezes. A constância diz o quanto os dois diferem.

COMO RODAR
    python 12_prepara_correntes.py
    python 12_prepara_correntes.py --entrada D:\\outra_pasta --saida teste.npz

Depende de: xarray, netCDF4, numpy, matplotlib (requirements-geracao.txt).

Autor: Helio | Assistência: Claude
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

import config

CFG = config.CONFIG_CORRENTES


def _abrir_nivel(caminho: Path):
    """Abre um NetCDF de UMA profundidade e padroniza os nomes dos eixos."""
    import xarray as xr

    ds = xr.open_dataset(caminho)
    renomear = {}
    for novo, candidatos in {"lat": ("latitude", "lat"), "lon": ("longitude", "lon"),
                             "prof": ("depth", "deptht", "z")}.items():
        for c in candidatos:
            if c in ds.dims or c in ds.coords:
                renomear[c] = novo
                break
    ds = ds.rename(renomear)
    if "prof" in ds.dims:
        if ds.sizes["prof"] != 1:
            raise ValueError(f"{caminho.name}: esperava 1 nível de profundidade, "
                             f"veio {ds.sizes['prof']}")
        ds = ds.isel(prof=0)
    ds = ds.sortby("lat").sortby("lon")
    return ds


def _media_ponderada(campo, meses_alvo):
    """Média no tempo ponderada pelos dias do mês, ignorando NaN (terra)."""
    if meses_alvo is not None:
        campo = campo.where(campo["time"].dt.month.isin(meses_alvo), drop=True)
    pesos = campo["time"].dt.days_in_month
    return campo.weighted(pesos).mean("time", skipna=True), int(campo.sizes["time"])


def processar(dir_entrada: Path, arq_saida: Path, dir_figuras: Path) -> int:
    alvos = CFG["profundidades_m"]
    periodos = CFG["periodos"]
    chaves_p = list(periodos)

    arquivos = []
    for prof in alvos:
        nome = (f"correntes_glorys12_mensal_{CFG['ano_inicio']}_{CFG['ano_fim']}"
                f"_z{int(round(prof * 10)):05d}.nc")
        arq = dir_entrada / nome
        if not arq.exists():
            print(f"[ERRO] Falta {arq}. Rode primeiro o 11_baixa_correntes.py.")
            return 1
        arquivos.append(arq)

    U, V, CONST, prof_usada, n_meses_ref = [], [], [], [], None
    lat = lon = None
    meses_por_periodo = {}
    for prof_alvo, arq in zip(alvos, arquivos):
        ds = _abrir_nivel(arq)

        # O CMEMS (seleção 'nearest') pode devolver um passo além da janela
        # (visto: 2026-01-01 num pedido até 2025-12-31). Descarta tudo que
        # está fora dos anos configurados, senão entra uma média a mais.
        ds = ds.sel(time=slice(f"{CFG['ano_inicio']}-01-01",
                               f"{CFG['ano_fim']}-12-31"))

        # --- Conferência da série temporal -----------------------------------
        t = ds["time"].to_index()
        anos_meses = sorted(set(zip(t.year, t.month)))
        esperado = (CFG["ano_fim"] - CFG["ano_inicio"] + 1) * 12
        if len(anos_meses) != esperado or len(t) != esperado:
            faltam = sorted(
                {(a, m) for a in range(CFG["ano_inicio"], CFG["ano_fim"] + 1)
                 for m in range(1, 13)} - set(anos_meses))
            print(f"[AVISO] z={prof_alvo:g} m: {len(t)} passos, esperados {esperado}. "
                  f"Meses ausentes: {faltam[:12]}{' ...' if len(faltam) > 12 else ''}")
        if lat is None:
            lat, lon = ds["lat"].values.astype("float64"), ds["lon"].values.astype("float64")
        elif ds["lat"].size != lat.size or ds["lon"].size != lon.size:
            print("[ERRO] As profundidades têm grades diferentes — rebaixe com --refazer.")
            return 1

        z_real = float(np.atleast_1d(ds["prof"].values)[0]) if "prof" in ds.coords else float("nan")
        prof_usada.append(z_real)

        uo, vo = ds["uo"].astype("float64"), ds["vo"].astype("float64")
        rap_mensal = np.hypot(uo, vo)

        u_p, v_p, c_p = [], [], []
        for chave in chaves_p:
            meses = periodos[chave]
            um, n = _media_ponderada(uo, meses)
            vm, _ = _media_ponderada(vo, meses)
            rm, _ = _media_ponderada(rap_mensal, meses)
            modulo = np.hypot(um, vm)
            const = (modulo / rm.where(rm > 1e-6)).clip(0, 1)
            u_p.append(um.values.astype("float32"))
            v_p.append(vm.values.astype("float32"))
            c_p.append(const.values.astype("float32"))
            meses_por_periodo[chave] = n
            print(f"[MEDIA] z={z_real:7.1f} m | {chave:<12} | n_meses={n:3d} | "
                  f"|v| max={float(np.nanmax(modulo)):.2f} m/s | "
                  f"constancia media={float(np.nanmean(const)):.2f}")
        U.append(u_p), V.append(v_p), CONST.append(c_p)
        ds.close()

    # (periodo, nivel, lat, lon)
    U = np.array(U).transpose(1, 0, 2, 3)
    V = np.array(V).transpose(1, 0, 2, 3)
    CONST = np.array(CONST).transpose(1, 0, 2, 3)

    # --- Controle de qualidade ---------------------------------------------------
    rap = np.hypot(U, V)
    pico = float(np.nanmax(rap))
    frac_nan = float(np.isnan(U).mean())
    print(f"[QC] formato (periodo,nivel,lat,lon) = {U.shape} | NaN={frac_nan * 100:.1f}% "
          f"| rapidez maxima={pico:.2f} m/s")
    if pico > CFG["rapidez_max_plausivel_ms"]:
        print(f"[AVISO] Rapidez acima de {CFG['rapidez_max_plausivel_ms']} m/s "
              "numa média mensal: confira o arquivo de entrada.")
    if frac_nan > 0.6:
        print("[AVISO] Mais de 60 % de NaN: o domínio é quase todo terra ou "
              "a profundidade não tem dados.")
    # A máscara de terra tem de ser a mesma em todos os períodos do mesmo nível.
    for iz in range(U.shape[1]):
        base = np.isnan(U[0, iz])
        for ip in range(1, U.shape[0]):
            if not np.array_equal(base, np.isnan(U[ip, iz])):
                print(f"[AVISO] Máscara de terra muda entre períodos no nível {iz} "
                      "(esperado só se faltarem meses).")
                break

    # --- Gravação -----------------------------------------------------------------
    meta = {
        "produto": "GLOBAL_MULTIYEAR_PHY_001_030 (GLORYS12V1)",
        "dataset_id": CFG["dataset_id"],
        "variaveis": "uo, vo (m/s), médias mensais",
        "janela": f"{CFG['ano_inicio']}-01 a {CFG['ano_fim']}-12",
        "anos": CFG["ano_fim"] - CFG["ano_inicio"] + 1,
        "n_meses_por_periodo": meses_por_periodo,
        "grade": "1/12° (~8 km)",
        "gerado_em": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ponderacao": "média mensal ponderada pelos dias do mês",
        "limitacao": ("Média de campos mensais de reanálise: não resolve maré, "
                      "ondas nem a plataforma interna rasa; perto da costa a grade "
                      "de ~8 km é grosseira. É MODELO assimilativo, não medição."),
    }
    arq_saida.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        arq_saida,
        u=np.round(U, 4), v=np.round(V, 4), constancia=np.round(CONST, 3),
        lat=lat, lon=lon,
        periodos=np.array(chaves_p),
        profundidade_alvo_m=np.array(alvos, dtype="float64"),
        profundidade_usada_m=np.array(prof_usada, dtype="float64"),
        metadados=np.array(json.dumps(meta, ensure_ascii=False)),
    )
    kb = arq_saida.stat().st_size / 1024
    print(f"[SAIDA] {arq_saida} ({kb:.0f} KB)")

    # --- Figura de conferência ------------------------------------------------------
    try:
        _figura_previa(U, V, lat, lon, chaves_p, prof_usada, dir_figuras)
    except Exception as exc:  # noqa: BLE001 — a figura nunca derruba o produto
        print(f"[AVISO] Figura de conferência não gerada: {exc}")
    print("[RESUMO] Pronto. Abra o simulador e ligue 'Correntes oceânicas'.")
    return 0


def _figura_previa(U, V, lat, lon, chaves_p, prof_usada, dir_figuras: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n_p, n_z = U.shape[0], U.shape[1]
    fig, eixos = plt.subplots(n_z, n_p, figsize=(3.2 * n_p, 3.0 * n_z),
                              squeeze=False, constrained_layout=True)
    passo = 4
    for iz in range(n_z):
        vmax = float(np.nanpercentile(np.hypot(U[:, iz], V[:, iz]), 99)) or 0.1
        for ip in range(n_p):
            ax = eixos[iz][ip]
            rap = np.hypot(U[ip, iz], V[ip, iz])
            im = ax.pcolormesh(lon, lat, rap, vmin=0, vmax=vmax, cmap="viridis",
                               shading="auto")
            LON, LAT = np.meshgrid(lon, lat)
            ax.quiver(LON[::passo, ::passo], LAT[::passo, ::passo],
                      U[ip, iz][::passo, ::passo], V[ip, iz][::passo, ::passo],
                      color="white", scale=vmax * 18, width=0.003)
            ax.set_aspect(1 / np.cos(np.radians(abs(lat.mean()))))
            ax.set_title(f"{chaves_p[ip]} · {prof_usada[iz]:.0f} m", fontsize=9)
            ax.tick_params(labelsize=7)
            if ip == n_p - 1:
                fig.colorbar(im, ax=ax, label="m/s", shrink=0.8)
    dir_figuras.mkdir(parents=True, exist_ok=True)
    arq = dir_figuras / f"correntes_previa_{dt.date.today():%Y%m%d}.png"
    fig.savefig(arq, dpi=110)
    plt.close(fig)
    print(f"[FIGURA] {arq}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entrada", default=str(config.DIR_CORRENTES_BRUTO),
                    help="Pasta com os NetCDF do 11 (padrão: NMRM_DIR_DADOS/correntes).")
    ap.add_argument("--saida", default=str(config.DIR_RAIZ / "dados_web" / config.ARQ_CORRENTES_WEB),
                    help="Produto leve (padrão: dados_web/correntes_caravelas.npz).")
    args = ap.parse_args()
    print("=" * 70)
    print("[CORRENTES] Preparo: climatologia e trimestres")
    print(f"[CORRENTES] entrada = {args.entrada}")
    print(f"[CORRENTES] saida   = {args.saida}")
    print("=" * 70)
    return processar(Path(args.entrada), Path(args.saida), config.DIR_SAIDAS)


if __name__ == "__main__":
    sys.exit(main())
