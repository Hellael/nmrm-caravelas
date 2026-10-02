#!/usr/bin/env python3
"""
10_paleolinhas.py — Projeto 26.09 (simulador NMRM Caravelas)

Converte as PALEOLINHAS DE COSTA, digitalizadas à mão no QGIS pela turma sobre
as figuras georreferenciadas de Andrade et al. (2003), em polígonos de TERRA
EMERSA por estágio evolutivo -> `dados_web/paleolinhas_turma.geojson`.

ENTRADA (v2.1, 01/10/2026)
    UM SHAPEFILE DE LINHAS POR ESTÁGIO, em `dados_web/fonte_paleolinhas/estagios/`:
    `estagio_I.shp`, `estagio_II.shp`, ... `estagio_VII.shp`. O estágio sai do
    NOME do arquivo — a tabela de atributos não precisa de campo nenhum (a turma
    entregou só o `Id` padrão, e está ótimo assim).

    Isto substitui o `paleolinhas.shp` único da versão preliminar de 24/09/2026
    (só o Estágio I, campo `estagio`, nunca publicada), descartado em
    01/10/2026: os arquivos da turma cobrem os sete estágios, inclusive o I, e
    foram digitalizados com o mesmo critério.

COMO A TURMA DIGITALIZOU (e por que o fechamento mudou)
    Cada linha é uma FRONTEIRA TERRA/ÁGUA: costa oceânica, margem de laguna,
    contorno de ilha, margem de canal. Algumas linhas também correm ao longo da
    MOLDURA da figura (o contorno do continente foi fechado pela borda), e
    vários contornos foram feitos em mais de um trecho que se encostam pelas
    pontas.

    A regra da versão preliminar ("a peça que contém a âncora é terra, o resto
    é mar, ilha entra por ponto-semente") não dá conta disso: num estágio com
    laguna, ilhas dentro da laguna e ilha-barreira, ela exigiria uma semente
    por ilha. A regra nova não precisa de semente de terra nenhuma:

        Toda linha separa terra de água. Atravessar uma linha troca a classe.

    O mar aberto a leste é sempre mar (semente única, `ponto_mar`). A partir
    dele, cada peça do recorte recebe a classe oposta à das vizinhas do outro
    lado de uma linha — é uma 2-coloração do mapa. Ilha dentro de laguna dentro
    de continente sai certa sozinha, em qualquer profundidade de aninhamento.

PASSO A PASSO
    1. MOLDURA: o trecho de cada linha a menos de `margem_borda_graus` da borda
       do quadro é descartado — é moldura redesenhada à mão, não costa. A
       moldura entra pelo retângulo EXATO do quadro, idêntico nos sete
       estágios (mesmo motivo da versão preliminar: erro de moldura não pode
       virar diferença de área entre estágios).
    2. PONTAS: ponta que ficou junto à borda é prolongada até cruzá-la; ponta
       solta no meio do mapa a menos de `tol_costura_graus` de outra linha é
       COSTURADA nela (fecha as frestas entre trechos digitalizados
       separadamente); anel quase fechado é fechado.
    3. CORTE: `polygonize` sobre linhas + quadro. O que sobrar sem fechar
       peça nenhuma é avisado — fresta não costurada junta duas peças que
       deviam estar separadas.
    4. CLASSE: 2-coloração a partir do mar. Lascas menores que
       `area_min_lasca_km2` (entre dois traçados quase coincidentes) herdam a
       classe da vizinha com a maior fronteira comum.
    5. CONFERÊNCIAS que PARAM o script (nada é gravado): peças que não
       reconstituem o quadro; `ponto_continente` (Barreiras) saindo mar; terra
       acima de `frac_terra_max`; conflito de classe entre peças grandes.

O QUE ESTE SCRIPT NÃO FAZ
    Não deriva, não simplifica e não suaviza o traçado. A geometria é a que
    foi digitalizada no QGIS; aqui ela só é fechada, conferida e convertida.
    Para mudar uma paleolinha: reeditar no QGIS e rodar isto de novo — nunca
    editar o GeoJSON na mão.

PRECISÃO — LEIA ANTES DE CITAR QUALQUER NÚMERO
    A origem é uma figura de 2003 escaneada e georreferenciada por pontos de
    controle nos cantos do quadro. O erro posicional resultante é da ordem de
    CENTENAS DE METROS. Os km² impressos aqui servem para comparar estágios
    entre si (onde o erro é em boa parte sistemático e se cancela), não para
    serem publicados como medida absoluta.

    Isto é uma RECONSTRUÇÃO redesenhada de Andrade et al. (2003), não uma
    simulação, não um cálculo nosso, e não um dado medido.

PROVENIÊNCIA
    Versionado em `dados_web/fonte_paleolinhas/`: os shapefiles da turma
    (`estagios/`) e, em `georref/`, as figuras originais com os `.points` do
    georreferenciador do QGIS — com os dois, qualquer pessoa refaz o warp.

    Dependências (`shapely` + `pyshp`) estão em `requirements-geracao.txt` e
    NÃO em `requirements.txt`: o app publicado lê o GeoJSON com `json` da
    stdlib e nunca roda este script.

    Rodar:  pip install -r requirements-geracao.txt
            python 10_paleolinhas.py

Autor: Helio e turma de Ecossistemas Marinhos Costeiros (georreferenciamento e
traçado no QGIS) | Assistência: Claude (conversão)
"""
import json
import math
import sys
from collections import deque
from datetime import date

import numpy as np

import config

# =============================================================================
# CONFIG — todo limiar numérico mora aqui (nunca hardcodado dentro de função)
# =============================================================================

CONFIG_PALEO = {
    "dir_saida":      config.DIR_RAIZ / "dados_web",
    "subdir_fonte":   "fonte_paleolinhas/estagios",
    "padrao_fonte":   "estagio_{est}",        # sem extensão (pyshp)
    "arq_produto":    "paleolinhas_turma.geojson",

    # QUADRO DAS FIGURAS 9 a 15 do artigo. As sete compartilham exatamente o
    # mesmo enquadramento: 39°30'W–39°00'W x 17°30'S–18°00'S. É ele, e não
    # config.BBOX_WGS84, que delimita o que a paleolinha pode afirmar.
    "bbox_figura": {
        "lon_min": -39.50, "lon_max": -39.00,
        "lat_min": -18.00, "lat_max": -17.50,
    },

    # Faixa junto à borda do quadro, em graus (~220 m), em que o traçado é
    # tratado como MOLDURA redesenhada e descartado. Maior que o tremor da mão
    # ao seguir a borda (a turma ficou a 10–150 m dela) e bem menor que
    # qualquer feição costeira que encoste no quadro.
    "margem_borda_graus": 0.002,

    # Quanto prolongar uma ponta que terminou junto à borda, para garantir que
    # ela CRUZE o quadro (o excedente é recortado em seguida).
    "extensao_borda_graus": 0.02,

    # Fresta máxima entre trechos que deviam se encostar, em graus (~440 m). A
    # maior encontrada nos sete estágios é de ~260 m (Estágio II). Acima disso
    # a ponta é tratada como solta e AVISADA — não é costurada no chute.
    "tol_costura_graus": 0.004,

    # Ultrapassagem da costura além do ponto de contato, em graus (~20 m):
    # garante que o nó exista depois do `unary_union` (encostar exatamente na
    # linha deixa o cruzamento à mercê do arredondamento de ponto flutuante).
    "ultrapassa_costura_graus": 0.0002,

    # SEMENTE DO MAR: mar aberto, a leste da Ponta da Baleia, em todos os
    # sete estágios. É a ÚNICA semente da 2-coloração.
    "ponto_mar": (-39.01, -17.75),

    # CONFERÊNCIA DO CONTINENTE: sobre os Tabuleiros do Grupo Barreiras, emersos
    # nos sete estágios. Não é semente — se a coloração devolver mar aqui, a
    # leitura das linhas está errada e o script PARA.
    "ponto_continente": (-39.45, -17.60),

    # Peça menor que isto (5 ha) é LASCA entre dois traçados quase coincidentes
    # e herda a classe da vizinha com a maior fronteira comum. Fica abaixo da
    # menor ilha digitalizada e bem abaixo do erro posicional da figura.
    "area_min_lasca_km2": 0.05,

    # Fresta não costurada deixa linha sem fechar peça nenhuma. Acima deste
    # comprimento total por estágio, o script AVISA (não para).
    "alerta_solta_km": 0.5,

    "frac_terra_max": 0.98,
    "tol_fechamento_km2": 0.5,

    "raio_terra_m":   6_371_008.8,            # raio médio (IUGG), igual ao 09
    "km_por_grau":    111.32,                 # só para imprimir distâncias
    "casas_coord":    6,                      # ~0,1 m; evita ruído de float
    "rotulo_crs":     "urn:ogc:def:crs:EPSG::4674",
    "arq_debug":      config.DIR_SAIDAS / "paleo_pecas_debug.geojson",
    "gerado_por":     "10_paleolinhas.py",
}

# =============================================================================
# ESTÁGIOS — metadados de Andrade et al. (2003), §VII e Figs. 9 a 15
# =============================================================================
# Ficam AQUI, e não na tabela de atributos, para o QGIS não exigir nada além
# da linha. `nmrm_m` é o nível relativo do mar do momento retratado, quando o
# artigo dá um número; onde ele descreve uma FASE sem cota, fica None —
# inventar número aqui seria exatamente o que a regra 1 do CLAUDE.md proíbe.

ESTAGIOS = {
    # Revisado em 01/10/2026 contra o texto de Andrade et al. (2003), §VII e
    # legendas das Figs. 9 a 15. Os sete são estágios QUATERNÁRIOS do modelo
    # evolutivo — inclusive o VII, que é a última fase do modelo e NÃO a costa
    # atual (a costa atual é a linha tracejada "present day coastline" das
    # figuras, e no simulador vem do FABDEM).
    "I": {
        "figura": "Fig. 9",
        "periodo": "Pleistoceno",
        "idade_rotulo": "após 120.000 anos AP",
        "idade_ordem": 120_000,              # anos AP, só para ordenar o slider
        "nmrm_m": None,
        "nmrm_obs": ("fase regressiva posterior ao máximo da Penúltima "
                     "Transgressão (+8 ± 2 m em ~123.000 AP; Martin et al. 1980), "
                     "que se estende até ~18.000 AP. O artigo não atribui cota à "
                     "linha desenhada."),
        "titulo": "Construção da planície pleistocênica",
        "descricao": ("Com a descida do nível do mar, sedimentos retrabalhados da "
                      "plataforma interna e trazidos pela deriva litorânea fazem a "
                      "costa progradar por acréscimo de cordões litorâneos, "
                      "formando os Terraços Marinhos Pleistocênicos. Costa arenosa, "
                      "contínua, com orientação muito parecida com a atual "
                      "(controlada pelos recifes do Parcel das Paredes)."),
    },
    "II": {
        "figura": "Fig. 10",
        "periodo": "Holoceno",
        "idade_rotulo": "5.600 anos cal AP",
        "idade_ordem": 5_600,
        "nmrm_m": 4.8,
        "nmrm_obs": ("máximo da Última Transgressão, +4,8 ± 0,5 m na curva de "
                     "Salvador (Martin et al. 1980, 2002)."),
        "titulo": "Afogamento da planície pleistocênica na Última Transgressão",
        "descricao": ("A subida do mar afoga e retrabalha parte dos terraços "
                      "pleistocênicos e forma um sistema ilha-barreira/laguna, com o "
                      "Sistema Lagunar I (sul) e o II (norte). Já existia uma "
                      "paleo-Ponta do Catoeiro na cadeia de ilhas-barreira; a deriva "
                      "litorânea era dominantemente para norte."),
    },
    "III": {
        "figura": "Fig. 11",
        "periodo": "Holoceno",
        "idade_rotulo": "após 5.600 anos cal AP",
        "idade_ordem": 5_000,
        "nmrm_m": None,
        "nmrm_obs": ("descida do nível do mar após o máximo de 5.600 cal AP, "
                     "chegando um pouco abaixo do atual antes de ~3.800 cal AP. "
                     "Sem cota atribuída à linha."),
        "titulo": "Progradação na enseada entre as paleo-Pontas da Baleia e do Catoeiro",
        "descricao": ("A queda do nível do mar favorece a progradação, primeiro na "
                      "enseada entre a paleo-Ponta da Baleia e a paleo-Ponta do "
                      "Catoeiro: preenchimento transversal do setor côncavo e, "
                      "depois, crescimento de um pontal arenoso para nordeste. Os "
                      "sistemas lagunares I e II perdem contato com o mar e viram "
                      "brejos de água doce."),
    },
    "IV": {
        "figura": "Fig. 12",
        "periodo": "Holoceno",
        "idade_rotulo": "~4.000 anos cal AP",
        "idade_ordem": 4_000,
        "nmrm_m": None,
        "nmrm_obs": ("o artigo não data o estágio; a idade é a da emersão do arco "
                     "recifal interno (~4.000 cal AP), com datações de "
                     "4.530–3.930 cal AP na figura. O 2º máximo da curva de "
                     "Salvador (+3,5 ± 0,5 m, ~3.500 cal AP) cai entre os "
                     "Estágios IV e V."),
        "titulo": "Início da sedimentação no setor norte da planície",
        "descricao": ("A emersão do arco interno de recifes bloqueia as ondas de "
                      "sudeste e inverte a deriva litorânea no setor norte "
                      "(de nordeste para sul). Duas pontas marcam a costa: "
                      "paleo-Ponta da Baleia e paleo-Ponta do Catoeiro, onde pontais "
                      "arenosos isolam lagunas alongadas."),
    },
    "V": {
        "figura": "Fig. 13",
        "periodo": "Holoceno",
        "idade_rotulo": "2.100 anos cal AP",
        "idade_ordem": 2_100,
        "nmrm_m": 2.5,
        "nmrm_obs": ("terceiro máximo da curva de Salvador, +2,5 ± 0,5 m. As "
                     "oscilações de alta frequência são CONTESTADAS — ver "
                     "Angulo & Lessa (1997) e a réplica de Martin et al. "
                     "(1998, 2002)."),
        "titulo": "Episódio erosivo da subida rápida do nível do mar de 2.100 cal AP",
        "descricao": ("O episódio erosivo mais marcante da planície: erosão do "
                      "cabo da paleo-Ponta da Baleia, associada à subida rápida do "
                      "nível relativo do mar. Truncamento datado em 2.344 cal AP "
                      "(CA96/30) e 2.317 cal AP (testemunho 13)."),
    },
    "VI": {
        "figura": "Fig. 14",
        "periodo": "Holoceno",
        "idade_rotulo": "≤ 1.300 anos cal AP",
        "idade_ordem": 1_300,
        "nmrm_m": None,
        "nmrm_obs": ("nível relativo descendo do 3º máximo rumo à posição atual; "
                     "sem cota atribuída. 1.290 cal AP (CA96-11/70 cm) é idade "
                     "MÁXIMA da paleogeografia."),
        "titulo": "Erosão costeira severa na Ilha de Caçumba",
        "descricao": ("A intensificação da deriva litorânea para sul desloca o "
                      "canal de Caravelas, o que explicaria a erosão severa da Ilha "
                      "de Caçumba. O paleocanal é sugerido pelas fácies de canal de "
                      "maré do testemunho 10."),
    },
    "VII": {
        "figura": "Fig. 15",
        "periodo": "Holoceno",
        "idade_rotulo": "< 1.300 anos cal AP",
        "idade_ordem": 1_000,
        "nmrm_m": None,
        "nmrm_obs": ("nível relativo descendo do 3º máximo rumo à posição atual; "
                     "sem cota atribuída. Planícies de maré datadas em ~700–500 cal "
                     "AP e chênieres em ~800–300 cal AP; borda do recife de Coroa "
                     "Vermelha em 1.540 cal AP."),
        "titulo": "Retomada da progradação da linha de costa",
        "descricao": ("Último estágio do modelo. O crescimento da Ponta da Baleia "
                      "e a emersão dos recifes de Sebastião Gomes, Coroa Vermelha e "
                      "Viçosa criam uma zona de baixa energia junto à Ilha de "
                      "Caçumba, com planícies de maré extensas: a sedimentação "
                      "passa a ser dominada pela maré."),
    },
}

FONTE_ARTIGO = ("Andrade ACS, Dominguez JML, Martin L, Bittencourt ACSP (2003). "
                "Quaternary evolution of the Caravelas strandplain – Southern "
                "Bahia State – Brazil. An Acad Bras Cienc 75(3): 357-382.")


# =============================================================================
# GEODÉSIA (numpy, sem pyproj)
# =============================================================================
# Espelha as funções de 09_limite_turma.py. Duplicadas de propósito: os dois
# scripts de geração são independentes e o 09 está estável.

def _area_anel_km2(coords) -> float:
    """
    Área de um anel em lon/lat (graus) sobre a esfera de raio R, pelo excesso
    esférico (Chamberlain & Duquette, 2007):
        A = R²/2 · |Σ (λ2-λ1)(2 + sen φ1 + sen φ2)|
    A esfera erra ~0,3 % contra o elipsoide — serve para AFERIR, não publicar.
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
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in partes(g)]
    return []


def _linhas(geom) -> list:
    """Lista de LineStrings de uma geometria qualquer (descarta pontos)."""
    if geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if hasattr(geom, "geoms"):
        return [l for g in geom.geoms for l in _linhas(g)]
    return []


def _m(graus: float) -> float:
    """Graus -> metros, só para mensagem de log."""
    return graus * CONFIG_PALEO["km_por_grau"] * 1000.0


# =============================================================================
# LEITURA E CONFERÊNCIA
# =============================================================================

def conferir_prj(caminho) -> None:
    """
    O .prj precisa ser geográfico (graus). Um shapefile projetado passaria sem
    erro de sintaxe e sairia com METROS dentro de um GeoJSON rotulado em graus.
    """
    if not caminho.exists():
        print(f"[PRJ] AVISO: {caminho.name} não existe. Seguindo sob a suposição de "
              "coordenadas geográficas — confira a camada no QGIS.")
        return
    wkt = caminho.read_text(encoding="utf-8", errors="replace")
    if "PROJCS" in wkt.upper():
        print(f"[PRJ] PARADO: {caminho.name} está PROJETADO (PROJCS). Este pipeline "
              "espera coordenadas geográficas em graus. No QGIS, salve a camada "
              "como EPSG:4326 e rode de novo. Nada foi gravado.")
        sys.exit(1)


def ler_linhas(base) -> list:
    """
    Lê o shapefile de linhas de UM estágio. Devolve a lista de LineStrings
    (MultiLineString é explodida). Para se a camada não for de linhas.
    """
    import shapefile
    from shapely.geometry import shape

    leitor = shapefile.Reader(str(base))
    print(f"[LEITURA] {base.name}.shp | shapeType={leitor.shapeType} | "
          f"feições={len(leitor)} | lon [{leitor.bbox[0]:.4f}, {leitor.bbox[2]:.4f}] "
          f"lat [{leitor.bbox[1]:.4f}, {leitor.bbox[3]:.4f}]")
    if len(leitor) == 0:
        print(f"[LEITURA] PARADO: {base.name}.shp não tem feição nenhuma. (Armadilha "
              "conhecida: exportar do QGIS com 'Salvar apenas feições "
              "selecionadas' marcado e nada selecionado.) Nada foi gravado.")
        sys.exit(1)

    linhas = []
    for i, forma in enumerate(leitor.shapes()):
        geom = shape(forma.__geo_interface__)
        if geom.geom_type not in ("LineString", "MultiLineString"):
            print(f"[LEITURA] PARADO: feição {i} de {base.name} é {geom.geom_type}, "
                  "não linha. Esta camada é de LINHAS — o polígono é fechado aqui "
                  "pelo script. Nada foi gravado.")
            sys.exit(1)
        linhas.extend(_linhas(geom))
    return linhas


# =============================================================================
# PREPARO DAS LINHAS: moldura, pontas, costura
# =============================================================================

def _prolonga(p_dentro, p_ponta, extra: float):
    """Ponto `extra` graus além de `p_ponta`, na direção p_dentro -> p_ponta."""
    dx, dy = p_ponta[0] - p_dentro[0], p_ponta[1] - p_dentro[1]
    n = math.hypot(dx, dy)
    if n == 0:
        return tuple(p_ponta)
    return (p_ponta[0] + dx / n * extra, p_ponta[1] + dy / n * extra)


def preparar_linhas(linhas, quadro, est: str) -> list:
    """
    Passos 1 e 2 do cabeçalho: tira a moldura redesenhada, fecha os anéis quase
    fechados, prolonga as pontas que encostam na borda e costura as frestas.
    Devolve a lista de LineStrings prontas para o corte.
    """
    from shapely.geometry import LineString, Point
    from shapely.ops import nearest_points, unary_union

    cfg = CONFIG_PALEO
    margem = cfg["margem_borda_graus"]
    tol = cfg["tol_costura_graus"]
    miolo = quadro.buffer(-margem, join_style=2)       # quadro encolhido, canto reto

    # 1. Moldura fora: só sobrevive o que está a mais de `margem` da borda.
    trechos = []
    for l in linhas:
        trechos.extend(t for t in _linhas(l.intersection(miolo))
                       if t.length > cfg["ultrapassa_costura_graus"])
    print(f"[MOLDURA {est}] {len(linhas)} linha(s) -> {len(trechos)} trecho(s) "
          f"fora da faixa de {_m(margem):.0f} m da borda")

    # Anel quase fechado (contorno de ilha) é fechado aqui — antes da costura,
    # senão a ponta procuraria outra linha em vez de si mesma.
    abertos = set()
    for k, t in enumerate(trechos):
        c = list(t.coords)
        gap = Point(c[0]).distance(Point(c[-1]))
        if c[0] != c[-1] and gap < tol and t.length > 3 * tol:
            trechos[k] = LineString(c + [c[0]])
            if gap > cfg["ultrapassa_costura_graus"]:
                print(f"[ANEL {est}] trecho {k} fechado (fresta de {_m(gap):.0f} m)")
        elif c[0] != c[-1]:
            abertos.add(k)

    # 2. Pontas — uma decisão por ponta: (a) junto à borda -> prolonga até
    # cruzar; (b) solta -> costura na linha mais próxima (outra, ou a própria
    # longe da ponta); (c) longe de tudo -> avisa e deixa como está.
    prontos = []
    for k, t in enumerate(trechos):
        c = list(t.coords)
        if k not in abertos:
            prontos.append(t)
            continue
        for lado in (0, -1):
            p = Point(c[lado])
            vizinho = c[1] if lado == 0 else c[-2]
            novo = None
            if quadro.exterior.distance(p) < 1.5 * margem:
                novo = _prolonga(vizinho, c[lado], cfg["extensao_borda_graus"])
            else:
                resto = c[3:] if lado == 0 else c[:-3]
                outros = [o for j, o in enumerate(trechos) if j != k]
                if len(resto) > 1:
                    outros.append(LineString(resto))
                alvo = unary_union(outros) if outros else None
                d = p.distance(alvo) if alvo is not None else float("inf")
                if d < tol:
                    q = nearest_points(p, alvo)[1]
                    novo = _prolonga(c[lado], (q.x, q.y),
                                     cfg["ultrapassa_costura_graus"])
                    if d > cfg["ultrapassa_costura_graus"]:
                        print(f"[COSTURA {est}] trecho {k}, ponta "
                              f"{'inicial' if lado == 0 else 'final'}: fresta de "
                              f"{_m(d):.0f} m costurada em ({q.x:.4f}, {q.y:.4f})")
                else:
                    print(f"[COSTURA {est}] AVISO: trecho {k}, ponta em "
                          f"({p.x:.4f}, {p.y:.4f}) está a {_m(d):.0f} m da linha mais "
                          "próxima — acima da tolerância, NÃO costurada. Confira "
                          "no QGIS se o contorno ficou aberto.")
            if novo is not None:
                c = [novo] + c if lado == 0 else c + [novo]
        prontos.append(LineString(c))
    return prontos


# =============================================================================
# CORTE E CLASSIFICAÇÃO
# =============================================================================

def _vizinhanca(pecas) -> dict:
    """{i: {j: comprimento da fronteira comum}} entre as peças do corte."""
    from shapely.strtree import STRtree

    arvore = STRtree(pecas)
    viz = {i: {} for i in range(len(pecas))}
    for i, a in enumerate(pecas):
        for j in arvore.query(a):
            j = int(j)
            if j <= i:
                continue
            comum = a.boundary.intersection(pecas[j].boundary).length
            if comum > 0:
                viz[i][j] = comum
                viz[j][i] = comum
    return viz


def _colorir(n: int, viz: dict, semente: int, permitidas: set) -> list:
    """BFS de 2-coloração: 0 = mar, 1 = terra. Só anda por `permitidas`."""
    cor = [None] * n
    cor[semente] = 0
    fila = deque([semente])
    while fila:
        i = fila.popleft()
        for j in viz[i]:
            if j in permitidas and cor[j] is None:
                cor[j] = 1 - cor[i]
                fila.append(j)
    return cor


def terra_do_estagio(linhas, est: str):
    """
    Fecha as linhas do estágio e devolve (terra, pecas_debug).

    `pecas_debug` é a lista [(Polygon, classe)] de TODAS as peças do corte,
    gravada em saidas/ para inspeção no QGIS quando o resultado não bater.
    """
    from shapely.geometry import Point, box
    from shapely.ops import polygonize_full, unary_union

    cfg = CONFIG_PALEO
    b = cfg["bbox_figura"]
    quadro = box(b["lon_min"], b["lat_min"], b["lon_max"], b["lat_max"])

    prontas = preparar_linhas(linhas, quadro, est)

    # 3. Corte. unary_union NODA os cruzamentos, que é o que polygonize exige.
    rede = unary_union([quadro.exterior] + prontas)
    faces, cortes, soltas, _ = polygonize_full(rede)
    dentro = quadro.buffer(-cfg["margem_borda_graus"])
    solta_km = sum(_m(g.intersection(dentro).length)
                   for g in _linhas(cortes) + _linhas(soltas)) / 1000
    if solta_km > cfg["alerta_solta_km"]:
        print(f"[CORTE {est}] AVISO: {solta_km:.1f} km de linha não fecham peça "
              "nenhuma (contorno aberto). A peça dos dois lados dessa linha é a "
              f"MESMA — abra {cfg['arq_debug'].name} no QGIS.")

    pecas = []
    for f in getattr(faces, "geoms", []):
        pecas.extend(p for p in partes(f.intersection(quadro)) if p.area > 0)

    if len(pecas) < 2:
        print(f"[CORTE {est}] PARADO: o corte devolveu {len(pecas)} peça(s) — as "
              "linhas não separam terra de mar. Nada foi gravado.")
        sys.exit(1)

    soma = sum(area_km2(p) for p in pecas)
    quadro_km2 = area_km2(quadro)
    desvio = abs(soma - quadro_km2)
    print(f"[CORTE {est}] {len(pecas)} peça(s) | soma {soma:,.1f} km² vs quadro "
          f"{quadro_km2:,.1f} km² (Δ {desvio:,.3f} km²)")
    if desvio > cfg["tol_fechamento_km2"]:
        print(f"[CORTE {est}] PARADO: as peças não reconstituem o quadro (Δ "
              f"{desvio:,.2f} km²). Geometria quebrada — provavelmente linha "
              "auto-interceptante. Conserte no QGIS. Nada foi gravado.")
        sys.exit(1)

    # 4. Classe. Primeiro só entre peças GRANDES: lasca em junção de três
    # linhas cria ciclo ímpar e contaminaria a paridade. O que não for
    # alcançado assim entra numa segunda passada pela malha toda.
    areas = [area_km2(p) for p in pecas]
    viz = _vizinhanca(pecas)
    grandes = {i for i, a in enumerate(areas) if a >= cfg["area_min_lasca_km2"]}

    mar_pt = Point(*cfg["ponto_mar"])
    semente = next((i for i, p in enumerate(pecas) if p.contains(mar_pt)), None)
    if semente is None:
        print(f"[CLASSE {est}] PARADO: o ponto_mar {cfg['ponto_mar']} não caiu em "
              "peça nenhuma (está sobre uma linha?). Ajuste CONFIG_PALEO. "
              "Nada foi gravado.")
        sys.exit(1)
    grandes.add(semente)

    cor = _colorir(len(pecas), viz, semente, grandes)
    if any(cor[i] is None for i in grandes):
        completa = _colorir(len(pecas), viz, semente, set(range(len(pecas))))
        for i in grandes:
            if cor[i] is None:
                cor[i] = completa[i]

    # Lascas: herdam da vizinha grande de maior fronteira comum (ou, sem
    # vizinha grande, da maior já classificada).
    n_lascas = 0
    for i in sorted(range(len(pecas)), key=lambda k: -areas[k]):
        if i in grandes:
            continue
        opcoes = ([(comp, j) for j, comp in viz[i].items() if j in grandes]
                  or [(comp, j) for j, comp in viz[i].items() if cor[j] is not None])
        cor[i] = cor[max(opcoes)[1]] if opcoes else 0
        n_lascas += 1

    conflitos = [(i, j, comp) for i in grandes for j, comp in viz[i].items()
                 if j in grandes and j > i and cor[i] == cor[j]]
    print(f"[CLASSE {est}] semente do mar na peça {semente} | {len(grandes)} peça(s) "
          f"grandes, {n_lascas} lasca(s) < {cfg['area_min_lasca_km2']} km² absorvidas "
          f"| conflitos: {len(conflitos)}")
    if conflitos:
        for i, j, comp in conflitos[:5]:
            pt = pecas[i].boundary.intersection(pecas[j].boundary).centroid
            print(f"[CLASSE {est}]   peças {i} e {j} com a mesma classe dos dois lados "
                  f"de {_m(comp):.0f} m de linha, perto de ({pt.x:.4f}, {pt.y:.4f})")
        print(f"[CLASSE {est}] PARADO: linha que não separa terra de água (traçado "
              "duplicado ou contorno de unidade geológica em vez de costa). "
              "Conserte no QGIS. Nada foi gravado.")
        sys.exit(1)

    for k, (p, c) in enumerate(sorted(zip(pecas, cor), key=lambda t: -t[0].area)[:8]):
        print(f"[PECA {est}.{k}] {area_km2(p):9,.2f} km² | {'TERRA' if c else 'mar'}")

    terra = unary_union([p for p, c in zip(pecas, cor) if c == 1]).buffer(0)
    debug = [(p, "terra" if c == 1 else "mar") for p, c in zip(pecas, cor)]

    # 5. Conferências de sentido.
    if not terra.contains(Point(*cfg["ponto_continente"])):
        print(f"[CLASSE {est}] PARADO: o ponto_continente {cfg['ponto_continente']} "
              "(Tabuleiros do Barreiras) saiu MAR. A paridade inverteu — há linha "
              "aberta ou duplicada entre o mar e o continente. Abra "
              f"{cfg['arq_debug'].name} no QGIS. Nada foi gravado.")
        sys.exit(1)
    frac = area_km2(terra) / quadro_km2
    if frac > cfg["frac_terra_max"]:
        print(f"[CLASSE {est}] PARADO: a terra ficou com {100 * frac:.1f}% do "
              "quadro — não sobrou mar. Nada foi gravado.")
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

    dir_fonte = cfg["dir_saida"] / cfg["subdir_fonte"]
    disponiveis = {}
    for est in ESTAGIOS:
        base = dir_fonte / cfg["padrao_fonte"].format(est=est)
        if base.with_suffix(".shp").exists():
            disponiveis[est] = base
    if not disponiveis:
        print(f"[PALEO] PARADO: nenhum shapefile em {dir_fonte} com o padrão "
              f"{cfg['padrao_fonte'].format(est='<I..VII>')}.shp. Nada foi gravado.")
        return 1
    faltando = [e for e in ESTAGIOS if e not in disponiveis]
    if faltando:
        print(f"[PALEO] estágios sem shapefile: {faltando} — o produto sai só com "
              "os que existem, e o app mostra só esses.")

    feicoes, debug_total = [], []
    nd = cfg["casas_coord"]

    def _arredonda(o):
        if isinstance(o, (list, tuple)):
            return [_arredonda(x) for x in o]
        return round(float(o), nd)

    # Ordem cronológica (mais antigo primeiro) — é a ordem do slider.
    for est in sorted(disponiveis, key=lambda e: -ESTAGIOS[e]["idade_ordem"]):
        meta = ESTAGIOS[est]
        base = disponiveis[est]
        print(f"\n[ESTAGIO {est}] {meta['titulo']} — {meta['idade_rotulo']} "
              f"({meta['figura']})")
        conferir_prj(base.with_suffix(".prj"))
        linhas = ler_linhas(base)

        terra, debug = terra_do_estagio(linhas, est)
        debug_total.extend((p, est, classe) for p, classe in debug)

        pecas = partes(terra)
        km2 = area_km2(terra)
        n_vert = sum(len(p.exterior.coords) + sum(len(f.coords) for f in p.interiors)
                     for p in pecas)
        print(f"[ESTAGIO {est}] TERRA EMERSA: {km2:,.1f} km² | {len(pecas)} parte(s) | "
              f"{n_vert} vértices | válido={terra.is_valid}")

        geom = mapping(terra)
        feicoes.append({
            "type": "Feature",
            "properties": {
                "estagio":       est,
                "titulo":        meta["titulo"],
                "periodo":       meta["periodo"],
                "idade_rotulo":  meta["idade_rotulo"],
                "idade_ordem":   meta["idade_ordem"],
                "nmrm_m":        meta["nmrm_m"],
                "nmrm_obs":      meta["nmrm_obs"],
                "descricao":     meta["descricao"],
                "figura":        meta["figura"],
                "area_km2_aprox_esferica": round(km2, 1),
                "n_partes":      len(pecas),
                "n_vertices":    n_vert,
                "arquivo_fonte": f"{cfg['subdir_fonte']}/{base.name}.shp",
                "metodo": ("linhas terra/água digitalizadas pela turma no QGIS sobre "
                           "a figura georreferenciada; polígono fechado contra o "
                           "quadro da figura por 2-coloração (cada linha troca "
                           "terra/água), em 10_paleolinhas.py"),
                "precisao": ("RECONSTRUÇÃO redesenhada, não medição. Erro posicional "
                             "da ordem de centenas de metros (figura de 2003 "
                             "escaneada e georreferenciada por pontos de controle). "
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
    cfg["arq_debug"].parent.mkdir(parents=True, exist_ok=True)
    dbg = {
        "type": "FeatureCollection",
        "name": "paleo_pecas_debug",
        "crs": {"type": "name", "properties": {"name": cfg["rotulo_crs"]}},
        "features": [{
            "type": "Feature",
            "properties": {"estagio": est, "classe": classe,
                           "area_km2": round(area_km2(p), 3)},
            "geometry": {"type": mapping(p)["type"],
                         "coordinates": _arredonda(mapping(p)["coordinates"])},
        } for p, est, classe in debug_total],
    }
    with open(cfg["arq_debug"], "w", encoding="utf-8") as f:
        json.dump(dbg, f, ensure_ascii=False)
    print(f"[DEBUG]  {cfg['arq_debug']} ({len(debug_total)} peça(s)) — abra no QGIS "
          "se a classificação terra/mar não bater com o esperado.")

    # ---- Resumo comparativo --------------------------------------------------
    print("\n[RESUMO] terra emersa por estágio (dentro do quadro da figura):")
    for f_ in feicoes:
        p = f_["properties"]
        print(f"  {p['estagio']:>4}  {p['idade_rotulo']:>22}  "
              f"{p['area_km2_aprox_esferica']:9,.1f} km²  ({p['n_partes']} parte(s))")
    print("[RESUMO] km² para comparação entre estágios. Não cite como medida "
          "absoluta — ver 'precisao' nas propriedades.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
