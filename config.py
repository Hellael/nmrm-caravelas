"""
config.py — Configuração central do projeto NMRM Caravelas
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB

Único lugar do repositório onde caminhos e recorte da área de estudo são
definidos. Todo script importa daqui. Nunca duplicar constante.
"""

from pathlib import Path
import os
import sys


# =============================================================================
# CONSOLE
# =============================================================================

def configurar_console() -> None:
    """
    Força stdout/stderr em UTF-8.

    Motivo: no Windows o console herda cp1252, e QUALQUER caractere fora dessa
    tabela derruba o script inteiro com UnicodeEncodeError no meio de um
    `print` de diagnóstico — seta (→), delta (Δ), quase-igual (≈). Um print
    de diagnóstico nunca pode matar a simulação.

    `errors="replace"` é a rede de segurança: em terminal que não renderiza o
    glifo, ele vira '?' em vez de exceção. Chamada no import deste módulo, que
    é o primeiro import de todo script do projeto.
    """
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # Streamlit Cloud, notebook ou stream já fechado: segue o baile.
            # A rede de segurança de slr_core._print cobre o resto.
            pass


configurar_console()

# =============================================================================
# CAMINHOS
# =============================================================================

DIR_RAIZ = Path(__file__).resolve().parent

# Os tiles FABDEM somam alguns GB. Se o repositório estiver dentro de uma pasta
# sincronizada (OneDrive, Google Drive, Dropbox), aponte os dados para fora dela
# definindo a variável de ambiente NMRM_DIR_DADOS.
#   Windows (PowerShell):  $env:NMRM_DIR_DADOS = "C:\dados_nmrm"
#   Linux/macOS:           export NMRM_DIR_DADOS=~/dados_nmrm
DIR_DADOS = Path(os.environ.get("NMRM_DIR_DADOS", DIR_RAIZ / "dados"))

DIR_FABDEM = DIR_DADOS / "fabdem"          # tiles .tif brutos (NÃO versionar)
DIR_AUXILIAR = DIR_DADOS / "auxiliar"      # MapBiomas, GEBCO, maregrafia
DIR_PROCESSADO = DIR_DADOS / "processado"  # MDE recortado e reprojetado
DIR_SAIDAS = DIR_RAIZ / "saidas"           # figuras, GeoTIFF, CSV

# Raster nacional do MapBiomas Col. 11 (~763 MB), entrada do 04_prepara_cobertura.py.
# Vive em DIR_AUXILIAR — ou seja, em NMRM_DIR_DADOS/auxiliar quando a variável
# de ambiente está definida.
ARQ_MAPBIOMAS_NACIONAL = "brazil_coverage-col11_2025.tif"

# Produto do 01_mapa_elevacao.py — entrada de todo o resto do projeto
MDE_PROCESSADO = DIR_PROCESSADO / "caravelas_fabdem_utm24s_30m.tif"

# Máscara binária de água (1=oceano/estuário/corpo d'água com dem==0.0 exato
# no FABDEM, 0=terra), mesma grade do MDE_PROCESSADO. Existe porque o próprio
# MDE_PROCESSADO converte esses pixels em nodata na gravação — indistinguível
# de "fora do bbox, sem tile" — e o teste de conectividade em slr_core precisa
# saber por onde a água pode propagar mesmo depois desse round-trip.
MASCARA_AGUA = DIR_PROCESSADO / "caravelas_mascara_agua_utm24s_30m.tif"


def criar_estrutura():
    """Cria as pastas do projeto se ainda não existirem."""
    for d in (DIR_FABDEM, DIR_AUXILIAR, DIR_PROCESSADO, DIR_SAIDAS):
        d.mkdir(parents=True, exist_ok=True)


# =============================================================================
# ÁREA DE ESTUDO
# =============================================================================

# Recorte da planície costeira de Caravelas (graus decimais, WGS84).
# Cobre o strandplain de Andrade et al. (2003), com margem a oeste até
# as falésias inativas do Grupo Barreiras.
BBOX_WGS84 = {
    "lon_min": -39.60,
    "lon_max": -38.98,
    "lat_min": -18.05,
    "lat_max": -17.42,
}

CRS_ALVO = "EPSG:31984"   # SIRGAS 2000 / UTM 24S
CRS_FONTE = "EPSG:4326"   # FABDEM é distribuído em WGS84 geográfico
RESOLUCAO_M = 30.0


# =============================================================================
# ÁREA DE TRABALHO DA TURMA
# =============================================================================

# A área que a turma definiu (UCs da região + plataforma até a isóbata de
# 500 m) tem 21.955 km² e é quase toda oceânica. Ela NÃO é o domínio do MDE:
# o FABDEM não distribui os tiles oceânicos (S18W038, S19W039, S19W038) e não
# teria o que dizer sobre o banco dos Abrolhos. Por isso a área da turma vive
# como camada vetorial, desenhada por cima do mapa, e BBOX_WGS84 segue sendo
# o domínio de análise de exposição.
#
# Fontes: CNUC 07/2026 (ICMBio/MMA) — unidades de conservação; Batimetria do
# Brasil CPRM/ANP 2013, derivada do GEBCO 925 m — isóbatas.
BBOX_TURMA = {"lon_min": -39.60, "lon_max": -37.24,
              "lat_min": -18.26, "lat_max": -17.23}
ARQ_UCS_TURMA      = "ucs_turma.geojson"
ARQ_ISOBATAS_TURMA = "isobatas_turma.geojson"
ARQ_AREA_TURMA     = "area_turma.geojson"

# area_turma.geojson não traz a área como propriedade (só o nome). Valor
# documentado acima, usado pela interface para não recalcular geodésia de um
# polígono pequeno só para um tooltip.
AREA_TURMA_KM2 = 21955.0


# =============================================================================
# MARÉ — TPXO9-atlas v5
# =============================================================================

# Produto de `07_mare_tpxo.py` (roda FORA deste repo, contra o atlas de
# ~10 GB — aqui só o JSON de saída é versionado, como proveniência
# auditável). Consumido por `src/slr_core.NIVEIS_MARE` (offsets já extraídos)
# e pela interface (constituintes completos, para a aba Metadados).
ARQ_MARE_TPXO = "mare_caravelas_tpxo9v5.json"


# =============================================================================
# FABDEM — onde baixar
# =============================================================================

FABDEM_DOI = "https://doi.org/10.5523/bris.s5hqmjcdj8yo2ibzi9b4ew3sn"
FABDEM_PAGINA = "https://data.bris.ac.uk/data/dataset/s5hqmjcdj8yo2ibzi9b4ew3sn"

# Blocos são de 10°x10°, nomeados pelo canto SO e pelo canto NE.
# Caravelas (~17,7°S / 39,2°W) cai no bloco abaixo.
FABDEM_BLOCO = "S20W040-S10W030_FABDEM_V1-2.zip"
FABDEM_URL_BLOCO = (
    f"https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn/{FABDEM_BLOCO}"
)

# Tiles de 1°x1° que intersectam o BBOX (nomeados pelo canto SO).
# S19W039 intersecta apenas um canto de ~2 x 6 km no extremo SE do recorte,
# cerca de 20 km mar adentro. O FABDEM não distribui tiles inteiramente
# oceânicos, então esse arquivo pode simplesmente não existir — a ausência
# dele é esperada e o 01 trata a área como NaN, não como terreno.
TILES_NECESSARIOS = ["S18W040", "S18W039", "S19W040"]
TILES_OPCIONAIS = ["S19W039"]


# =============================================================================
# CLASSIFICAÇÃO ALTIMÉTRICA
# =============================================================================

# Faixas escolhidas a partir de Andrade et al. (2003): terraços holocênicos
# vão de decímetros a ~6 m; pleistocênicos de 6 a 10 m.
FAIXAS_ALTIMETRICAS = [0, 0.5, 1.0, 2.0, 3.0, 5.0, 6.0, 10.0, 20.0, 50.0]

CORES_FAIXAS = [
    "#08306b", "#2171b5", "#4292c6", "#6baed6", "#9ecae1",
    "#c7e9c0", "#74c476", "#31a354", "#e6d3a3", "#b09060",
]
