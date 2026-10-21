"""
11_baixa_correntes.py — Baixa as correntes do CMEMS (GLORYS12, médias mensais)
Projeto: Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB — Caravelas (BA)

O QUE FAZ
    Baixa as componentes uo (leste) e vo (norte) da reanálise GLORYS12 mensal
    para o domínio `config.BBOX_CORRENTES`, nos 10 anos civis completos
    definidos em `config.CONFIG_CORRENTES` (padrão 2016-2025) e nas
    profundidades-alvo (padrão 0,5 / 50 / 200 / 1000 m).
    Um arquivo NetCDF por profundidade, em NMRM_DIR_DADOS/correntes/.
    Peso total esperado: poucos MB.

    Depois rode o `12_prepara_correntes.py`, que calcula a climatologia e as
    médias por trimestre e grava o produto leve que o simulador lê.

PRÉ-REQUISITOS (uma vez)
    1. Conta gratuita em https://data.marine.copernicus.eu (Register).
    2. pip install -r requirements-geracao.txt
    3. O script pede usuário e senha na primeira execução e guarda as
       credenciais na pasta do usuário (~/.copernicusmarine). Também aceita
       as variáveis COPERNICUSMARINE_SERVICE_USERNAME / _PASSWORD.

COMO RODAR
    python 11_baixa_correntes.py                # baixa tudo que falta
    python 11_baixa_correntes.py --simular      # só confere o pedido (dry run)
    python 11_baixa_correntes.py --refazer      # rebaixa por cima

Reexecutar é seguro: arquivo que já existe é pulado.

Autor: Helio | Assistência: Claude
"""

import argparse
import sys

import config

CFG = config.CONFIG_CORRENTES


def nome_arquivo(prof_alvo: float) -> str:
    """Nome estável por profundidade-alvo — é o que o 12 procura."""
    return (f"correntes_glorys12_mensal_{CFG['ano_inicio']}_{CFG['ano_fim']}"
            f"_z{int(round(prof_alvo * 10)):05d}.nc")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--simular", action="store_true",
                    help="Não baixa: só mostra o que seria pedido (dry run).")
    ap.add_argument("--refazer", action="store_true",
                    help="Baixa de novo mesmo que o arquivo exista.")
    args = ap.parse_args()

    try:
        import copernicusmarine
    except ImportError:
        print("[ERRO] Falta o pacote copernicusmarine. Rode:\n"
              "       pip install -r requirements-geracao.txt")
        return 1

    box = config.BBOX_CORRENTES
    destino = config.DIR_CORRENTES_BRUTO
    destino.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("[CORRENTES] Download CMEMS GLORYS12 mensal")
    print(f"[CORRENTES] dataset   = {CFG['dataset_id']}")
    print(f"[CORRENTES] periodo   = {CFG['ano_inicio']}-01 a {CFG['ano_fim']}-12 "
          f"({(CFG['ano_fim'] - CFG['ano_inicio'] + 1) * 12} meses)")
    print(f"[CORRENTES] dominio   = lon {box['lon_min']}..{box['lon_max']} | "
          f"lat {box['lat_min']}..{box['lat_max']}")
    print(f"[CORRENTES] niveis    = {CFG['profundidades_m']} m (alvo; o CMEMS usa o mais proximo)")
    print(f"[CORRENTES] destino   = {destino}")
    print("=" * 70)

    if not args.simular:
        # Credenciais: reaproveita as já salvas; senão pergunta uma vez.
        try:
            if not copernicusmarine.login(check_credentials_valid=True):
                print("[CORRENTES] Credenciais nao encontradas — informe usuario e senha do CMEMS.")
                if not copernicusmarine.login():
                    print("[ERRO] Login no CMEMS falhou.")
                    return 1
        except TypeError:
            # Versões antigas do pacote não têm check_credentials_valid.
            copernicusmarine.login()

    feitos, pulados, falhas = [], [], []
    for prof in CFG["profundidades_m"]:
        arq = destino / nome_arquivo(prof)
        if arq.exists() and not args.refazer and not args.simular:
            print(f"[PULADO] z={prof:g} m ja existe: {arq.name}")
            pulados.append(arq.name)
            continue
        print(f"[BAIXANDO] z={prof:g} m -> {arq.name}")
        try:
            copernicusmarine.subset(
                dataset_id=CFG["dataset_id"],
                variables=CFG["variaveis"],
                minimum_longitude=box["lon_min"], maximum_longitude=box["lon_max"],
                minimum_latitude=box["lat_min"], maximum_latitude=box["lat_max"],
                # min = max = alvo, com seleção 'nearest': devolve UM nível,
                # o mais próximo do alvo (a profundidade real vai no arquivo).
                minimum_depth=prof, maximum_depth=prof,
                start_datetime=f"{CFG['ano_inicio']}-01-01T00:00:00",
                # Carimbo mensal = dia 1. Pedir até 31/12 fazia a seleção
                # 'nearest' devolver também 01/01 do ano seguinte.
                end_datetime=f"{CFG['ano_fim']}-12-01T00:00:00",
                coordinates_selection_method="nearest",
                output_filename=arq.name,
                output_directory=str(destino),
                overwrite=bool(args.refazer),
                dry_run=bool(args.simular),
            )
            feitos.append(arq.name)
        except Exception as exc:  # noqa: BLE001 — queremos seguir para as outras profundidades
            print(f"[FALHA] z={prof:g} m: {exc}")
            falhas.append((prof, str(exc)))

    print("=" * 70)
    print(f"[RESUMO] baixados/pedidos={len(feitos)} | pulados={len(pulados)} | falhas={len(falhas)}")
    for prof, msg in falhas:
        print(f"[RESUMO]   falhou z={prof:g} m -> {msg[:150]}")
    if falhas:
        print("[RESUMO] Rode de novo para tentar as que faltam. Se o erro for de "
              "dataset_id, confira o nome em https://data.marine.copernicus.eu "
              "(produto GLOBAL_MULTIYEAR_PHY_001_030) e ajuste "
              "config.CONFIG_CORRENTES['dataset_id'].")
        return 2
    if not args.simular:
        print("[RESUMO] Proximo passo: python 12_prepara_correntes.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
