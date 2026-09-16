"""
cobertura.py — Cobertura e uso do solo (MapBiomas) para o simulador NMRM
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB — Caravelas (BA)

Módulo SEM interface. Guarda a legenda oficial da Coleção 11 do MapBiomas,
lê o recorte de Caravelas produzido por `04_prepara_cobertura.py` e devolve
tabela de área por classe. Quem desenha mapa é `mapa_web.py`; quem desenha
controle é a interface.

ESTADO (v1.3): a cobertura entra na ferramenta apenas como CAMADA VISUAL.
Nenhum cruzamento estatístico com a máscara de inundação é feito aqui — isso
é a Parte 2 (resposta ecológica) e depende de decisões ecológicas que ainda
não foram tomadas. O que este módulo garante é que a camada exibida tem
legenda conferida e procedência declarada.

Autor: Helio | Assistência: Claude
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import rasterio

# =============================================================================
# 1. PARÂMETROS CENTRALIZADOS
# =============================================================================

CONFIG_COBERTURA = {
    "colecao":            "MapBiomas Coleção 11",
    "ano_referencia":     2025,
    "nodata":             0,       # convenção MapBiomas: 0 = sem dado
    "reamostragem":       "nearest",   # categórico — NUNCA bilinear/cúbica
    "cor_desconhecida":   "#9E9E9E",   # código fora da legenda conferida
    "n_classes_legenda":  20,          # máximo de itens na legenda da interface
    "pct_minimo_legenda": 0.05,        # abaixo disto a classe some da legenda (%)

    # Classes sobre as quais a cota do FABDEM carrega dossel residual conhecido e
    # NÃO deve ser lida como cota do solo. Hoje só o mangue, medido na validação
    # de 05/09/2026 (ver "alerta_mangue" abaixo). A interface consulta esta lista
    # em vez de comparar com o número 5 solto no meio do código.
    "codigos_alerta_dossel": [5],
}

# Procedência — mesmo padrão de `slr_core.FONTE_CENARIOS`. A regra 1 do projeto
# vale para legenda também: código de classe pintado com o nome errado vira
# citação errada no relatório.
FONTE_COBERTURA = {
    "referencia": (
        "MapBiomas Brasil, Coleção 11 (2025), cobertura e uso da terra a 30 m. "
        "Arquivo brazil_coverage-col11_2025.tif."
    ),
    "legenda": (
        "Códigos e cores transcritos do CSV oficial de legenda da Coleção 11 "
        "(legend_code_mapbiomas_brazil_collection_11.csv, brasil.mapbiomas.org), "
        "conferido em set/2026."
    ),
    "conferido": (
        "Os 17 códigos que ocorrem no recorte de Caravelas foram conferidos um a "
        "um contra o CSV oficial. Os demais códigos da Coleção 11 NÃO foram "
        "transcritos — se aparecerem, a interface os mostra como "
        "'fora da legenda conferida', nunca com nome inventado."
    ),
    "validacao": (
        "Conferência qualitativa por setor contra o Laudo biológico do sistema "
        "Caravelas–Nova Viçosa (criação da RESEX Cassurubá) — ver "
        "docs/validacao_mapbiomas_laudo.md."
    ),
    "limitacao": (
        "Classificação de imagem de satélite a 30 m. Não distingue fitofisionomias "
        "de restinga (herbácea inundada, arbustiva de moitas, mata inundada) que o "
        "laudo separa em campo, e a fronteira mangue/apicum é sensível ao ano e à "
        "maré da cena."
    ),
    # Achado da validação de 05/09/2026 — ver docs/validacao_mapbiomas_laudo.md §4.4.
    # Fica aqui, e não só no doc, porque é a informação que impede alguém de ler
    # "mangue quase não alaga" no mapa e escrever isso no relatório.
    "alerta_mangue": (
        "O FABDEM coloca o Mangue em mediana de 4,31 m e o Apicum em 1,91 m — a ordem "
        "INVERTIDA da que a ecologia prevê (o manguezal é intermarés; a planície "
        "hipersalina fica acima dele). A diferença, de ordem de 3 m, é dossel residual "
        "de mangue que o MDE não removeu, e é maior que todo o NMRM projetado para "
        "2100. Consequência: a exposição do manguezal aparece SUBESTIMADA nesta "
        "ferramenta, e área de mangue perdida por cenário não deve ser reportada até "
        "isso ser corrigido. O apicum, sem dossel, é o controle interno: mede certo e "
        "responde como esperado (56% abaixo de +2 m)."
    ),
}

# -----------------------------------------------------------------------------
# LEGENDA — código de pixel -> nome e cor oficiais
#
# `costeira=True` marca as classes que respondem diretamente ao NMRM na planície
# de Caravelas. É só um marcador de leitura (ordena a legenda da interface); a
# resposta ecológica em si é a Parte 2 e não está decidida.
# -----------------------------------------------------------------------------

LEGENDA_COL11 = {
    3:  {"nome": "Formação Florestal",              "cor": "#1F8D49", "costeira": False},
    5:  {"nome": "Mangue",                          "cor": "#04381D", "costeira": True},
    9:  {"nome": "Silvicultura",                    "cor": "#7A5900", "costeira": False},
    11: {"nome": "Campo Alagado e Área Pantanosa",  "cor": "#519799", "costeira": True},
    12: {"nome": "Formação Campestre",              "cor": "#D6BC74", "costeira": False},
    15: {"nome": "Pastagem",                        "cor": "#EDDE8E", "costeira": False},
    21: {"nome": "Mosaico de Usos",                 "cor": "#FFEFC3", "costeira": False},
    23: {"nome": "Praia, Duna e Areal",             "cor": "#FFA07A", "costeira": True},
    24: {"nome": "Área Urbanizada",                 "cor": "#D4271E", "costeira": True},
    25: {"nome": "Outras Áreas não Vegetadas",      "cor": "#DB4D4F", "costeira": False},
    32: {"nome": "Apicum",                          "cor": "#FC8114", "costeira": True},
    33: {"nome": "Rio, Lago e Oceano",              "cor": "#2532E4", "costeira": True},
    41: {"nome": "Outras Lavouras Temporárias",     "cor": "#F54CA9", "costeira": False},
    46: {"nome": "Café",                            "cor": "#D68FE2", "costeira": False},
    48: {"nome": "Outras Lavouras Perenes",         "cor": "#E6CCFF", "costeira": False},
    49: {"nome": "Restinga Arbórea",                "cor": "#02D659", "costeira": True},
    50: {"nome": "Restinga Herbácea ou Arbustiva",  "cor": "#FFAA5F", "costeira": True},
}


# =============================================================================
# 2. UTILIDADES
# =============================================================================

def _print(msg: str) -> None:
    """
    Print à prova de console cp1252 (Windows). Mesmo motivo de
    `slr_core._print`: um caractere fora da tabela derruba o script inteiro
    no meio de uma linha de diagnóstico.
    """
    try:
        print(msg)
    except UnicodeEncodeError:
        cod = getattr(sys.stdout, "encoding", None) or "ascii"
        print(msg.encode(cod, errors="replace").decode(cod, errors="replace"))


def classe(codigo: int) -> dict:
    """
    Devolve {nome, cor, costeira, conferida} para um código de pixel.

    Código fora da legenda conferida NÃO recebe nome inventado: volta rotulado
    como não conferido, em cinza, para a interface poder avisar.
    """
    if int(codigo) in LEGENDA_COL11:
        return {**LEGENDA_COL11[int(codigo)], "conferida": True}
    return {
        "nome": f"código {int(codigo)} — fora da legenda conferida",
        "cor": CONFIG_COBERTURA["cor_desconhecida"],
        "costeira": False,
        "conferida": False,
    }


def nome_classe(codigo: int) -> str:
    return classe(codigo)["nome"]


def alerta_dossel(codigo) -> bool:
    """
    True quando a cota do MDE naquela classe é sabidamente contaminada por
    dossel e não deve ser lida como cota do solo — hoje, só o manguezal.
    Ver FONTE_COBERTURA["alerta_mangue"] e
    docs/validacao_mapbiomas_laudo.md §4.4.
    """
    if codigo is None:
        return False
    return int(codigo) in CONFIG_COBERTURA["codigos_alerta_dossel"]


# =============================================================================
# 3. LEITURA DO RECORTE
# =============================================================================

def carregar_cobertura(caminho: str) -> dict | None:
    """
    Lê o GeoTIFF de cobertura recortado por `04_prepara_cobertura.py`.

    Retorna dicionário com:
        classes        : ndarray uint8 (código de classe; 0 = sem dado)
        transform, crs, res_x, res_y, area_pixel_m2, nodata, caminho

    Devolve None se o arquivo não existir — a camada é opcional e a interface
    precisa poder seguir sem ela.
    """
    if not caminho or not os.path.exists(caminho):
        return None

    with rasterio.open(caminho) as src:
        arr = src.read(1)
        transform = src.transform
        crs = src.crs
        nodata = src.nodata
        tags = src.tags()

    nodata = int(nodata) if nodata is not None else CONFIG_COBERTURA["nodata"]
    res_x, res_y = abs(transform.a), abs(transform.e)

    n_valido = int((arr != nodata).sum())
    _print(f"[COBERTURA] {os.path.basename(caminho)} | {arr.shape[0]}x{arr.shape[1]} px "
           f"| res={res_x:.0f}x{res_y:.0f} m | CRS={crs.to_string() if crs else 'indefinido'}")
    _print(f"[COBERTURA] {n_valido} px com classe válida "
           f"({n_valido * res_x * res_y / 1e6:.1f} km²) | "
           f"{len(np.unique(arr[arr != nodata]))} classes distintas")

    return {
        "classes": arr,
        "transform": transform,
        "crs": crs,
        "res_x": res_x,
        "res_y": res_y,
        "area_pixel_m2": res_x * res_y,
        "nodata": nodata,
        "caminho": caminho,
        "tags": tags,
    }


# =============================================================================
# 4. TABELA DE ÁREA POR CLASSE
# =============================================================================

def resumo_classes(dados_cob: dict) -> pd.DataFrame:
    """
    Área e percentual de cada classe presente no recorte.

    Colunas: Código | Classe | Área (km²) | % da área classificada | Conferida
    """
    arr = dados_cob["classes"]
    nodata = dados_cob["nodata"]
    area_px_km2 = dados_cob["area_pixel_m2"] / 1e6

    valido = arr != nodata
    codigos, contagem = np.unique(arr[valido], return_counts=True)
    total = int(contagem.sum()) or 1

    linhas = []
    for cod, n in zip(codigos, contagem):
        info = classe(int(cod))
        linhas.append({
            "Código": int(cod),
            "Classe": info["nome"],
            "Área (km²)": round(float(n) * area_px_km2, 2),
            "% da área classificada": round(100.0 * n / total, 2),
            "Costeira": info["costeira"],
            "Conferida": info["conferida"],
        })

    df = pd.DataFrame(linhas).sort_values("Área (km²)", ascending=False,
                                          ignore_index=True)

    nao_conf = df.loc[~df["Conferida"], "Código"].tolist()
    if nao_conf:
        _print(f"[COBERTURA] AVISO: códigos fora da legenda conferida: {nao_conf}. "
               "A interface os mostra em cinza, sem nome de classe.")
    return df


def cores_overlay(dados_cob: dict) -> dict:
    """
    Mapa {código: '#RRGGBB'} das classes presentes, pronto para
    `mapa_web.gerar_overlay_web`. Não inclui o nodata.
    """
    arr = dados_cob["classes"]
    codigos = np.unique(arr[arr != dados_cob["nodata"]])
    return {int(c): classe(int(c))["cor"] for c in codigos}


def legenda_para_interface(df_resumo: pd.DataFrame) -> list[dict]:
    """
    Itens de legenda ordenados para a interface: classes costeiras primeiro
    (são as que respondem ao NMRM), depois as demais por área. Classes com
    participação irrisória saem, para a legenda caber ao lado do mapa.
    """
    lim = CONFIG_COBERTURA["pct_minimo_legenda"]
    n_max = CONFIG_COBERTURA["n_classes_legenda"]
    df = df_resumo[df_resumo["% da área classificada"] >= lim]
    df = df.sort_values(["Costeira", "Área (km²)"], ascending=[False, False])
    return [
        {
            "codigo": int(r["Código"]),
            "nome": r["Classe"],
            "cor": classe(int(r["Código"]))["cor"],
            "area_km2": float(r["Área (km²)"]),
            "pct": float(r["% da área classificada"]),
            "costeira": bool(r["Costeira"]),
            "conferida": bool(r["Conferida"]),
        }
        for _, r in df.head(n_max).iterrows()
    ]
