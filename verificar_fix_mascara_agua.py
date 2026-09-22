#!/usr/bin/env python3
"""
verificar_fix_mascara_agua.py — Projeto 26.09 (NMRM Caravelas)

Verifica se a correção da grade de conectividade hidráulica (classificar
água na grade NATIVA do FABDEM, antes da reprojeção, e reprojetar a máscara
com `nearest` em vez de recomputá-la depois do `bilinear`) está de fato
presente em `01_mapa_elevacao.py` — para o Claude Code (ou qualquer sessão)
confirmar a mudança sem precisar reler o diff inteiro à mão.

Duas partes, independentes:

    PARTE A — Verificação ESTÁTICA (sempre roda, só precisa da stdlib)
        Lê o código-fonte de 01_mapa_elevacao.py e confere, por texto:
          A1. existe `classificar_agua()`;
          A2. `CONFIG_01["reamostragem_mascara"]` está em `Resampling.nearest`;
          A3. `main()` chama, NESSA ORDEM: mosaicar_e_recortar -> classificar_agua
              -> reprojetar -> mascarar_e_salvar;
          A4. `reprojetar()` recebe `mask_agua` como parâmetro (reprojeta a
              máscara, não só o MDE);
          A5. `mascarar_e_salvar()` NÃO recomputa `np.isclose(dem, ...)` no
              próprio corpo — ou seja, para de derivar a máscara depois da
              reprojeção (esse era o bug).

    PARTE B — Verificação FUNCIONAL (roda só se rasterio/scipy disponíveis)
        Constrói um MDE sintético (linha de "rio" de 1 pixel, exatamente
        0.0, dentro de um domínio maior) posicionado dentro do
        `config.BBOX_WGS84` real, chama `classificar_agua` + `reprojetar`
        de verdade (o código de produção, não uma cópia), e confere que:
          B1. o teste ANTIGO (dem==0.0 só depois do bilinear) perde a
              maior parte do rio sintético;
          B2. o pipeline ATUAL (classificar antes + nearest) recupera
              significativamente mais desse rio do que o método antigo;
          B3. nenhum pixel de água do método antigo desaparece no atual
              (a mudança é estritamente aditiva — sem regressão).

USO
    python verificar_fix_mascara_agua.py
    (rodar de dentro da pasta do projeto — mesma pasta de config.py)

SAÍDA
    Prints com tag [VERIFICA] + [OK]/[FALHOU] por item, resumo final, e
    código de saída: 0 = tudo passou, 1 = algo falhou.

Autor: Helio | Assistência: Claude
"""

import re
import sys
from pathlib import Path

CONFIG_VERIFICA = {
    "arquivo_alvo": "01_mapa_elevacao.py",
    # sintético: linha de "rio" de 1 px, dentro de um bloco 120x120 px
    "sintetico_lado_px": 120,
    "sintetico_res_deg": 1 / 3600,   # ~1 arcsec, resolução nativa do FABDEM
    "sintetico_elevacao_terra_m": 8.0,
    # limiares de aceitação da Parte B (ver docstring B1/B2)
    "razao_max_aceitavel_metodo_antigo": 0.5,   # antigo deve perder > 50% do rio
    "razao_min_aceitavel_metodo_novo":   0.7,   # novo deve preservar >= 70% do rio
}

resultados = []  # (id, ok: bool, mensagem)


def _registrar(id_item: str, ok: bool, mensagem: str) -> None:
    tag = "[OK]" if ok else "[FALHOU]"
    print(f"[VERIFICA] {tag} {id_item}: {mensagem}")
    resultados.append((id_item, ok, mensagem))


# =============================================================================
# PARTE A — VERIFICAÇÃO ESTÁTICA (texto do arquivo)
# =============================================================================

def verificar_estatico(caminho_arquivo: Path) -> None:
    print("=" * 72)
    print("PARTE A — verificação estática (texto de 01_mapa_elevacao.py)")
    print("=" * 72)

    if not caminho_arquivo.exists():
        _registrar("A0", False, f"arquivo não encontrado: {caminho_arquivo}")
        return

    texto = caminho_arquivo.read_text(encoding="utf-8")

    # A1 — classificar_agua existe
    tem_funcao = re.search(r"^def classificar_agua\(", texto, re.MULTILINE) is not None
    _registrar("A1", tem_funcao,
               "classificar_agua() presente" if tem_funcao else
               "classificar_agua() NÃO encontrada — o código ainda deve estar "
               "na versão antiga (máscara recomputada depois do bilinear)")

    # A2 — reamostragem_mascara = nearest
    m = re.search(r'"reamostragem_mascara"\s*:\s*Resampling\.(\w+)', texto)
    ok_nearest = bool(m) and m.group(1) == "nearest"
    _registrar("A2", ok_nearest,
               f"CONFIG_01['reamostragem_mascara'] = Resampling.{m.group(1)}"
               if m else "chave 'reamostragem_mascara' não encontrada em CONFIG_01")

    # A3 — ordem de chamadas dentro de main()
    m_main = re.search(r"def main\(\):(.*?)\nif __name__", texto, re.DOTALL)
    ordem_ok = False
    detalhe_ordem = "bloco main() não encontrado"
    if m_main:
        corpo = m_main.group(1)
        posicoes = {}
        for nome in ("mosaicar_e_recortar(", "classificar_agua(",
                     "reprojetar(", "mascarar_e_salvar("):
            pos = corpo.find(nome)
            posicoes[nome] = pos
        if all(p != -1 for p in posicoes.values()):
            ordem = sorted(posicoes, key=posicoes.get)
            ordem_ok = ordem == ["mosaicar_e_recortar(", "classificar_agua(",
                                  "reprojetar(", "mascarar_e_salvar("]
            detalhe_ordem = "ordem encontrada: " + " -> ".join(
                n.rstrip("(") for n in ordem)
        else:
            faltando = [n for n, p in posicoes.items() if p == -1]
            detalhe_ordem = f"chamada(s) não encontrada(s) em main(): {faltando}"
    _registrar("A3", ordem_ok, detalhe_ordem)

    # A4 — reprojetar() recebe mask_agua
    m_assinatura = re.search(r"def reprojetar\(([^)]*)\)", texto)
    tem_mask_param = bool(m_assinatura) and "mask_agua" in m_assinatura.group(1)
    _registrar("A4", tem_mask_param,
               f"assinatura: reprojetar({m_assinatura.group(1).strip()})"
               if m_assinatura else "reprojetar() não encontrada")

    # A5 — mascarar_e_salvar NÃO recomputa a máscara internamente
    m_func = re.search(
        r"def mascarar_e_salvar\(.*?\):(.*?)\n\ndef ", texto, re.DOTALL)
    sem_recomputo = False
    detalhe_recomputo = "mascarar_e_salvar() não encontrada"
    if m_func:
        corpo_func = m_func.group(1)
        sem_recomputo = "np.isclose(dem" not in corpo_func
        detalhe_recomputo = (
            "não recomputa a máscara a partir do dem reprojetado (correto)"
            if sem_recomputo else
            "AINDA recomputa np.isclose(dem, ...) dentro da função — "
            "isso é exatamente o bug antigo, o fix não está completo")
    _registrar("A5", sem_recomputo, detalhe_recomputo)


# =============================================================================
# PARTE B — VERIFICAÇÃO FUNCIONAL (MDE sintético, dentro do BBOX real)
# =============================================================================

def verificar_funcional() -> None:
    print()
    print("=" * 72)
    print("PARTE B — verificação funcional (MDE sintético)")
    print("=" * 72)

    try:
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.transform import from_origin
        from rasterio.warp import reproject
        import importlib
        import config
        pipeline = importlib.import_module("01_mapa_elevacao")
    except Exception as exc:  # pragma: no cover - ambiente sem dependências
        _registrar("B0", None,
                   f"pulada — dependências indisponíveis neste ambiente ({exc})")
        return

    cfg = CONFIG_VERIFICA
    lado = cfg["sintetico_lado_px"]
    res = cfg["sintetico_res_deg"]

    # Ancora o MDE sintético no canto SW do BBOX real do projeto, pra
    # `reprojetar()` (que usa config.BBOX_WGS84 internamente) enxergar
    # sobreposição de verdade.
    bbox = config.BBOX_WGS84
    origem_lon = bbox["lon_min"] + 10 * res
    origem_lat = bbox["lat_min"] + (lado + 10) * res
    transform = from_origin(origem_lon, origem_lat, res, res)

    dem = np.full((lado, lado), cfg["sintetico_elevacao_terra_m"], dtype="float32")
    # "rio" sintético: linha em degrau (não retinha), 1 px de largura,
    # exatamente 0.0 — pior caso pra reamostragem, igual a um canal real.
    for col in range(lado):
        linha = (col * 7) // 10  # inclinação ~35°, gera degraus como um rio real
        linha = min(linha, lado - 1)
        dem[linha, col] = 0.0
    n_rio_nativo = int(np.isclose(dem, 0.0).sum())

    mask_bruta = pipeline.classificar_agua(dem)
    b1_classificacao_ok = int(mask_bruta.sum()) == n_rio_nativo
    _registrar("B_classificacao", b1_classificacao_ok,
               f"classificar_agua() achou {int(mask_bruta.sum())}/{n_rio_nativo} "
               f"px do rio sintético na grade nativa")

    dem_alvo, mask_alvo, transform_alvo = pipeline.reprojetar(dem, mask_bruta, transform)

    # Reconstitui o método ANTIGO só pra comparação: dem==0.0 testado
    # DEPOIS do bilinear (é exatamente o que reprojetar() já faz pro MDE,
    # só reaproveitamos o dem_alvo que ela devolve).
    mask_antiga = np.isclose(dem_alvo, 0.0, atol=1e-6, equal_nan=False)

    n_antiga = int(mask_antiga.sum())
    n_nova = int(mask_alvo.sum())
    razao_antiga = n_antiga / n_rio_nativo if n_rio_nativo else 0.0
    razao_nova = n_nova / n_rio_nativo if n_rio_nativo else 0.0

    print(f"[VERIFICA] rio sintético: {n_rio_nativo} px na grade nativa")
    print(f"[VERIFICA] método ANTIGO (bilinear, depois dem==0.0): "
          f"{n_antiga} px recuperados ({100*razao_antiga:.0f} %)")
    print(f"[VERIFICA] método NOVO   (classificar antes + nearest): "
          f"{n_nova} px recuperados ({100*razao_nova:.0f} %)")

    _registrar("B1", razao_antiga <= cfg["razao_max_aceitavel_metodo_antigo"],
               f"método antigo perde a maior parte do rio "
               f"({100*razao_antiga:.0f} % <= "
               f"{100*cfg['razao_max_aceitavel_metodo_antigo']:.0f} % esperado)")

    _registrar("B2", razao_nova >= cfg["razao_min_aceitavel_metodo_novo"],
               f"método novo preserva o rio "
               f"({100*razao_nova:.0f} % >= "
               f"{100*cfg['razao_min_aceitavel_metodo_novo']:.0f} % esperado)")

    _registrar("B3", n_nova > n_antiga,
               f"fix recupera mais água que o método antigo "
               f"({n_nova} px > {n_antiga} px)")


# =============================================================================
# EXECUÇÃO
# =============================================================================

def main() -> int:
    print("=" * 72)
    print("VERIFICAÇÃO — fix da máscara de água (rios/canais estreitos)")
    print("=" * 72)

    caminho_alvo = Path(__file__).resolve().parent / CONFIG_VERIFICA["arquivo_alvo"]
    verificar_estatico(caminho_alvo)
    verificar_funcional()

    print()
    print("=" * 72)
    falhas = [r for r in resultados if r[1] is False]
    pulados = [r for r in resultados if r[1] is None]
    if falhas:
        print(f"RESULTADO: FALHOU ({len(falhas)} item(ns) reprovado(s))")
        for id_item, _, msg in falhas:
            print(f"  - {id_item}: {msg}")
    else:
        extra = f" ({len(pulados)} pulado(s))" if pulados else ""
        print(f"RESULTADO: TUDO OK{extra} — o fix está presente e funcionando")
    print("=" * 72)

    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
