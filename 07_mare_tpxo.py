#!/usr/bin/env python3
"""
07_mare_tpxo.py — Projeto 26.09 (simulador NMRM Caravelas)

Extrai as constantes harmônicas do TPXO9-atlas v5 num ponto ao largo da barra
de Caravelas (BA) e converte em níveis de maré acima do nível médio do mar.

ONDE ESTE SCRIPT RODA
    NÃO na máquina do projeto. O atlas TPXO9-atlas v5 tem ~10 GB e vive na
    máquina onde o Helio roda o ROMS (`~/Projetos/TPXO9_atlas_v5_nc`). Este
    arquivo está versionado aqui apenas como PROVENIÊNCIA: é o código exato
    que gerou `dados_web/mare_caravelas_tpxo9v5.json`, para o número ser
    reproduzível e auditável. Rodado em 22/09/2026.

    Para reproduzir: copie este arquivo para a máquina que tem o atlas,
    ajuste CONFIG_MARE["dir_tpxo"] e rode. Dependências: numpy + netCDF4
    (netCDF4 NÃO entra no requirements.txt do projeto — o app publicado lê
    só o JSON, nunca o atlas).

O QUE NÃO É LIDO
    Os arquivos u_*.nc (componentes de corrente) não são tocados: só
    interessam ao ROMS montar forçante de maré. Para nível d'água bastam os
    h_*.nc de elevação mais o arquivo de grade.

CUIDADO DE MEMÓRIA
    A grade do atlas é 10800 x 5401 (58 milhões de células por variável).
    Ler uma variável inteira (`nc.variables["hRe"][:]`) carrega centenas de
    MB. Aqui só os vetores lon/lat vêm completos (poucas centenas de KB); o
    resto é lido por janela de índice.

NOMES DE VARIÁVEL
    Versões do atlas trocam `mz` por `mask_z`/`mask` e `hz` por `depth`/`h`.
    O script procura entre candidatos, imprime o que encontrou e, quando não
    há máscara nenhuma (é o caso da distribuição usada aqui, que traz só
    hz/hu/hv), deriva a água de profundidade > 0.

Autor: Helio | Assistência: Claude
"""
import os
import glob
import json

import numpy as np
from netCDF4 import Dataset


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

CONFIG_MARE = {
    "dir_tpxo":      os.path.expanduser("~/Projetos/TPXO9_atlas_v5_nc"),
    "lat_alvo":      -17.75,   # ao largo da barra de Caravelas
    "lon_alvo":      -39.05,
    "constituintes": ["q1", "o1", "p1", "k1", "n2", "m2", "s2", "k2"],
    "raio_busca_px": 12,       # janela para achar célula molhada, se cair em terra
    "arq_saida":     "mare_caravelas_tpxo9v5.json",
    # Candidatos por papel, na ordem de preferência.
    "nomes_lon":   ["lon_z", "lon", "longitude", "nx"],
    "nomes_lat":   ["lat_z", "lat", "latitude", "ny"],
    "nomes_mask":  ["mz", "mask_z", "mask", "mask_rho"],
    "nomes_prof":  ["hz", "depth", "h", "bathy"],
}


def _primeiro(nc, candidatos, papel, obrigatorio=True):
    """Devolve a primeira variável existente entre os candidatos."""
    for nome in candidatos:
        if nome in nc.variables:
            print(f"[MARE] {papel}: variável '{nome}' {nc.variables[nome].shape}")
            return nc.variables[nome]
    if obrigatorio:
        raise SystemExit(f"[MARE] nenhuma variável de {papel} encontrada. "
                         f"Procurei por {candidatos}. Existem: "
                         f"{sorted(nc.variables)}")
    print(f"[MARE] {papel}: ausente ({candidatos}) — seguindo sem")
    return None


def _acha_arquivo(padrao):
    achados = sorted(glob.glob(padrao))
    return achados[0] if achados else None


# =============================================================================
# 1. LOCALIZAÇÃO NA GRADE DO ATLAS
# =============================================================================

arq_grade = _acha_arquivo(os.path.join(CONFIG_MARE["dir_tpxo"], "grid_tpxo9*.nc"))
if arq_grade is None:
    raise SystemExit(f"[MARE] grade não encontrada em {CONFIG_MARE['dir_tpxo']}")
print(f"[MARE] grade: {os.path.basename(arq_grade)}")

with Dataset(arq_grade) as nc:
    lon_z = np.asarray(_primeiro(nc, CONFIG_MARE["nomes_lon"], "longitude")[:]).ravel()
    lat_z = np.asarray(_primeiro(nc, CONFIG_MARE["nomes_lat"], "latitude")[:]).ravel()
    var_prof = _primeiro(nc, CONFIG_MARE["nomes_prof"], "profundidade")
    var_mask = _primeiro(nc, CONFIG_MARE["nomes_mask"], "máscara", obrigatorio=False)

    # A orientação (lon,lat) x (lat,lon) varia entre versões: detectar, não supor.
    transposto = (var_prof.shape[0] == len(lat_z) and var_prof.shape[1] == len(lon_z))
    print(f"[MARE] orientação: {'(lat, lon)' if transposto else '(lon, lat)'}")

    def janela(var, i0, i1, j0, j1):
        bloco = np.asarray(var[j0:j1, i0:i1] if transposto else var[i0:i1, j0:j1])
        return bloco.T if transposto else bloco

    lon_alvo360 = CONFIG_MARE["lon_alvo"] % 360.0
    i = int(np.argmin(np.abs(lon_z - lon_alvo360)))
    j = int(np.argmin(np.abs(lat_z - CONFIG_MARE["lat_alvo"])))

    r = CONFIG_MARE["raio_busca_px"]
    i0, i1 = max(i - r, 0), min(i + r + 1, len(lon_z))
    j0, j1 = max(j - r, 0), min(j + r + 1, len(lat_z))

    jan_prof = janela(var_prof, i0, i1, j0, j1).astype("float64")
    if var_mask is not None:
        jan_agua = janela(var_mask, i0, i1, j0, j1) > 0
    else:
        # Sem máscara: no atlas a profundidade é 0 (ou nodata) em terra.
        jan_agua = np.isfinite(jan_prof) & (jan_prof > 0)
        print("[MARE] usando profundidade > 0 como critério de água")

    if not jan_agua[i - i0, j - j0]:
        agua = np.argwhere(jan_agua)
        if agua.size == 0:
            raise SystemExit("[MARE] nenhuma célula molhada na janela — "
                             "aumente raio_busca_px ou mova o ponto em CONFIG_MARE")
        d = (agua[:, 0] - (i - i0)) ** 2 + (agua[:, 1] - (j - j0)) ** 2
        di, dj = agua[int(np.argmin(d))]
        i, j = i0 + int(di), j0 + int(dj)
        print("[MARE] ponto pedido caiu em terra; usando a célula molhada mais próxima")

    prof = float(jan_prof[i - i0, j - j0])

lon_use = float(((lon_z[i] + 180) % 360) - 180)
lat_use = float(lat_z[j])
dist_km = float(np.hypot(
    (lon_use - CONFIG_MARE["lon_alvo"]) * 111.0 * np.cos(np.radians(lat_use)),
    (lat_use - CONFIG_MARE["lat_alvo"]) * 111.0))
print(f"[MARE] célula usada: lon {lon_use:.4f} / lat {lat_use:.4f} | "
      f"{dist_km:.2f} km do alvo | profundidade {prof:.1f} m")


# =============================================================================
# 2. AMPLITUDE E FASE POR CONSTITUINTE
# =============================================================================

const = {}
for c in CONFIG_MARE["constituintes"]:
    arq = _acha_arquivo(os.path.join(CONFIG_MARE["dir_tpxo"], f"h_{c}_*.nc"))
    if arq is None:
        print(f"[MARE] AVISO: {c.upper()} não encontrado — seguindo sem ele")
        continue
    with Dataset(arq) as nc:
        nomes = sorted(nc.variables)
        nRe = next((n for n in ("hRe", "hRe_z", "hre", "h_re") if n in nc.variables), None)
        nIm = next((n for n in ("hIm", "hIm_z", "him", "h_im") if n in nc.variables), None)
        if nRe is None or nIm is None:
            raise SystemExit(f"[MARE] {c.upper()}: não achei hRe/hIm. Existem: {nomes}")
        vRe, vIm = nc.variables[nRe], nc.variables[nIm]
        tr = (vRe.shape[0] == len(lat_z) and vRe.shape[1] == len(lon_z))
        hRe = float(vRe[j, i] if tr else vRe[i, j])          # mm
        hIm = float(vIm[j, i] if tr else vIm[i, j])          # mm
    amp = float(np.hypot(hRe, hIm)) / 1000.0                 # m
    fase = float(np.degrees(np.arctan2(-hIm, hRe)) % 360.0)  # graus, GMT
    const[c.upper()] = {"amplitude_m": round(amp, 4), "fase_graus": round(fase, 2)}
    print(f"[MARE] {c.upper():3s} | amplitude {amp:6.3f} m | fase {fase:6.2f}°")

if not const:
    raise SystemExit("[MARE] nenhum constituinte lido — confira dir_tpxo")
if all(v["amplitude_m"] < 1e-4 for v in const.values()):
    raise SystemExit("[MARE] todas as amplitudes deram ~0 — a célula escolhida "
                     "provavelmente é terra. Mova lon_alvo/lat_alvo mar adentro.")


# =============================================================================
# 3. NÍVEIS DE MARÉ ACIMA DO NÍVEL MÉDIO
# =============================================================================
#
# Relações harmônicas clássicas, válidas para costa francamente semidiurna
# (é o caso: F = 0,127). NÃO são datums medidos — ver a ressalva gravada no
# JSON e a seção de limitações do CLAUDE.md.
#
#   PM média      = M2 + (K1+O1)/2   preamar média
#   PM sizígia    = M2 + S2          preamar de sizígia
#   PM quadratura = |M2 - S2|        preamar de quadratura
#   HAT estimado  = soma de TODAS as amplitudes — limite SUPERIOR, não o HAT
#                   real: ignora modulação nodal e não inclui constituintes
#                   fora do conjunto de 8 (M4, MS4, MF, MM, águas rasas).

A = {k: v["amplitude_m"] for k, v in const.items()}
M2, S2 = A.get("M2", 0.0), A.get("S2", 0.0)
K1, O1, N2 = A.get("K1", 0.0), A.get("O1", 0.0), A.get("N2", 0.0)

F = (K1 + O1) / (M2 + N2) if (M2 + N2) > 0 else float("nan")
regime = ("semidiurna" if F < 0.25 else
          "mista, predominantemente semidiurna" if F < 1.5 else
          "mista, predominantemente diurna" if F < 3.0 else "diurna")

niveis = {
    "PM_media_m":      round(M2 + (K1 + O1) / 2, 3),
    "PM_sizigia_m":    round(M2 + S2, 3),
    "PM_quadratura_m": round(abs(M2 - S2), 3),
    "HAT_estimado_m":  round(sum(A.values()), 3),
    "numero_forma_F":  round(F, 3),
    "regime":          regime,
}


# =============================================================================
# 4. GRAVAÇÃO E RESUMO
# =============================================================================

saida = {
    "fonte": "TPXO9-atlas v5 (OSU), grade de 1/30°",
    "referencia_vertical": "nível médio do mar local do modelo de maré",
    "ressalva": ("célula de ~3,7 km: representa a maré AO LARGO da barra, "
                 "não dentro dos canais do estuário de Caravelas"),
    "ponto": {"lon": round(lon_use, 4), "lat": round(lat_use, 4),
              "profundidade_m": round(prof, 1),
              "dist_do_alvo_km": round(dist_km, 2)},
    "constituintes": const,
    "niveis_m": niveis,
}
with open(CONFIG_MARE["arq_saida"], "w", encoding="utf-8") as f:
    json.dump(saida, f, ensure_ascii=False, indent=2)

print("\n" + "=" * 64)
print("RESUMO — níveis acima do nível médio do mar (m)")
for k, v in niveis.items():
    print(f"  {k:18s} {v}")
print(f"\nArquivo gravado: {os.path.abspath(CONFIG_MARE['arq_saida'])}")
print("=" * 64)
