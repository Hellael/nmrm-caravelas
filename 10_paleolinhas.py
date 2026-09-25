#!/usr/bin/env python3
"""
10_paleolinhas.py — Projeto 26.09 (simulador NMRM Caravelas)

Converte as PALEOLINHAS DE COSTA, digitalizadas à mão no QGIS sobre as figuras
georreferenciadas de Andrade et al. (2003), em polígonos de TERRA EMERSA por
estágio evolutivo -> `dados_web/paleolinhas_turma.geojson`.

POR QUE A ENTRADA É LINHA E A SAÍDA É POLÍGONO
    Digitalizar o polígono fechado obrigaria a contornar o quadro da figura
    inteiro (borda oeste, sul e leste) a cada estágio. Isso é centenas de
    vértices que não são dado — são moldura — e, pior, uma moldura redesenhada
    de forma ligeiramente diferente a cada figura. A diferença de área ENTRE
    estágios é exatamente o que a aba de comparação vai medir, então erro de
    moldura viraria sinal falso de progradação.

    Traçando só a linha de costa, o quadro é idêntico em todos os estágios por
    construção, e a única coisa que varia é o que foi lido no artigo.

COMO O POLÍGONO É FECHADO
    Topologia padrão: une a(s) linha(s) do estágio com o retângulo do quadro,
    deixa `polygonize` cortar em peças, e classifica cada peça:

      TERRA  - peça que encosta na borda OESTE do quadro (os Tabuleiros do
               Grupo Barreiras estão emersos em todos os sete estágios), ou
               peça que contém algum ponto-semente declarado em ESTAGIOS.
      MAR    - todo o resto.

    Os pontos-semente existem para o Estágio II, em que a ilha-barreira é uma
    massa de terra SEPARADA do continente e portanto não encosta em borda
    nenhuma. Sem semente ela seria classificada como mar.

O QUE ESTE SCRIPT NÃO FAZ
    Não deriva, não simplifica e não suaviza o traçado. A geometria é a que
    foi digitalizada no QGIS; aqui ela só é fechada, conferida e convertida.
    Para mudar uma paleolinha: reeditar no QGIS e rodar isto de novo — nunca
    editar o GeoJSON na mão.

PRECISÃO — LEIA ANTES DE CITAR QUALQUER NÚMERO
    A origem é uma figura de 2003 escaneada e georreferenciada por 4 pontos de
    controle nos cantos do quadro. O erro posicional resultante é da ordem de
    CENTENAS DE METROS. Os km² impressos aqui servem para comparar estágios
    entre si (onde o erro é em boa parte sistemático e se cancela), não para
    serem publicados como medida absoluta. Por isso a interface arredonda para
    km² inteiro — decimal ali seria decoração.

    Isto é uma RECONSTRUÇÃO redesenhada de Andrade et al. (2003), não uma
    simulação, não um cálculo nosso, e não um dado medido.

PROVENIÊNCIA
    O shapefile de origem é VERSIONADO em `dados_web/fonte_paleolinhas/`,
    junto com os arquivos `.points` do georreferenciador do QGIS em
    `dados_web/fonte_paleolinhas/georref/`. Os `.points` são minúsculos e são
    o trabalho manual insubstituível: com eles + a figura original do artigo,
    qualquer pessoa refaz o warp. O GeoTIFF georreferenciado em si NÃO é
    versionado (é pesado e é regenerável) — mora em NMRM_DIR_DADOS/auxiliar/paleo/.

    Dependências (`shapely` + `pyshp`) estão em `requirements-geracao.txt` e
    NÃO em `requirements.txt`: o app publicado lê o GeoJSON com `json` da
    stdlib e nunca roda este script.

    Rodar:  pip install -r requirements-geracao.txt
            python 10_paleolinhas.py

Autor: Helio (georreferenciamento e traçado no QGIS) | Assistência: Claude (conversão)
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np

import config

# =============================================================================
# CONFIG — todo limiar numérico mora aqui (nunca hardcodado dentro de função)
# =============================================================================

CONFIG_PALEO = {
    "dir_saida":      config.DIR_RAIZ / "dados_web",
    "subdir_fonte":   "fonte_paleolinhas",
    "arq_fonte":      "paleolinhas",          # sem extensão (pyshp)
    "arq_produto":    "paleolinhas_turma.geojson",
    "campo_estagio":  "estagio",              # campo de texto no shapefile

    # QUADRO DAS FIGURAS 9 a 15 do artigo. As sete compartilham exatamente o
    # mesmo enquadramento: 39°30'W–39°00'W x 17°30'S–18°00'S. É ele, e não
    # config.BBOX_WGS84, que delimita o que a paleolinha pode afirmar: fora do
    # quadro o artigo não desenhou nada, então não há o que reconstruir.
    # (config.BBOX_WGS84 é MAIOR: vai a -39,60/-38,98 em lon e -18,05/-17,42
    # em lat. A camada paleo vale só dentro do quadro abaixo.)
    "bbox_figura": {
        "lon_min": -39.50, "lon_max": -39.00,
        "lat_min": -18.00, "lat_max": -17.50,
    },

    # Quanto estender as PONTAS da linha digitalizada, em graus (~11 km), para
    # garantir que ela atravesse o quadro de lado a lado. Sem isso, parar 200 m
    # antes da borda deixa o quadro sem corte e o polygonize devolve uma peça
    # só. A extensão é recortada pelo quadro logo em seguida, então não
    # inventa geometria dentro da área de análise.
    "extensao_pontas_graus": 0.10,

    # ÂNCORA DO CONTINENTE — ponto que, em todos os sete estágios, está em
    # terra firme: o canto NOROESTE do quadro, sobre os Tabuleiros do Grupo
    # Barreiras. A peça que contém este ponto é o continente.
    #
    # Por que âncora e não "a peça que encosta na borda oeste": quando a
    # paleolinha sai pela própria borda oeste (e não pela borda sul), ela parte
    # essa borda em dois trechos e AS DUAS peças passam a encostar nela — a
    # regra devolvia o quadro inteiro como terra, sem mar nenhum. Um ponto não
    # tem essa ambiguidade. Pode ser sobrescrito por estágio em ESTAGIOS[..]["ancora"].
    "ancora_continente": (-39.499, -17.501),

    # A terra não pode ser o quadro inteiro nem coisa nenhuma: os dois casos
    # significam que a classificação falhou, não que o mar sumiu.
    "frac_terra_max": 0.98,

    # As peças do corte têm que somar a área do quadro. Acima deste desvio não
    # é arredondamento — é geometria quebrada, e aí o script PARA.
    "tol_fechamento_km2": 0.5,

    # Se a linha digitalizada ficar mais longe que isto da borda do quadro em
    # alguma ponta, é sinal de traçado incompleto — o script AVISA (não para,
    # porque a extensão pode salvar; mas vale conferir no QGIS).
    "tol_alerta_ponta_graus": 0.02,

    "raio_terra_m":   6_371_008.8,            # raio médio (IUGG), igual ao 09
    "casas_coord":    6,                      # ~0,1 m; evita ruído de float
    "rotulo_crs":     "urn:ogc:def:crs:EPSG::4674",
    "arq_debug":      config.DIR_SAIDAS / "paleo_pecas_debug.geojson",
    "gerado_por":     "10_paleolinhas.py",
}

# =============================================================================
# ESTÁGIOS — metadados de Andrade et al. (2003), §VII e Figs. 9 a 15
# =============================================================================
# Ficam AQUI, e não como campos do shapefile, para o QGIS exigir só `estagio`.
# Menos digitação manual = menos erro de digitação em dado que já é frágil.
#
# `nmrm_m` é o nível relativo do mar do momento retratado, quando o artigo dá
# um número. Onde ele descreve uma FASE (regressão, progradação) sem cota
# associada, fica None — inventar número aqui seria exatamente o que a regra 1
# do CLAUDE.md proíbe.

ESTAGIOS = {
    "I": {
        "figura": "Fig. 9",
        "idade_rotulo": "> 120.000 anos AP",
        "idade_ordem": 120_000,              # anos AP, só para ordenar o slider
        "nmrm_m": None,
        "nmrm_obs": ("regressão posterior ao máximo da Penúltima Transgressão "
                     "(+8 ± 2 m em ~123.000 AP; Martin et al. 1980). O artigo "
                     "não atribui cota à linha desenhada."),
        "titulo": "Construção da planície pleistocênica",
        "descricao": ("Limite externo dos Terraços Marinhos Pleistocênicos. A "
                      "planície holocênica, a Ilha de Caçumba e todo o sistema "
                      "de manguezal AINDA NÃO EXISTEM — ali era mar."),
        "sementes_extra": [],
    },
    "II": {
        "figura": "Fig. 10",
        "idade_rotulo": "5.600 anos cal AP",
        "idade_ordem": 5_600,
        "nmrm_m": 4.8,
        "nmrm_obs": ("máximo da Última Transgressão, +4,8 ± 0,5 m na curva de "
                     "Salvador (Martin et al. 1980, 2002)."),
        "titulo": "Afogamento da planície pleistocênica",
        "descricao": ("Sistema ilha-barreira / laguna, com os sistemas lagunares "
                      "I (sul) e II (norte). A ilha-barreira é massa de terra "
                      "SEPARADA do continente: precisa de ponto-semente."),
        # Preencher ao digitalizar a Fig. 10: um ponto sobre a ilha-barreira.
        "sementes_extra": [],
    },
    "III": {
        "figura": "Fig. 11",
        "idade_rotulo": "pós-5.600 anos cal AP",
        "idade_ordem": 5_000,
        "nmrm_m": None,
        "nmrm_obs": "fase regressiva após o máximo; sem cota atribuída no artigo.",
        "titulo": "Progradação na enseada Baleia–Catoeiro",
        "descricao": ("Preenchimento do setor côncavo entre a paleo-Ponta da "
                      "Baleia e a paleo-Ponta do Catoeiro."),
        "sementes_extra": [],
    },
    "IV": {
        "figura": "Fig. 12",
        "idade_rotulo": "~4.000 anos cal AP",
        "idade_ordem": 4_000,
        "nmrm_m": None,
        "nmrm_obs": ("fase regressiva; a emersão do arco recifal interno a "
                     "partir de ~4.000 cal AP inverte a deriva litorânea no "
                     "setor norte."),
        "titulo": "Início da sedimentação no setor norte",
        "descricao": "Inversão da deriva litorânea dominante no setor norte.",
        "sementes_extra": [],
    },
    "V": {
        "figura": "Fig. 13",
        "idade_rotulo": "2.100 anos cal AP",
        "idade_ordem": 2_100,
        "nmrm_m": 2.5,
        "nmrm_obs": ("terceiro máximo da curva de Salvador, +2,5 ± 0,5 m. As "
                     "oscilações de alta frequência são CONTESTADAS — ver "
                     "Angulo & Lessa (1997) e a réplica de Martin et al. "
                     "(1998, 2002). Declarar na interface."),
        "titulo": "Episódio erosivo da Ponta da Baleia",
        "descricao": ("Erosão do cabo da paleo-Ponta da Baleia, associada à "
                      "subida rápida do nível relativo do mar. Truncamento "
                      "datado em 2.344 cal AP (CA96/30)."),
        "sementes_extra": [],
    },
    "VI": {
        "figura": "Fig. 14",
        "idade_rotulo": "~1.300 anos cal AP",
        "idade_ordem": 1_300,
        "nmrm_m": None,
        "nmrm_obs": "sem cota atribuída; idade máxima dada por CA96-11/70 cm.",
        "titulo": "Erosão severa da Ilha de Caçumba",
        "descricao": ("Deslocamento do canal de Caravelas e erosão da Ilha de "
                      "Caçumba."),
        "sementes_extra": [],
    },
    "VII": {
        "figura": "Fig. 15",
        "idade_rotulo": "atual",
        "idade_ordem": 0,
        "nmrm_m": 0.0,
        "nmrm_obs": "configuração atual, nível de referência.",
        "titulo": "Progradação recente",
        "descricao": ("Crescimento da Ponta da Baleia e instalação das planícies "
                      "de maré extensas — sedimentação dominada por maré."),
        "sementes_extra": [],
    },
}

FONTE_ARTIGO = ("Andrade ACS, Dominguez JML, Martin L, Bittencourt ACSP (2003). "
                "Quaternary evolution of the Caravelas strandplain – Southern "
                "Bahia State – Brazil. An Acad Bras Cienc 75(3): 357-382.")


# =============================================================================
# GEODÉSIA (numpy, sem pyproj)
# =============================================================================
# Espelha as funções de 09_limite_turma.py. Duplicadas de propósito: os dois
# scripts de geração são independentes e o 09 está estável — refatorar para um
# src/geodesia.py comum é limpeza futura, não tarefa desta entrega.

def _area_anel_km2(coords) -> float:
    """
    Área de um anel em lon/lat (graus) sobre a esfera de raio R, pelo excesso
    esférico (Chamberlain & Duquette, 2007):
        A = R²/2 · |Σ (λ2-λ1)(2 + sen φ1 + sen φ2)|
    A esfera erra ~0,3 % contra o elipsoide — serve para AFERIR, não publicar.
    (E aqui isso é o menor dos erros: o georreferenciamento erra bem mais.)
    """
    c = np.asarray(coords, dtype=float)
    lon, lat = np.radians(c[:, 0]), np.radians(c[:, 1])
    lon2, lat2 = np.roll(lon, -1), np.roll(lat, -1)
    dlon = (lon2 - lon + np.pi) % (2 * np.pi) - np.pi
    soma = np.sum(dlon * (2.0 + np.sin(lat) + np.sin(lat2)))
    R = CONFIG_PALEO["raio_terra_m"]
    return abs(soma) * R * R / 2.0 / 1e6


def area_km2(geom) -> float:
    """Área geodésica de Polygon / MultiPolygon (exterior menos furos)."""
    if geom.is_empty:
        return 0.0
    if geom.geom_type == "Polygon":
        a = _area_anel_km2(geom.exterior.coords)
        for furo in geom.interiors:
            a -= _area_anel_km2(furo.coords)
        return a
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return sum(area_km2(g) for g in geom.geoms
                   if g.geom_type in ("Polygon", "MultiPolygon", "GeometryCollection"))
    return 0.0


def partes(geom) -> list:
    """Lista de Polygons de uma geometria."""
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [p for g in geom.geoms for p in partes(g)]


# =============================================================================
# LEITURA E CONFERÊNCIA
# =============================================================================

def conferir_prj(caminho: Path) -> None:
    """
    O .prj precisa ser geográfico (graus). Um shapefile projetado passaria sem
    erro de sintaxe e sairia com METROS dentro de um GeoJSON rotulado em graus
    — engano que só aparece quando o mapa fica vazio. Mesma conferência do 09.
    """
    if not caminho.exists():
        print(f"[PRJ] AVISO: {caminho.name} não existe. Seguindo sob a suposição de "
              "coordenadas geográficas — confira a camada no QGIS.")
        return
    wkt = caminho.read_text(encoding="utf-8", errors="replace")
    print(f"[PRJ] {wkt.strip()[:110]}...")
    if "PROJCS" in wkt.upper():
        print("[PRJ] PARADO: a camada está PROJETADA (PROJCS). Este pipeline espera "
              "coordenadas geográficas em graus. No QGIS, salve a camada como "
              "EPSG:4326 e rode de novo. Nada foi gravado.")
        sys.exit(1)


def ler_linhas(base: Path) -> dict:
    """
    Lê o shapefile de linhas e agrupa por estágio.
    Devolve {estagio: [LineString, ...]} — lista porque um estágio pode ter
    mais de uma linha (costa oceânica + margem lagunar, no Estágio II).
    """
    import shapefile
    from shapely.geometry import shape

    leitor = shapefile.Reader(str(base))
    campos = [f[0] for f in leitor.fields[1:]]
    print(f"[LEITURA] {base.name}.shp | shapeType={leitor.shapeType} | "
          f"feições={len(leitor)} | campos={campos}")
    print(f"[LEITURA] bbox do arquivo: "
          f"lon [{leitor.bbox[0]:.4f}, {leitor.bbox[2]:.4f}] "
          f"lat [{leitor.bbox[1]:.4f}, {leitor.bbox[3]:.4f}]")

    campo = CONFIG_PALEO["campo_estagio"]
    if campo not in campos:
        print(f"[LEITURA] PARADO: o shapefile não tem o campo '{campo}'. Crie-o no "
              f"QGIS (texto, comprimento 5) e preencha com o número romano do "
              f"estágio (I, II, ... VII). Campos encontrados: {campos}. "
              "Nada foi gravado.")
        sys.exit(1)

    por_estagio: dict = {}
    for i, (forma, registro) in enumerate(zip(leitor.shapes(), leitor.records())):
        geom = shape(forma.__geo_interface__)
        if geom.geom_type not in ("LineString", "MultiLineString"):
            print(f"[LEITURA] PARADO: feição {i} é {geom.geom_type}, não linha. Esta "
                  "camada é de LINHAS — o polígono é fechado aqui pelo script. "
                  "Nada foi gravado.")
            sys.exit(1)

        est = str(registro[campo]).strip().upper()
        if est not in ESTAGIOS:
            print(f"[LEITURA] PARADO: feição {i} tem estagio='{est}', que não está em "
                  f"ESTAGIOS ({list(ESTAGIOS)}). Corrija o atributo no QGIS. "
                  "Nada foi gravado.")
            sys.exit(1)

        pecas = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
        por_estagio.setdefault(est, []).extend(pecas)
        print(f"[LEITURA] feição {i} -> estágio {est} | {geom.geom_type} | "
              f"{sum(len(p.coords) for p in pecas)} vértices")

    return por_estagio


# =============================================================================
# FECHAMENTO DO POLÍGONO
# =============================================================================

def estender_pontas(linha, extra: float):
    """
    Prolonga o primeiro e o último segmento da linha, na mesma direção, por
    `extra` graus. Serve para garantir que a linha atravesse o quadro de lado a
    lado mesmo que o traçado tenha parado um pouco antes da borda. O excedente
    é cortado pelo quadro em seguida, então isto não inventa geometria dentro
    da área de análise — só fecha a topologia.
    """
    from shapely.geometry import LineString

    coords = list(linha.coords)
    if len(coords) < 2:
        return linha
    # Anel fechado (ilha) não tem ponta para prolongar — e prolongar criaria
    # duas farpas saindo do anel. Devolve intacto.
    if coords[0] == coords[-1]:
        return linha

    def _prolonga(p_dentro, p_ponta):
        dx, dy = p_ponta[0] - p_dentro[0], p_ponta[1] - p_dentro[1]
        n = math.hypot(dx, dy)
        if n == 0:
            return p_ponta
        return (p_ponta[0] + dx / n * extra, p_ponta[1] + dy / n * extra)

    novo = ([_prolonga(coords[1], coords[0])]
            + coords
            + [_prolonga(coords[-2], coords[-1])])
    return LineString(novo)


def alertar_pontas(linhas, quadro_bounds) -> None:
    """
    Avisa se alguma ponta da linha digitalizada ficou longe da borda do quadro.
    Não para o script (a extensão costuma resolver), mas traçado incompleto é a
    causa número um de polígono estranho — melhor o aviso aparecer no log do
    que a área sair errada em silêncio.
    """
    lon_min, lat_min, lon_max, lat_max = quadro_bounds
    tol = CONFIG_PALEO["tol_alerta_ponta_graus"]
    for k, linha in enumerate(linhas):
        # Anel fechado é ilha: não deve mesmo encostar em borda nenhuma.
        if linha.coords[0] == linha.coords[-1]:
            print(f"[PONTA] linha {k} é anel fechado (ilha) — sem ponta a conferir.")
            continue
        for rotulo, (x, y) in (("inicial", linha.coords[0]),
                               ("final", linha.coords[-1])):
            d = min(abs(x - lon_min), abs(x - lon_max),
                    abs(y - lat_min), abs(y - lat_max))
            if d > tol:
                print(f"[PONTA] AVISO: linha {k}, ponta {rotulo} em "
                      f"({x:.4f}, {y:.4f}) está a {d:.4f}° (~{d * 111:.1f} km) da "
                      "borda mais próxima do quadro. Confira se o traçado ficou "
                      "incompleto no QGIS.")


def terra_do_estagio(linhas, est: str):
    """
    Fecha as linhas do estágio contra o quadro e devolve (terra, pecas_debug).

    `pecas_debug` é a lista [(Polygon, classe)] de TODAS as peças do corte, com
    a classificação de cada uma — gravada em saidas/ para inspeção no QGIS
    quando o resultado não bater com o esperado.
    """
    from shapely.geometry import box, LineString, Point
    from shapely.ops import polygonize, unary_union

    cfg = CONFIG_PALEO
    b = cfg["bbox_figura"]
    quadro = box(b["lon_min"], b["lat_min"], b["lon_max"], b["lat_max"])

    alertar_pontas(linhas, (b["lon_min"], b["lat_min"], b["lon_max"], b["lat_max"]))

    estendidas = [estender_pontas(l, cfg["extensao_pontas_graus"]) for l in linhas]

    # A rede a cortar: contorno do quadro + linhas. unary_union NODA os
    # cruzamentos, que é o que polygonize exige para fechar anéis.
    rede = unary_union([quadro.exterior] + estendidas)
    brutas = [p for p in polygonize(rede) if p.intersects(quadro)]
    # Recorta ao quadro: a extensão das pontas cria apêndices do lado de fora.
    # `partes` achata o resultado — uma interseção pode devolver MultiPolygon.
    pecas = []
    for p in brutas:
        pecas.extend(partes(p.intersection(quadro)))
    pecas = [p for p in pecas if not p.is_empty and p.area > 0]

    if len(pecas) < 2:
        print(f"[FECHAR {est}] PARADO: o corte devolveu {len(pecas)} peça(s). A linha "
              "não atravessou o quadro de lado a lado — no QGIS, prolongue o "
              "traçado até (ou além de) as bordas norte e sul. Nada foi gravado.")
        sys.exit(1)

    # Conferência de fechamento: as peças do corte têm que reconstituir o quadro
    # inteiro, sem sobra nem falta. É barata e pega de uma vez erro de nodação,
    # peça perdida no recorte e bug na conta de área esférica — qualquer um dos
    # três faria a área do estágio sair errada em silêncio.
    soma = sum(area_km2(p) for p in pecas)
    quadro_km2 = area_km2(quadro)
    desvio = abs(soma - quadro_km2)
    print(f"[FECHAR {est}] {len(pecas)} peça(s) | soma {soma:,.1f} km² vs quadro "
          f"{quadro_km2:,.1f} km² (Δ {desvio:,.3f} km²)")
    if desvio > cfg["tol_fechamento_km2"]:
        print(f"[FECHAR {est}] PARADO: as peças não reconstituem o quadro (Δ "
              f"{desvio:,.2f} km², acima de {cfg['tol_fechamento_km2']:.1f} km²). "
              "Isso indica geometria quebrada — provavelmente linha auto-"
              "interceptante. Conserte no QGIS. Nada foi gravado.")
        sys.exit(1)

    # ---- Classificação -------------------------------------------------------
    # O continente é a peça que CONTÉM a âncora. Ilhas destacadas entram por
    # ponto-semente. Ver a nota em CONFIG_PALEO["ancora_continente"] para o
    # motivo de não ser "a peça que encosta na borda oeste".
    ancora = Point(*(ESTAGIOS[est].get("ancora") or cfg["ancora_continente"]))
    sementes = [Point(x, y) for x, y in ESTAGIOS[est]["sementes_extra"]]
    print(f"[FECHAR {est}] âncora do continente em "
          f"({ancora.x:.4f}, {ancora.y:.4f})"
          + (f" | {len(sementes)} ponto(s)-semente" if sementes else ""))

    terras, debug = [], []
    for k, p in enumerate(sorted(pecas, key=lambda g: -g.area)):
        por_ancora = ancora.within(p)
        por_semente = any(s.within(p) for s in sementes)
        eh_terra = por_ancora or por_semente

        motivo = ("âncora" if por_ancora else
                  "ponto-semente" if por_semente else "—")
        print(f"[PECA {est}.{k}] {area_km2(p):9,.1f} km² | "
              f"{'TERRA' if eh_terra else 'mar  '} ({motivo})")

        debug.append((p, "terra" if eh_terra else "mar"))
        if eh_terra:
            terras.append(p)

    if not terras:
        print(f"[FECHAR {est}] PARADO: a âncora ({ancora.x:.4f}, {ancora.y:.4f}) não "
              "caiu dentro de nenhuma peça — provavelmente está exatamente sobre a "
              "paleolinha ou fora do quadro. Ajuste "
              f"ESTAGIOS['{est}']['ancora'] ou CONFIG_PALEO['ancora_continente']. "
              "Nada foi gravado.")
        sys.exit(1)

    terra = unary_union(terras).buffer(0)

    # Guarda-costas: terra = quadro inteiro significa que não sobrou mar, o que
    # nunca é verdade num mapa de linha de costa. Peguei este caso na marra —
    # a regra antiga da borda oeste devolvia exatamente isso quando a linha
    # saía pela própria borda oeste.
    frac = area_km2(terra) / quadro_km2
    if frac > cfg["frac_terra_max"]:
        print(f"[FECHAR {est}] PARADO: a terra ficou com {100 * frac:.1f}% do quadro — "
              "não sobrou mar. A classificação falhou; confira a âncora e abra "
              f"{cfg['arq_debug'].name} no QGIS. Nada foi gravado.")
        sys.exit(1)

    return terra, debug


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    from shapely.geometry import mapping
    import shapely

    cfg = CONFIG_PALEO
    print(f"[PALEO] shapely {shapely.__version__}")
    b = cfg["bbox_figura"]
    print(f"[QUADRO] Figs. 9–15 de Andrade et al. (2003): "
          f"lon [{b['lon_min']}, {b['lon_max']}] lat [{b['lat_min']}, {b['lat_max']}]")
    print("[QUADRO] lembrete: este quadro é MENOR que config.BBOX_WGS84. A camada "
          "paleo só vale dentro dele — fora, o artigo não desenhou nada.")

    dir_fonte = cfg["dir_saida"] / cfg["subdir_fonte"]
    base = dir_fonte / cfg["arq_fonte"]
    if not base.with_suffix(".shp").exists():
        print(f"[PALEO] PARADO: {base}.shp não encontrado. Digitalize as paleolinhas "
              "no QGIS (camada de LINHA, EPSG:4326, campo de texto 'estagio') e "
              "salve nesse caminho. Nada foi gravado.")
        return 1

    conferir_prj(base.with_suffix(".prj"))
    por_estagio = ler_linhas(base)

    faltando = [e for e in ESTAGIOS if e not in por_estagio]
    if faltando:
        print(f"[PALEO] estágios ainda não digitalizados: {faltando} — o produto sai "
              "só com os que existem, e o app mostra só esses.")

    feicoes, debug_total = [], []
    nd = cfg["casas_coord"]

    def _arredonda(o):
        if isinstance(o, (list, tuple)):
            return [_arredonda(x) for x in o]
        return round(float(o), nd)

    # Ordem cronológica (mais antigo primeiro) — é a ordem do slider da interface.
    for est in sorted(por_estagio, key=lambda e: -ESTAGIOS[e]["idade_ordem"]):
        meta = ESTAGIOS[est]
        print(f"\n[ESTAGIO {est}] {meta['titulo']} — {meta['idade_rotulo']} "
              f"({meta['figura']})")

        terra, debug = terra_do_estagio(por_estagio[est], est)
        debug_total.extend((p, est, classe) for p, classe in debug)

        pecas = partes(terra)
        km2 = area_km2(terra)
        n_vert = sum(len(p.exterior.coords) for p in pecas)
        print(f"[ESTAGIO {est}] TERRA EMERSA: {km2:,.1f} km² | {len(pecas)} parte(s) | "
              f"{n_vert} vértices | válido={terra.is_valid}")

        geom = mapping(terra)
        feicoes.append({
            "type": "Feature",
            "properties": {
                "estagio":       est,
                "titulo":        meta["titulo"],
                "idade_rotulo":  meta["idade_rotulo"],
                "idade_ordem":   meta["idade_ordem"],
                "nmrm_m":        meta["nmrm_m"],
                "nmrm_obs":      meta["nmrm_obs"],
                "descricao":     meta["descricao"],
                "figura":        meta["figura"],
                "area_km2_aprox_esferica": round(km2, 1),
                "n_partes":      len(pecas),
                "n_vertices":    n_vert,
                "metodo": ("linha de costa digitalizada no QGIS sobre a figura "
                           "georreferenciada; polígono fechado contra o quadro da "
                           "figura por 10_paleolinhas.py"),
                "precisao": ("RECONSTRUÇÃO redesenhada, não medição. Erro posicional "
                             "da ordem de centenas de metros (figura de 2003 "
                             "escaneada, georreferenciada por 4 pontos de controle). "
                             "Use para comparar estágios entre si, não como medida "
                             "absoluta."),
                "fonte":         FONTE_ARTIGO,
                "crs_origem":    ("EPSG:4326 (WGS 84); coordenadas não transformadas "
                                  "— mesma convenção de limite_turma e ucs_turma"),
                "gerado_em":     date.today().isoformat(),
                "gerado_por":    cfg["gerado_por"],
            },
            "geometry": {"type": geom["type"],
                         "coordinates": _arredonda(geom["coordinates"])},
        })

    # ---- Gravação do produto -------------------------------------------------
    produto = {
        "type": "FeatureCollection",
        "name": "paleolinhas_turma",
        "crs": {"type": "name", "properties": {"name": cfg["rotulo_crs"]}},
        "properties": {
            "fonte": FONTE_ARTIGO,
            "quadro_figura": b,
            "aviso": ("Reconstrução paleoambiental redesenhada de Andrade et al. "
                      "(2003). Não é simulação, não é cálculo próprio e não é dado "
                      "medido."),
        },
        "features": feicoes,
    }
    destino = cfg["dir_saida"] / cfg["arq_produto"]
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(produto, f, ensure_ascii=False)
    print(f"\n[EXPORT] {destino} ({destino.stat().st_size / 1024:.1f} KB) | "
          f"{len(feicoes)} estágio(s)")

    # ---- Gravação do debug ---------------------------------------------------
    # Todas as peças do corte, com a classe de cada uma. Abra no QGIS quando o
    # polígono não sair como o esperado: quase sempre a resposta está aqui.
    cfg["arq_debug"].parent.mkdir(parents=True, exist_ok=True)
    dbg = {
        "type": "FeatureCollection",
        "name": "paleo_pecas_debug",
        "crs": {"type": "name", "properties": {"name": cfg["rotulo_crs"]}},
        "features": [{
            "type": "Feature",
            "properties": {"estagio": est, "classe": classe,
                           "area_km2": round(area_km2(p), 2)},
            "geometry": {"type": mapping(p)["type"],
                         "coordinates": _arredonda(mapping(p)["coordinates"])},
        } for p, est, classe in debug_total],
    }
    with open(cfg["arq_debug"], "w", encoding="utf-8") as f:
        json.dump(dbg, f, ensure_ascii=False)
    print(f"[DEBUG]  {cfg['arq_debug']} ({len(debug_total)} peça(s)) — abra no QGIS "
          "se a classificação terra/mar não bater com o esperado.")

    # ---- Resumo comparativo --------------------------------------------------
    if len(feicoes) > 1:
        print("\n[RESUMO] terra emersa por estágio (dentro do quadro da figura):")
        for f_ in feicoes:
            p = f_["properties"]
            print(f"  {p['estagio']:>4}  {p['idade_rotulo']:>22}  "
                  f"{p['area_km2_aprox_esferica']:9,.1f} km²")
        print("[RESUMO] km² arredondados para comparação entre estágios. Não cite "
              "como medida absoluta — ver 'precisao' nas propriedades.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
