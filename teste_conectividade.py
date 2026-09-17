"""
teste_conectividade.py — Testes sintéticos da v1.4 (máscara de água na grade
nativa + canais MapBiomas como caminho hidráulico)

Não depende do FABDEM nem de dados_web/ reais: cada caso monta um MDE
sintético pequeno. Roda com:

    python teste_conectividade.py

Imprime OK/FALHOU por caso e sai com código != 0 se algum falhar.

Autor: Helio | Assistência: Claude
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from pathlib import Path

import numpy as np
from rasterio.transform import from_origin
from scipy import ndimage

import config
import src.slr_core as core
import src.fonte_dados as fonte


def _carregar_modulo_numerico(nome_arquivo: str, nome_modulo: str):
    """Os scripts do pipeline começam com dígito (`01_...py`, `03_...py`) e
    não são importáveis com `import`. Carrega via caminho de arquivo."""
    caminho = Path(__file__).parent / nome_arquivo
    spec = importlib.util.spec_from_file_location(nome_modulo, caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


m01 = _carregar_modulo_numerico("01_mapa_elevacao.py", "_teste_mapa_elevacao")
m03 = _carregar_modulo_numerico("03_prepara_dem_web.py", "_teste_prepara_dem_web")


# =============================================================================
# 1. Máscara nativa sobrevive à reprojeção (Parte 1)
# =============================================================================

def teste_1_mascara_nativa() -> bool:
    ny, nx = 60, 90
    dlon = dlat = (1.0 / 3.0) / 3600.0  # ~10 m — mais fino que o alvo de 30 m
    lon_min, lat_max = -39.20, -17.70
    transform_nativa = from_origin(lon_min, lat_max, dlon, dlat)
    lon_max = lon_min + nx * dlon
    lat_min = lat_max - ny * dlat

    dem_nat = np.full((ny, nx), 4.0, dtype="float32")
    dem_nat[:, 70:] = 0.0        # mar a leste
    dem_nat[30, 40:75] = 0.0     # canal de 1 px de largura ligando ao mar

    bbox_original = dict(config.BBOX_WGS84)
    config.BBOX_WGS84 = {"lon_min": lon_min, "lon_max": lon_max,
                         "lat_min": lat_min, "lat_max": lat_max}
    try:
        agua_nat = m01.detectar_agua_nativa(dem_nat)
        dem_sem_agua = dem_nat.copy()
        dem_sem_agua[agua_nat] = np.nan

        dem_utm, transform_utm = m01.reprojetar(dem_sem_agua, transform_nativa)
        agua_area, agua_conexao, agua_margem = m01.reprojetar_mascaras_agua(
            agua_nat, transform_nativa, transform_utm, dem_utm.shape)

        dem_utm_final = dem_utm.copy()
        dem_utm_final[agua_area] = np.nan  # v1.4b: só agua_area sai da área

        # (a) o canal sobrevive contínuo em agua_conexao (Resampling.max): a
        # máscara inteira (mar + canal) forma UM ÚNICO componente conexo — se
        # o canal tivesse sido cortado pela reamostragem, o mar formaria seu
        # próprio retângulo e o resto do canal apareceria solto ou
        # desapareceria, dando mais de um componente (ou nenhum a oeste do
        # mar). Também exige que o canal se estenda visivelmente a oeste da
        # coluna onde o mar "puro" começa.
        estrutura = np.ones((3, 3), dtype=bool)
        rot, n_rot = ndimage.label(agua_conexao, structure=estrutura)
        um_componente = (n_rot == 1)

        colunas_com_agua = np.where(agua_conexao.any(axis=0))[0]
        col_mais_a_oeste = int(colunas_com_agua.min())
        # coluna onde o mar "puro" começa: moda da 1ª coluna de água por linha
        primeira_col_por_linha = [
            int(np.where(linha)[0][0]) for linha in agua_conexao if linha.any()
        ]
        col_mar_tipica = int(np.median(primeira_col_por_linha))
        canal_visivel = col_mais_a_oeste < col_mar_tipica - 3

        canal_continuo = um_componente and canal_visivel

        # (b) a margem não herdou cota artificialmente baixa do bilinear
        # misturado com o 0.0 da água — todo terreno restante é ~4.0 m.
        margem_ok = bool(np.nanmin(dem_utm_final) >= 3.9)

        # (c) o canal, sendo 1 px estreito dentro de pixels de 30 m, cai
        # majoritariamente como MARGEM (fica terra, mas conduz) — não deveria
        # inteiro virar agua_area, senão a v1.4b não estaria fazendo nada de
        # diferente da v1.4a.
        canal_tem_margem = bool(agua_margem.any())

        ok = canal_continuo and margem_ok and canal_tem_margem
        print(f"  [1] máscara nativa | canal contínuo (agua_conexao)={canal_continuo} | "
              f"min margem={np.nanmin(dem_utm_final):.2f} m (>= 3.9 esperado) | "
              f"agua_margem não vazia={canal_tem_margem} -> {'OK' if ok else 'FALHOU'}")
        return ok
    finally:
        config.BBOX_WGS84 = bbox_original


# =============================================================================
# Utilitário comum aos testes 2-5: grade sintética UTM-like
# =============================================================================

def _grade_canal_mar_depressao(cota_canal_m: float):
    """
    Mar a leste (cols 27-29), depressão a 1.0 m (linhas 5-9, cols 3-7) e um
    canal classe 33 de 1 px de largura (linha 7, cols 8-26) na cota informada.
    Terreno de fundo a 5.0 m (nunca alaga nos cenários testados).
    """
    ny, nx = 20, 30
    dem = np.full((ny, nx), 5.0, dtype="float32")
    mascara_agua = np.zeros((ny, nx), dtype=bool)
    mascara_agua[:, 27:] = True
    dem[mascara_agua] = np.nan

    fatia_depressao = (slice(5, 10), slice(3, 8))
    dem[fatia_depressao] = 1.0

    fatia_canal = (7, slice(8, 27))
    dem[fatia_canal] = np.float32(cota_canal_m)

    cobertura = np.zeros((ny, nx), dtype=np.uint8)
    cobertura[fatia_canal] = 33

    return dem, mascara_agua, cobertura, fatia_depressao, fatia_canal


# =============================================================================
# 2. Canal como caminho conecta a depressão
# =============================================================================

def teste_2_canal_caminho() -> bool:
    dem, agua, cobertura, dep, canal = _grade_canal_mar_depressao(cota_canal_m=2.4)
    cota = 1.5

    caminho = core.mascara_caminho(dem, agua, cobertura)

    m_sem = core.mascara_inundacao(dem, agua, cota, mascara_agua=agua,
                                   semear_bordas=False)
    m_com = core.mascara_inundacao(dem, agua, cota, mascara_agua=agua,
                                   mascara_caminho=caminho, semear_bordas=False)

    dep_isolada_sem = bool(m_sem["isolada"][dep].all())
    dep_inundada_sem = bool(m_sem["inundada"][dep].any())
    dep_inundada_com = bool(m_com["inundada"][dep].all())
    dep_isolada_com = bool(m_com["isolada"][dep].any())
    canal_fora_das_classes = bool(
        not m_com["inundada"][canal].any() and not m_com["isolada"][canal].any())

    ok = (dep_isolada_sem and not dep_inundada_sem
          and dep_inundada_com and not dep_isolada_com
          and canal_fora_das_classes)
    print(f"  [2] canal como caminho | sem canais: isolada={dep_isolada_sem} | "
          f"com canais: inundada={dep_inundada_com} | "
          f"canal fora de inundada/isolada={canal_fora_das_classes} "
          f"-> {'OK' if ok else 'FALHOU'}")
    return ok


# =============================================================================
# 3. Lagoa classe 33 interior não vira fonte falsa
# =============================================================================

def teste_3_lagoa_nao_e_fonte() -> bool:
    ny, nx = 20, 30
    dem = np.full((ny, nx), 5.0, dtype="float32")
    mascara_agua = np.zeros((ny, nx), dtype=bool)  # nenhuma água real na grade

    fatia_terreno = (slice(5, 15), slice(5, 20))
    dem[fatia_terreno] = 1.0

    fatia_lagoa = (slice(9, 11), slice(11, 14))
    dem[fatia_lagoa] = 0.3
    cobertura = np.zeros((ny, nx), dtype=np.uint8)
    cobertura[fatia_lagoa] = 33

    cota = 1.5
    caminho = core.mascara_caminho(dem, mascara_agua, cobertura)

    m = core.mascara_inundacao(dem, mascara_agua, cota, mascara_agua=mascara_agua,
                               mascara_caminho=caminho, semear_bordas=False)

    terreno_isolado = bool(m["isolada"][fatia_terreno].all())
    terreno_nao_inundado = bool(not m["inundada"][fatia_terreno].any())

    ok = terreno_isolado and terreno_nao_inundado
    print(f"  [3] lagoa não é fonte | terreno ao redor isolado={terreno_isolado} "
          f"-> {'OK' if ok else 'FALHOU'}")
    return ok


# =============================================================================
# 4. Salvaguarda de cota (canal alto não conta como caminho)
# =============================================================================

def teste_4_salvaguarda_cota() -> bool:
    dem, agua, cobertura, dep, canal = _grade_canal_mar_depressao(cota_canal_m=8.0)
    cota = 1.5

    caminho = core.mascara_caminho(dem, agua, cobertura)  # cota_max_m padrão = 6.0
    assert not caminho[canal].any(), "canal a 8 m não deveria virar caminho (cota_max=6 m)"

    m_com = core.mascara_inundacao(dem, agua, cota, mascara_agua=agua,
                                   mascara_caminho=caminho, semear_bordas=False)

    dep_continua_isolada = bool(m_com["isolada"][dep].all())
    dep_nao_inundada = bool(not m_com["inundada"][dep].any())

    ok = dep_continua_isolada and dep_nao_inundada
    print(f"  [4] salvaguarda de cota | depressão continua isolada={dep_continua_isolada} "
          f"-> {'OK' if ok else 'FALHOU'}")
    return ok


# =============================================================================
# 5. Equivalência com caminhos_canais desligado
# =============================================================================

def teste_5_equivalencia_flag_desligada() -> bool:
    dem, agua, cobertura, dep, canal = _grade_canal_mar_depressao(cota_canal_m=2.4)
    cota = 1.5
    caminho = core.mascara_caminho(dem, agua, cobertura)

    valor_original = core.CONFIG_INUNDACAO["caminhos_canais"]
    try:
        core.CONFIG_INUNDACAO["caminhos_canais"] = False
        m_flag_off = core.mascara_inundacao(dem, agua, cota, mascara_agua=agua,
                                            mascara_caminho=caminho, semear_bordas=False)
    finally:
        core.CONFIG_INUNDACAO["caminhos_canais"] = valor_original

    m_referencia = core.mascara_inundacao(dem, agua, cota, mascara_agua=agua,
                                          semear_bordas=False)  # sem mascara_caminho

    iguais_inundada = bool(np.array_equal(m_flag_off["inundada"], m_referencia["inundada"]))
    iguais_isolada = bool(np.array_equal(m_flag_off["isolada"], m_referencia["isolada"]))

    ok = iguais_inundada and iguais_isolada
    print(f"  [5] equivalência (caminhos_canais=False) | "
          f"inundada idêntica={iguais_inundada} | isolada idêntica={iguais_isolada} "
          f"-> {'OK' if ok else 'FALHOU'}")
    return ok


# =============================================================================
# 6. Web x local — raster de limiar bate com o flood-fill, com e sem canais
# =============================================================================

def teste_6_web_local() -> bool:
    dem, agua, cobertura, dep, canal = _grade_canal_mar_depressao(cota_canal_m=2.4)
    valido = np.isfinite(dem)
    area_pixel_m2 = 30.0 * 30.0

    dem_cm = np.where(valido, np.round(dem * 100.0), -32768).astype(np.int16)
    caminho = core.mascara_caminho(dem, agua, cobertura)

    limiar_sem, _ = m03.etapa_5_limiar(dem_cm, agua, valido, caminho_r=None)
    limiar_com, _ = m03.etapa_5_limiar(dem_cm, agua, valido, caminho_r=caminho)

    dados_dem = {
        "dem": dem, "mask_oceano": agua, "area_pixel_m2": area_pixel_m2,
    }

    cotas = [0.5, 1.0, 1.5, 2.0]
    tudo_ok = True
    for cota in cotas:
        ref_sem = core.mascara_inundacao(dem, agua, cota, mascara_agua=agua,
                                         semear_bordas=True)
        alt_sem = fonte.mascara_inundacao_auto(core, dados_dem, cota, limiar=limiar_sem)
        ok_sem = np.array_equal(ref_sem["inundada"], alt_sem["inundada"])

        ref_com = core.mascara_inundacao(dem, agua, cota, mascara_agua=agua,
                                         mascara_caminho=caminho, semear_bordas=True)
        alt_com = fonte.mascara_inundacao_auto(core, dados_dem, cota, usar_canais=True,
                                               limiar_canais=limiar_com)
        ok_com = np.array_equal(ref_com["inundada"], alt_com["inundada"])

        tudo_ok = tudo_ok and ok_sem and ok_com
        print(f"      cota={cota:.1f} m | sem canais bate={ok_sem} | com canais bate={ok_com}")

    # Também exercita fonte.validar_limiar (versão "print", usada durante o
    # desenvolvimento) — não deve levantar exceção.
    fonte.validar_limiar(core, dados_dem, agua, limiar_sem, cotas=cotas,
                         limiar_canais=limiar_com, mascara_caminho=caminho)

    print(f"  [6] web x local (limiar sem/com canais) -> {'OK' if tudo_ok else 'FALHOU'}")
    return tudo_ok


# =============================================================================
# 7. Margem d'água (v1.4b): pixel com 30% de água continua terra na área,
#    mas conduz conexão hidráulica
# =============================================================================

def teste_7_margem_conduz_sem_contar_area() -> bool:
    # --- Parte A: fração exata de 30% -------------------------------------
    # Mesmo CRS dos dois lados (sem conversão geográfica real), para
    # controlar a razão de agregação com exatidão: 10 px nativos de 3 m por
    # px de saída de 30 m (10x10 = 100 px nativos por pixel de destino).
    crs_original = config.CRS_FONTE
    config.CRS_FONTE = config.CRS_ALVO
    try:
        x0, y0 = 500000.0, 8000000.0
        transform_nativa = from_origin(x0, y0, 3.0, 3.0)
        transform_alvo = from_origin(x0, y0, 30.0, 30.0)

        # 3 blocos de 10x10 px nativos lado a lado: 0% / 30% / 100% de água.
        agua_nat = np.zeros((10, 30), dtype=bool)
        agua_nat[0:3, 10:20] = True   # bloco do meio: 3x10 = 30 de 100 px -> 30%
        agua_nat[:, 20:30] = True     # bloco da direita: 100%

        agua_area, agua_conexao, agua_margem = m01.reprojetar_mascaras_agua(
            agua_nat, transform_nativa, transform_alvo, (1, 3))

        fracao_ok = (not agua_area[0, 0] and not agua_area[0, 1] and agua_area[0, 2])
        conexao_ok = (not agua_conexao[0, 0] and agua_conexao[0, 1] and agua_conexao[0, 2])
        margem_ok = (not agua_margem[0, 0] and agua_margem[0, 1] and not agua_margem[0, 2])
        parte_a = bool(fracao_ok and conexao_ok and margem_ok)

        print(f"  [7a] fração exata 30% | agua_area={agua_area[0].tolist()} "
              f"(esperado [F,F,T]) | agua_conexao={agua_conexao[0].tolist()} "
              f"(esperado [F,T,T]) | agua_margem={agua_margem[0].tolist()} "
              f"(esperado [F,T,F]) -> {'OK' if parte_a else 'FALHOU'}")
    finally:
        config.CRS_FONTE = crs_original

    # --- Parte B: a margem conduz conexão sem contar como área/inundada --
    # Reaproveita o layout de _grade_canal_mar_depressao (mar + depressão +
    # "canal" a 2,4 m); aqui o "canal" vira MARGEM D'ÁGUA REAL diretamente —
    # sem cobertura MapBiomas, sem salvaguarda de cota.
    dem, agua, _cobertura, dep, pos_margem = _grade_canal_mar_depressao(cota_canal_m=2.4)
    margem = np.zeros(dem.shape, dtype=bool)
    margem[pos_margem] = True
    cota = 1.5

    m_sem = core.mascara_inundacao(dem, agua, cota, mascara_agua=agua, semear_bordas=False)
    m_com = core.mascara_inundacao(dem, agua, cota, mascara_agua=agua,
                                   mascara_caminho=margem, semear_bordas=False)

    dep_isolada_sem = bool(m_sem["isolada"][dep].all())
    dep_inundada_com = bool(m_com["inundada"][dep].all())
    margem_fora_das_classes = bool(
        not m_com["inundada"][pos_margem].any() and not m_com["isolada"][pos_margem].any())
    # a cota da margem (2,4 m) fica ACIMA do cenário (1,5 m): continua TERRA
    # na área (dem finito, nunca virou NaN) — só passou a conduzir conexão.
    margem_e_terra = bool(np.isfinite(dem[pos_margem]).all())

    parte_b = bool(dep_isolada_sem and dep_inundada_com
                  and margem_fora_das_classes and margem_e_terra)
    print(f"  [7b] margem conduz sem contar área | sem margem: isolada={dep_isolada_sem} "
          f"| com margem: inundada={dep_inundada_com} | margem fora de "
          f"inundada/isolada={margem_fora_das_classes} | margem é terra "
          f"(dem finito)={margem_e_terra} -> {'OK' if parte_b else 'FALHOU'}")

    ok = parte_a and parte_b
    print(f"  [7] margem d'água (30%) -> {'OK' if ok else 'FALHOU'}")
    return ok


# =============================================================================
# EXECUÇÃO
# =============================================================================

def main():
    testes = [
        teste_1_mascara_nativa,
        teste_2_canal_caminho,
        teste_3_lagoa_nao_e_fonte,
        teste_4_salvaguarda_cota,
        teste_5_equivalencia_flag_desligada,
        teste_6_web_local,
        teste_7_margem_conduz_sem_contar_area,
    ]

    print("=" * 70)
    print("teste_conectividade.py — v1.4 (máscara nativa + canais MapBiomas)")
    print("=" * 70)

    resultados = []
    for teste in testes:
        try:
            resultados.append(teste())
        except Exception:
            print(f"  {teste.__name__} -> FALHOU (exceção)")
            traceback.print_exc()
            resultados.append(False)

    print("=" * 70)
    if all(resultados):
        print(f"OK — {len(resultados)}/{len(resultados)} testes passaram")
    else:
        n_falhou = resultados.count(False)
        print(f"FALHOU — {n_falhou}/{len(resultados)} teste(s) não passaram")
    print("=" * 70)

    sys.exit(0 if all(resultados) else 1)


if __name__ == "__main__":
    main()
