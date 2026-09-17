"""
fonte_dados.py — Resolução de fonte de dados (local x web) para o simulador NMRM
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB — Caravelas (BA)

Colocar em `src/fonte_dados.py`.

Motivação
---------
O simulador roda em dois contextos com restrições distintas:

    LOCAL  : dados completos em NMRM_DIR_DADOS, float32, flood-fill em tempo real
    WEB     : dados versionados em dados_web/, int16 em cm, limiar pré-computado

Este módulo isola essa diferença num único ponto. O resto do código
(`slr_core.py`, `02_simulador_nmrm.py`) não precisa saber em qual modo está.

Regra de decisão: se NMRM_DIR_DADOS existe E o MDE processado está lá,
roda em modo local. Caso contrário, cai para dados_web/.

Autor: Helio | Assistência: Claude
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import rasterio

# =============================================================================
# PARÂMETROS
# =============================================================================

CONFIG_FONTE = {
    "subdir_web": "dados_web",
    "arq_dem_web": "dem_30m_web.tif",
    "arq_agua_web": "mascara_agua_web.tif",
    "arq_limiar_web": "limiar_conexao_web.tif",
    # v1.4 — segundo raster de limiar, gerado com canais MapBiomas (classe 33)
    # como caminho hidráulico. Opcional: se faltar (dados_web antigo, gerado
    # antes da v1.4, ou cobertura ausente no modo local do 03), a interface
    # cai para o raster sem canais.
    "arq_limiar_canais_web": "limiar_conexao_canais_web.tif",
    "arq_meta_web": "metadados_web.json",
    # v1.3 — cobertura do solo (MapBiomas Col. 11), produto do 04_prepara_cobertura.py.
    # Camada OPCIONAL: se faltar, a interface desliga o controle e segue.
    "arq_cobertura_web": "cobertura_web.tif",
    "arq_cobertura_local": "caravelas_mapbiomas_col11_2025_utm24s_30m.tif",

    # Variável de ambiente que força o modo, ignorando a autodetecção.
    "env_modo": "NMRM_MODO",

    "fator_escala_cm": 100.0,   # int16 (cm) -> float (m)
    "nunca_alaga": 32767,       # sentinela do raster de limiar
    "valor_oceano": 0.0,        # FABDEM: oceano == 0.0 exato
    "tol_oceano": 1e-6,
}

MODO_LOCAL = "local"
MODO_WEB = "web"


# =============================================================================
# 1. RESOLUÇÃO DE MODO
# =============================================================================

def resolver_fonte(raiz_repo: str | Path = None) -> dict:
    """
    Decide o modo de operação e devolve os caminhos correspondentes.

    Retorna dicionário com:
        modo       : "local" | "web"
        dem        : caminho do GeoTIFF de elevação
        agua       : caminho da máscara d'água (ou None)
        limiar     : caminho do raster de limiar (ou None — só existe no modo web)
        cobertura  : caminho do recorte MapBiomas (ou None — camada opcional)
        metadados  : dict do metadados_web.json (ou None)
        rotulo     : texto curto para exibir na interface
    """
    raiz = Path(raiz_repo) if raiz_repo else Path(__file__).resolve().parent.parent

    # --- Tentativa 0: modo forçado por variável de ambiente ------------------
    # NMRM_MODO=web faz o resolvedor IGNORAR os dados completos e usar
    # dados_web/, mesmo com o MDE local presente. Serve para pré-visualizar,
    # na própria máquina, exatamente a ferramenta que vai ao ar: mesmo raster
    # leve, mesmo limiar pré-computado, mesmos controles bloqueados.
    # NMRM_MODO=local é o comportamento padrão, explicitado.
    #   PowerShell:  $env:NMRM_MODO = "web"   (limpar: Remove-Item Env:NMRM_MODO)
    #   bash:        NMRM_MODO=web streamlit run 02_simulador_nmrm.py
    forcado = os.environ.get(CONFIG_FONTE["env_modo"], "").strip().lower()
    if forcado and forcado not in (MODO_LOCAL, MODO_WEB):
        print(f"[FONTE] {CONFIG_FONTE['env_modo']}={forcado!r} não reconhecido "
              f"(use {MODO_LOCAL!r} ou {MODO_WEB!r}). Ignorando.")
        forcado = ""
    if forcado == MODO_WEB:
        print(f"[FONTE] {CONFIG_FONTE['env_modo']}=web — pulando os dados "
              "completos e usando dados_web/ (pré-visualização do modo público).")

    # --- Tentativa 1: modo local via config.py ------------------------------
    try:
        if forcado == MODO_WEB:
            raise ImportError("modo web forçado por NMRM_MODO")
        import config
        dem_local = Path(str(config.MDE_PROCESSADO))
        agua_local = Path(str(config.MASCARA_AGUA))
        cob_local = Path(str(config.DIR_AUXILIAR)) / CONFIG_FONTE["arq_cobertura_local"]
        if dem_local.exists():
            print(f"[FONTE] modo=LOCAL | {dem_local}")
            if not cob_local.exists():
                print("[FONTE] cobertura MapBiomas ausente — rode 04_prepara_cobertura.py "
                      "para habilitar a camada. A simulação não depende dela.")
            return {
                "modo": MODO_LOCAL,
                "dem": str(dem_local),
                "agua": str(agua_local) if agua_local.exists() else None,
                "limiar": None,
                "limiar_canais": None,   # modo local sempre faz flood-fill em tempo real
                "cobertura": str(cob_local) if cob_local.exists() else None,
                "metadados": None,
                "rotulo": "Dados completos (30 m, float32) — flood-fill em tempo real",
                "forcado": False,
            }
    except (ImportError, AttributeError) as e:
        # O ImportError acima é controle de fluxo quando o modo web foi
        # forçado — nesse caso o config.py está ótimo e não há o que avisar.
        if forcado != MODO_WEB:
            print(f"[FONTE] config.py indisponível ou incompleto ({e}). "
                  "Tentando modo web.")

    # --- Tentativa 2: modo web ----------------------------------------------
    dir_web = raiz / CONFIG_FONTE["subdir_web"]
    dem_web = dir_web / CONFIG_FONTE["arq_dem_web"]

    if not dem_web.exists():
        raise FileNotFoundError(
            f"Nenhuma fonte de dados encontrada.\n"
            f"  Modo local: defina NMRM_DIR_DADOS e rode 01_mapa_elevacao.py\n"
            f"  Modo web  : rode 03_prepara_dem_web.py para gerar {dir_web}"
        )

    agua_web = dir_web / CONFIG_FONTE["arq_agua_web"]
    limiar_web = dir_web / CONFIG_FONTE["arq_limiar_web"]
    limiar_canais_web = dir_web / CONFIG_FONTE["arq_limiar_canais_web"]
    meta_web = dir_web / CONFIG_FONTE["arq_meta_web"]
    cob_web = dir_web / CONFIG_FONTE["arq_cobertura_web"]

    meta = None
    if meta_web.exists():
        with open(meta_web, encoding="utf-8") as f:
            meta = json.load(f)

    clamp = meta["config"]["clamp_m"] if meta else None
    rot = "Dados leves (30 m, int16 cm) — conectividade pré-computada"
    if clamp:
        rot += f" · teto de terreno em +{clamp:.0f} m"

    print(f"[FONTE] modo=WEB | {dem_web}")
    return {
        "modo": MODO_WEB,
        "dem": str(dem_web),
        "agua": str(agua_web) if agua_web.exists() else None,
        "limiar": str(limiar_web) if limiar_web.exists() else None,
        "limiar_canais": str(limiar_canais_web) if limiar_canais_web.exists() else None,
        "cobertura": str(cob_web) if cob_web.exists() else None,
        "metadados": meta,
        "rotulo": rot,
        # True = o modo web foi pedido à mão, não deduzido da ausência de dados.
        # A interface usa isto para avisar que é pré-visualização.
        "forcado": forcado == MODO_WEB,
    }


# =============================================================================
# 2. LEITURA DO MDE — tolerante a float32 (m) e int16 (cm)
# =============================================================================

def carregar_dem_auto(caminho: str) -> dict:
    """
    Substitui `core.carregar_dem` cobrindo os dois formatos.

    Diferenças em relação ao original:

    1. Detecta dtype inteiro e converte de centímetros para metros.
    2. NÃO aplica o teste `dem == 0.0` quando o raster é inteiro. No DEM
       em centímetros, qualquer terreno entre -0,005 e +0,005 m arredonda
       para exatamente 0 e seria apagado como se fosse oceano. Como o
       oceano já vem gravado como nodata e a máscara d'água é explícita,
       o teste é desnecessário nesse formato.

    Retorna o MESMO dicionário de `core.carregar_dem`, para compatibilidade.
    """
    if not os.path.exists(caminho):
        raise FileNotFoundError(f"MDE não encontrado: {caminho}")

    with rasterio.open(caminho) as src:
        bruto = src.read(1)
        perfil = src.profile.copy()
        transform = src.transform
        crs = src.crs
        nodata = src.nodata
        dtype_orig = src.dtypes[0]

    inteiro = np.issubdtype(bruto.dtype, np.integer)

    if inteiro:
        invalido = (bruto == nodata) if nodata is not None else np.zeros(bruto.shape, bool)
        dem = bruto.astype("float32") / CONFIG_FONTE["fator_escala_cm"]
        dem[invalido] = np.nan
        mask_oceano = np.zeros(dem.shape, dtype=bool)  # oceano já é nodata
        print(f"[DEM] formato int16 (cm) detectado — convertido para metros "
              f"(fator {CONFIG_FONTE['fator_escala_cm']:.0f})")
        print("[DEM] teste dem==0.0 desativado: em cm ele apagaria terreno real "
              "próximo de zero. Oceano vem de nodata + máscara d'água.")
    else:
        dem = bruto.astype("float32")
        if nodata is not None and not np.isnan(nodata):
            dem[dem == nodata] = np.nan
        mask_oceano = np.isclose(dem, CONFIG_FONTE["valor_oceano"],
                                 atol=CONFIG_FONTE["tol_oceano"], equal_nan=False)
        dem[mask_oceano] = np.nan

    res_x, res_y = abs(transform.a), abs(transform.e)
    area_pixel = res_x * res_y
    n_terra = int(np.isfinite(dem).sum())

    print(f"[DEM] {os.path.basename(caminho)} | {dem.shape[0]}x{dem.shape[1]} px "
          f"| dtype={dtype_orig} | res={res_x:.1f}x{res_y:.1f} m "
          f"| CRS={crs.to_string() if crs else 'indefinido'}")
    print(f"[DEM] terra={n_terra} px ({n_terra * area_pixel / 1e6:.1f} km²) | "
          f"z: min={np.nanmin(dem):.2f} m | mediana={np.nanmedian(dem):.2f} m | "
          f"max={np.nanmax(dem):.2f} m")

    return {
        "dem": dem,
        "mask_oceano": mask_oceano,
        "transform": transform,
        "crs": crs,
        "res_x": res_x,
        "res_y": res_y,
        "area_pixel_m2": area_pixel,
        "perfil": perfil,
        "caminho": caminho,
        "formato_inteiro": inteiro,
    }


# =============================================================================
# 3. RASTER DE LIMIAR
# =============================================================================

def carregar_limiar(caminho: str | None) -> np.ndarray | None:
    """
    Lê o raster de limiar de conexão hidráulica gerado por
    `03_prepara_dem_web.py`.

    Cada pixel guarda o menor nível de mar (em cm) no qual aquele pixel
    passa a estar inundado E conectado ao oceano. Pixels que nunca
    conectam recebem CONFIG_FONTE["nunca_alaga"].

    Isso funciona porque a inundação conectada é monotônica: se um pixel
    conecta no nível h, conecta em qualquer nível maior. O limiar é
    portanto único e bem definido, e um raster substitui o flood-fill.
    """
    if not caminho or not os.path.exists(caminho):
        return None
    with rasterio.open(caminho) as src:
        limiar = src.read(1).astype(np.int32)  # int32 evita overflow nas comparações
        nodata = src.nodata
    if nodata is not None:
        limiar[limiar == int(nodata)] = CONFIG_FONTE["nunca_alaga"]
    n_util = int((limiar < CONFIG_FONTE["nunca_alaga"]).sum())
    print(f"[LIMIAR] {os.path.basename(caminho)} | {n_util} px com limiar definido "
          f"| máx útil = {limiar[limiar < CONFIG_FONTE['nunca_alaga']].max() / 100:.2f} m")
    return limiar


def cota_maxima_limiar(limiar: np.ndarray | None) -> float | None:
    """Maior cota (m) para a qual o raster de limiar é confiável."""
    if limiar is None:
        return None
    util = limiar[limiar < CONFIG_FONTE["nunca_alaga"]]
    return float(util.max()) / 100.0 if util.size else None


# =============================================================================
# 4. MÁSCARA DE INUNDAÇÃO — despacha entre flood-fill e limiar
# =============================================================================

def mascara_inundacao_auto(core,
                           dados_dem: dict,
                           cota_m: float,
                           conectividade: bool = True,
                           semear_bordas: bool = True,
                           area_minima_ha: float = 0.0,
                           mascara_agua: np.ndarray = None,
                           limiar: np.ndarray = None,
                           usar_canais: bool = False,
                           mascara_caminho: np.ndarray = None,
                           limiar_canais: np.ndarray = None) -> dict:
    """
    Substitui `core.mascara_inundacao` escolhendo o caminho mais barato.

    Ordem de decisão:
        1. conectividade desligada  -> bathtub direto do DEM (não usa limiar)
        2. limiar disponível         -> consulta O(n), sem scipy.ndimage.label
        3. caso contrário            -> delega para core.mascara_inundacao

    `core` é passado como argumento para evitar import circular.

    ATENÇÃO: o raster de limiar foi gerado com um valor FIXO de
    `semear_bordas`. No modo limiar esse argumento é ignorado — a interface
    deve desabilitar o toggle correspondente.

    `usar_canais` escolhe, no modo limiar, entre `limiar` (sem canais
    MapBiomas) e `limiar_canais` (com canais MapBiomas como caminho
    hidráulico — ver `core.CONFIG_INUNDACAO["caminhos_canais"]`). Se
    `usar_canais=True` mas `limiar_canais` for None (raster ainda não
    gerado), cai de volta para `limiar` sem canais.

    No modo flood-fill (item 3), `mascara_caminho` é repassada tal como
    recebida — SEM gating por `usar_canais` aqui dentro. Isso é proposital
    desde a v1.4b: quem chama decide o que entra nessa máscara (margem
    d'água real, sempre; canal MapBiomas, só se `usar_canais`) e já entrega
    a união pronta. `usar_canais` continua controlando só a ESCOLHA do
    raster de limiar no modo web.
    """
    dem = dados_dem["dem"]
    area_px = dados_dem["area_pixel_m2"]
    valido = np.isfinite(dem)
    abaixo = valido & (dem <= cota_m)

    # --- 1. Bathtub ---------------------------------------------------------
    if not conectividade:
        print(f"[MASCARA] modo=bathtub | cota={cota_m:.2f} m | "
              f"abaixo={int(abaixo.sum())} px")
        return _empacota(abaixo, np.zeros_like(abaixo), abaixo, area_px)

    # --- 2. Atalho pelo raster de limiar ------------------------------------
    limiar_ativo = limiar_canais if (usar_canais and limiar_canais is not None) else limiar
    if limiar_ativo is not None:
        cota_cm = int(round(cota_m * CONFIG_FONTE["fator_escala_cm"]))
        conectada = limiar_ativo <= cota_cm
        inundada = abaixo & conectada
        isolada = abaixo & ~conectada

        if area_minima_ha > 0 and area_px:
            estrutura = np.ones((3, 3), dtype=bool)
            n_min = int(np.ceil(area_minima_ha * 1e4 / area_px))
            inundada = core._remove_manchas_pequenas(inundada, estrutura, n_min)
            isolada = core._remove_manchas_pequenas(isolada, estrutura, n_min)

        _rot_limiar = "com canais" if limiar_ativo is limiar_canais else "sem canais"
        print(f"[MASCARA] modo=limiar pré-computado ({_rot_limiar}) | "
              f"cota={cota_m:.2f} m ({cota_cm} cm) | "
              f"inundada={int(inundada.sum())} px | isolada={int(isolada.sum())} px")
        return _empacota(inundada, isolada, abaixo, area_px)

    # --- 3. Flood-fill em tempo real ----------------------------------------
    return core.mascara_inundacao(
        dem, dados_dem["mask_oceano"], cota_m,
        conectividade=conectividade,
        semear_bordas=semear_bordas,
        area_pixel_m2=area_px,
        area_minima_ha=area_minima_ha,
        mascara_agua=mascara_agua,
        mascara_caminho=mascara_caminho,
    )


def _empacota(inundada, isolada, abaixo, area_pixel_m2):
    return {
        "inundada": inundada,
        "isolada": isolada,
        "abaixo": abaixo,
        "area_pixel_m2": area_pixel_m2,
    }


# =============================================================================
# 5. VALIDAÇÃO CRUZADA — usar durante o desenvolvimento
# =============================================================================

def validar_limiar(core, dados_dem: dict, mascara_agua: np.ndarray,
                   limiar: np.ndarray, cotas=(0.5, 1.0, 2.0, 3.0),
                   semear_bordas: bool = True,
                   limiar_canais: np.ndarray = None,
                   mascara_caminho: np.ndarray = None) -> None:
    """
    Compara o resultado do(s) raster(s) de limiar com o flood-fill em tempo
    real. Roda a checagem sem canais e, se `limiar_canais` for passado
    (junto com `mascara_caminho`), roda de novo com canais — os dois
    precisam bater com seu flood-fill equivalente.

    Rode UMA VEZ em modo local, com os dados leves carregados, para
    confirmar que os dois caminhos dão o mesmo número. Se divergirem,
    quase certamente é incompatibilidade de `semear_bordas` ou de
    conectividade (4 x 8) entre 03_prepara_dem_web.py e CONFIG_INUNDACAO.
    """
    a = dados_dem["area_pixel_m2"] / 1e6

    def _rodar(rotulo, limiar_ref, usar_canais, mascara_cam):
        # "dif" em vez de Δ: esta função é de diagnóstico e roda em console
        # Windows, que não codifica o glifo grego em cp1252.
        print(f"\n  [{rotulo}] Cota (m) | Flood-fill (km²) | Limiar (km²) | dif (km²)")
        print("  " + "-" * 52)
        for cota in cotas:
            ref = core.mascara_inundacao(
                dados_dem["dem"], dados_dem["mask_oceano"], cota,
                conectividade=True, semear_bordas=semear_bordas,
                area_pixel_m2=dados_dem["area_pixel_m2"], mascara_agua=mascara_agua,
                mascara_caminho=mascara_cam)
            alt = mascara_inundacao_auto(
                core, dados_dem, cota, limiar=limiar_ref if not usar_canais else None,
                usar_canais=usar_canais, limiar_canais=limiar_ref if usar_canais else None)
            v_ref = float(ref["inundada"].sum()) * a
            v_alt = float(alt["inundada"].sum()) * a
            flag = "" if abs(v_ref - v_alt) < 0.05 else "   <-- DIVERGE"
            print(f"  {cota:8.2f} | {v_ref:16.2f} | {v_alt:12.2f} | "
                  f"{v_alt - v_ref:+7.2f}{flag}")
        print()

    _rodar("sem canais", limiar, False, None)
    if limiar_canais is not None:
        _rodar("com canais", limiar_canais, True, mascara_caminho)
