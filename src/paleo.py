"""
src/paleo.py — Reconstrução paleoambiental de Caravelas (v2.1)

MOTOR, sem interface. Não importa Streamlit, folium nem ipywidgets — mesma
separação de `slr_core.py` (regra do §3 do CLAUDE.md). Quem desenha controle é
o `02_simulador_nmrm.py`.

O QUE ESTE MÓDULO FAZ
    Lê `dados_web/paleolinhas_turma.geojson` (produto de `10_paleolinhas.py`),
    rasteriza o polígono de terra emersa de cada estágio evolutivo na grade do
    MDE e compara com a terra de HOJE, dentro do quadro da figura do artigo.

    Três classes saem dessa comparação:
        PERMANENTE  terra no estágio E terra hoje
        GANHO       mar no estágio, terra hoje  -> planície construída desde então
        PERDA       terra no estágio, mar hoje  -> terreno erodido desde então

O QUE ESTE MÓDULO NÃO FAZ
    Não simula nada. Os polígonos são REDESENHO das Figs. 9 a 15 de Andrade et
    al. (2003), com erro posicional da ordem de centenas de metros. Servem para
    comparar estágios entre si — onde o erro é em boa parte sistemático e se
    cancela —, não como medida absoluta. Ver §5 do CLAUDE.md.

    E não corta o MDE numa paleocota para "reconstruir" o passado: o terreno de
    hoje é PRODUTO daquele nível do mar, não seu contemporâneo. Cortar o FABDEM
    moderno em +4,8 m responde "o que alagaria se o mar subisse 4,8 m hoje",
    que é outra pergunta. A paleogeografia vem do polígono, que é o dado.

"HOJE" VEM DO FABDEM, NÃO DE UM ESTÁGIO DIGITALIZADO
    Decisão de 24/09/2026, revista em 01/10/2026. Nenhum dos sete estágios é a
    costa atual: o VII ("Retomada da progradação") é a última fase do modelo
    quaternário, no Holoceno tardio (< 1.300 cal AP). A costa atual aparece nas
    figuras só como a linha tracejada "present day coastline"; aqui ela vem do
    FABDEM a 30 m.

TODA ÁREA AQUI É CONTADA EM PIXEL DA GRADE DO MDE
    E não pela geometria esférica do polígono (que `10_paleolinhas.py` imprime).
    Motivo: assim paleo e hoje são medidos com a MESMA régua, e a diferença
    entre eles não carrega discrepância de método. Os dois números aparecem lado
    a lado em `estatisticas_estagio` justamente para a divergência ficar visível.
"""
from __future__ import annotations

import json

import numpy as np

# =============================================================================
# CONFIG — todo limiar numérico mora aqui (nunca hardcodado dentro de função)
# =============================================================================

CONFIG_PALEO = {
    "arquivo": "paleolinhas_turma.geojson",

    # CRS rotulado nos GeoJSON da turma. Coordenadas são CRS84 sem
    # transformação — mesma convenção de `limite_turma` e `ucs_turma`, e o que
    # `core.mascara_recorte` e `core._path_geometria` esperam. Ver §4 do CLAUDE.md.
    "crs_origem": "EPSG:4674",

    # Quadro de análise de reserva. O normal é vir de
    # `properties.quadro_figura` do próprio GeoJSON; isto aqui só entra se um
    # arquivo antigo não trouxer a propriedade.
    "quadro_reserva": {"lon_min": -39.50, "lon_max": -39.00,
                       "lat_min": -18.00, "lat_max": -17.50},

    # Cores CARTOGRÁFICAS: carregam significado, então NÃO mudam com o tema —
    # mesma regra da lâmina d'água em `core.CONFIG_TEMA`. O tema mexe só no
    # papel da figura (fundo, título, eixos, créditos).
    "cores": {
        "permanente": "#8c7a55",   # terra nos dois momentos
        "ganho":      "#2e9e5b",   # construída desde o estágio
        "perda":      "#c0392b",   # erodida desde o estágio
        "contorno":   "#232323",   # mesma cor de borda do .qlr do QGIS
    },
    "alpha_overlay_web": 0.72,
    "alpha_figura": 0.88,
    "alpha_oceano": 0.80,

    # "perda" NÃO se chama "erodida". No Estágio I essa classe cai quase toda
    # sobre os canais do estuário Caravelas–Peruípe e a rede de marés — terreno
    # que o polígono paleo cobre e que hoje é água, mas por drenagem, não por
    # recuo de costa. "Erodida" nomearia um processo que a comparação não
    # distingue. O rótulo diz o que o dado diz, e nada além.
    "rotulos": {
        "permanente": "Terra nos dois momentos",
        "ganho":      "Construída desde o estágio",
        "perda":      "Terra então, água hoje",
    },

    # Abaixo disto a classe some da legenda: com um estágio em que a erosão é
    # nula, um item "0,0 km²" na legenda sugere um fenômeno que não aconteceu.
    "area_min_legenda_km2": 0.5,

    "lw_contorno": 1.3,
    "dpi_export": 300,
    "fracao_margem_quadro": 0.02,   # folga em volta do enquadramento, na figura

    # ENQUADRAMENTO PADRÃO. "dados" fecha no bbox do que foi classificado;
    # "quadro" mostra o retângulo inteiro das figuras do artigo. Enquadramento
    # NÃO é recorte — os dois contam exatamente os mesmos km², só muda o que
    # entra no quadro (mesma distinção do `enquadramento` de `core.figura_mapa`).
    # O padrão é "dados" porque o quadro vai até 39°00'W e o FABDEM não
    # distribui tile oceânico: um terço da figura sairia cinza vazio.
    "enquadramento_padrao": "dados",

    # Fração da massa classificada que o enquadramento "dados" precisa conter.
    # Não é 1.0 de propósito: o FABDEM cobre recifes e ilhotas soltos lá no
    # leste do quadro, e meia dúzia desses pixels esticava o bbox por dezenas de
    # km, devolvendo um terço de figura em cinza. Cortar pelas pontas da
    # distribuição enquadra onde a paleogeografia de fato está. Não muda km².
    "fracao_enquadramento_dados": 0.995,
}

FONTE_PALEO = {
    "referencia": ("Andrade ACS, Dominguez JML, Martin L, Bittencourt ACSP (2003). "
                   "Quaternary evolution of the Caravelas strandplain – Southern "
                   "Bahia State – Brazil. An Acad Bras Cienc 75(3): 357-382."),
    "metodo": ("Linhas terra/água digitalizadas pela turma no QGIS sobre as "
               "Figs. 9 a 15 georreferenciadas; polígonos fechados por "
               "10_paleolinhas.py."),
    "precisao": ("RECONSTRUÇÃO redesenhada, não medição e não simulação. Erro "
                 "posicional da ordem de centenas de metros (figura de 2003 "
                 "escaneada, 4 pontos de controle). Compare estágios entre si; "
                 "não cite como medida absoluta."),
    "hoje": ("A terra de hoje vem do FABDEM V1-2 a 30 m, não de um estágio "
             "digitalizado."),
}


def _print(msg: str) -> None:
    """Espelha `core._print`: rede de segurança para console cp1252 no Windows
    quando alguém importa o motor sem passar pelo `config.configurar_console()`."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


# =============================================================================
# LEITURA
# =============================================================================

def carregar_paleolinhas(caminho: str) -> dict | None:
    """
    Lê o GeoJSON de `10_paleolinhas.py`. Devolve None se o arquivo não existir —
    a aba então se desabilita sozinha, como o controle de recorte faz sem
    `limite_turma.geojson`. Nunca exceção por arquivo ausente.
    """
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            gj = json.load(f)
    except (OSError, json.JSONDecodeError) as erro:
        _print(f"[PALEO] {caminho} indisponível ({erro.__class__.__name__}) — aba desligada")
        return None

    feicoes = gj.get("features", [])
    if not feicoes:
        _print("[PALEO] GeoJSON sem feições — aba desligada")
        return None
    _print(f"[PALEO] {len(feicoes)} estágio(s): "
           f"{[f['properties'].get('estagio') for f in feicoes]}")
    return gj


def estagios(gj: dict) -> list[dict]:
    """
    Lista de estágios em ordem CRONOLÓGICA (mais antigo primeiro) — a ordem do
    seletor de tempo na interface. Cada item é o `properties` da feição mais a
    própria geometria, para quem chama não precisar mexer no GeoJSON cru.
    """
    itens = []
    for f in gj.get("features", []):
        p = dict(f.get("properties", {}))
        p["_geometria"] = f.get("geometry")
        itens.append(p)
    return sorted(itens, key=lambda p: -(p.get("idade_ordem") or 0))


def quadro(gj: dict) -> dict:
    """Bbox do quadro das figuras, do próprio GeoJSON (com reserva no CONFIG)."""
    q = (gj or {}).get("properties", {}).get("quadro_figura")
    return dict(q) if q else dict(CONFIG_PALEO["quadro_reserva"])


def _fc(geometria: dict) -> dict:
    """Embrulha uma geometria num FeatureCollection de uma feição — é o que
    `core.mascara_recorte` e `core._bbox_pixel_geojson` consomem."""
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {},
                          "geometry": geometria}]}


def _fc_quadro(q: dict) -> dict:
    """FeatureCollection do retângulo do quadro, para rasterizar."""
    anel = [[q["lon_min"], q["lat_min"]], [q["lon_max"], q["lat_min"]],
            [q["lon_max"], q["lat_max"]], [q["lon_min"], q["lat_max"]],
            [q["lon_min"], q["lat_min"]]]
    return _fc({"type": "Polygon", "coordinates": [anel]})


# =============================================================================
# RASTERIZAÇÃO E COMPARAÇÃO
# =============================================================================

def mascara_quadro(core, gj: dict, dados_dem: dict) -> np.ndarray:
    """
    Bool na forma do MDE: True dentro do quadro das Figs. 9 a 15.

    Existe porque o quadro é MENOR que `config.BBOX_WGS84`. Sem ele, "terra
    hoje" contaria a planície inteira do domínio contra um polígono paleo que
    só cobre o quadro — e a diferença seria pura assimetria de recorte, não
    progradação. `core` entra por parâmetro para este módulo não importar
    `slr_core` e criar dependência circular na interface.
    """
    return core.mascara_recorte(_fc_quadro(quadro(gj)), dados_dem)


def mascara_estagio(core, estagio: dict, dados_dem: dict) -> np.ndarray:
    """Bool na forma do MDE: True onde havia TERRA EMERSA naquele estágio."""
    return core.mascara_recorte(_fc(estagio["_geometria"]), dados_dem)


def classificar(terra_paleo: np.ndarray, terra_hoje: np.ndarray,
                dentro_quadro: np.ndarray) -> np.ndarray:
    """
    Grade de classes uint8, já recortada ao quadro:
        0 = nada a dizer (mar nos dois momentos, ou fora do quadro)
        1 = PERMANENTE   2 = GANHO   3 = PERDA
    """
    c = np.zeros(terra_hoje.shape, dtype=np.uint8)
    c[dentro_quadro & terra_paleo & terra_hoje] = 1
    c[dentro_quadro & ~terra_paleo & terra_hoje] = 2
    c[dentro_quadro & terra_paleo & ~terra_hoje] = 3
    return c


def estatisticas_estagio(classes: np.ndarray, area_pixel_m2: float,
                         estagio: dict) -> dict:
    """
    Áreas em km² a partir da grade de classes. Tudo contado em PIXEL, para
    paleo e hoje saírem com a mesma régua (ver o cabeçalho do módulo).

    `area_poligono_km2` é a área esférica que `10_paleolinhas.py` gravou na
    propriedade da feição — fica ao lado da área rasterizada de propósito: se
    as duas divergirem muito, o polígono cobre bastante pixel sem MDE (oceano
    sem tile FABDEM), e a interface precisa dizer isso em vez de escolher uma.
    """
    a = area_pixel_m2 / 1e6
    permanente = float((classes == 1).sum()) * a
    ganho = float((classes == 2).sum()) * a
    perda = float((classes == 3).sum()) * a

    terra_paleo = permanente + perda
    terra_hoje = permanente + ganho
    variacao = terra_hoje - terra_paleo
    pct = (100.0 * variacao / terra_paleo) if terra_paleo > 0 else float("nan")

    _print(f"[PALEO {estagio.get('estagio')}] paleo={terra_paleo:.1f} km² | "
           f"hoje={terra_hoje:.1f} km² | ganho={ganho:.1f} | perda={perda:.1f} | "
           f"variação={variacao:+.1f} km² ({pct:+.1f}%)")

    return {
        "estagio": estagio.get("estagio"),
        "titulo": estagio.get("titulo"),
        "periodo": estagio.get("periodo"),
        "idade_rotulo": estagio.get("idade_rotulo"),
        "nmrm_m": estagio.get("nmrm_m"),
        "area_permanente_km2": permanente,
        "area_ganho_km2": ganho,
        "area_perda_km2": perda,
        "area_terra_paleo_km2": terra_paleo,
        "area_terra_hoje_km2": terra_hoje,
        "variacao_km2": variacao,
        "variacao_pct": pct,
        "area_poligono_km2": estagio.get("area_km2_aprox_esferica"),
    }


def tabela_estagios(core, gj: dict, dados_dem: dict) -> "list[dict]":
    """
    Roda a comparação para TODOS os estágios disponíveis — é o que alimenta a
    tabela comparativa e, quando houver mais de um estágio, a curva de
    progradação. Rasteriza o quadro e a terra de hoje uma vez só.
    """
    dentro = mascara_quadro(core, gj, dados_dem)
    terra_hoje = np.isfinite(dados_dem["dem"])
    linhas = []
    for est in estagios(gj):
        cls = classificar(mascara_estagio(core, est, dados_dem), terra_hoje, dentro)
        linhas.append(estatisticas_estagio(cls, dados_dem["area_pixel_m2"], est))
    return linhas


# =============================================================================
# OVERLAY PARA O MAPA INTERATIVO
# =============================================================================

def cores_overlay() -> dict:
    """Mapa classe -> cor hex, no formato que `mapa_web.gerar_overlay_web` usa."""
    c = CONFIG_PALEO["cores"]
    return {1: c["permanente"], 2: c["ganho"], 3: c["perda"]}


def _pares_legenda(stats: dict) -> list:
    """(chave, área) das classes que merecem entrar na legenda. `stats` é o que
    `estatisticas_estagio` devolve — não confundir com o dicionário do estágio,
    que carrega os metadados e a geometria."""
    return [(k, v) for k, v in (("permanente", stats.get("area_permanente_km2", 0.0)),
                                ("ganho", stats.get("area_ganho_km2", 0.0)),
                                ("perda", stats.get("area_perda_km2", 0.0)))
            if v >= CONFIG_PALEO["area_min_legenda_km2"]]


def itens_legenda(stats: dict) -> list[dict]:
    """
    Itens de legenda para `_legenda_html` do `02`, já sem as classes de área
    desprezível (ver `area_min_legenda_km2`).
    """
    cores, rot = CONFIG_PALEO["cores"], CONFIG_PALEO["rotulos"]
    return [{"cor": cores[k], "rotulo": f"{rot[k]} — {v:,.0f} km²"}
            for k, v in _pares_legenda(stats)]


# =============================================================================
# FIGURA DE RELATÓRIO
# =============================================================================

def _faixa_massa(soma: np.ndarray, fracao: float) -> tuple:
    """
    Menor intervalo de índices que contém `fracao` da massa de `soma`, cortando
    o resto igualmente pelas duas pontas. É um bbox por PERCENTIL, não por
    mínimo e máximo: meia dúzia de pixels soltos (recife, ilhota) não deve
    decidir o enquadramento de um mapa de 50 km.
    """
    total = float(soma.sum())
    if total <= 0:
        return None
    acum = np.cumsum(soma) / total
    fora = (1.0 - fracao) / 2.0
    i0 = int(np.searchsorted(acum, fora))
    i1 = int(np.searchsorted(acum, 1.0 - fora))
    return (min(i0, i1), max(i0, i1))


def _bbox_massa(mascara: np.ndarray, fracao: float) -> tuple | None:
    """(col_min, col_max, lin_min, lin_max) por percentil — ver `_faixa_massa`."""
    cols = _faixa_massa(mascara.sum(axis=0), fracao)
    lins = _faixa_massa(mascara.sum(axis=1), fracao)
    if cols is None or lins is None:
        return None
    return (float(cols[0]), float(cols[1]), float(lins[0]), float(lins[1]))

def figura_paleo(core, dados_dem: dict, classes: np.ndarray, est: dict,
                 stats: dict, gj: dict, hs: np.ndarray = None,
                 tema: str = "claro", figsize=(10, 9),
                 enquadramento: str = None,
                 dentro_quadro: np.ndarray = None):
    """
    Figura de 300 dpi: hillshade + as três classes + contorno da paleolinha,
    enquadrada no quadro da figura do artigo.

    `est` traz os metadados e a geometria do estágio (de `estagios`); `stats`
    traz as áreas (de `estatisticas_estagio`). São dois dicionários de propósito:
    as áreas dependem da grade do MDE e o estágio não.

    Reaproveita os auxiliares do `slr_core` (`hillshade`, `paleta`,
    `_bbox_pixel_geojson`, `_path_geometria`, `_barra_escala`) em vez de
    duplicá-los — `core` entra por parâmetro pelo mesmo motivo de
    `mascara_quadro`.

    Retorna (fig, ax); quem chamou decide se salva ou exibe.
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch, PathPatch

    cfg = CONFIG_PALEO
    dem = dados_dem["dem"]
    transform = dados_dem["transform"]
    hs = core.hillshade(dem, dados_dem["res_x"]) if hs is None else hs
    pal = core.paleta(tema)

    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(pal["fundo_figura"])
    ax.set_facecolor(pal["fundo_figura"])

    # Fundo: sombreado em cinza. O hipsométrico competiria com as três classes,
    # que aqui são o assunto — e em Caravelas ele gasta a faixa de cor toda nos
    # primeiros metros (decisão da v1.2). vmin/vmax vêm do tema: no escuro o
    # cinza é comprimido, senão o hillshade vira um continente branco estourado.
    ax.imshow(hs, cmap="gray", vmin=pal["hillshade_vmin"], vmax=pal["hillshade_vmax"],
              alpha=0.85, zorder=0)

    # Mar nos DOIS momentos, pintado só DENTRO do quadro de análise. Em cinza
    # ele lia como "sem dado", que é a leitura errada — ali é oceano. Fora do
    # quadro segue sendo o papel da figura, nunca cor de água: a regra da v1.5
    # vale aqui igual, terra alta lida como mar é o pior erro deste mapa.
    # `dentro_quadro` chega por parâmetro justamente para esta camada não
    # extravasar para onde a análise não foi feita.
    if dentro_quadro is not None:
        mar = dentro_quadro & (classes == 0)
        if mar.any():
            rgba = np.zeros(mar.shape + (4,), dtype=float)
            r, g, b = tuple(int(core.CONFIG_MAPA["cor_oceano"][i:i + 2], 16) / 255
                            for i in (1, 3, 5))
            rgba[mar] = (r, g, b, cfg["alpha_oceano"])
            ax.imshow(rgba, zorder=1)

    # As três classes, cada uma como uma máscara colorida só onde vale.
    for valor, chave in ((1, "permanente"), (2, "ganho"), (3, "perda")):
        m = (classes == valor)
        if not m.any():
            continue
        rgba = np.zeros(m.shape + (4,), dtype=float)
        r, g, b = tuple(int(cfg["cores"][chave][i:i + 2], 16) / 255 for i in (1, 3, 5))
        rgba[m] = (r, g, b, cfg["alpha_figura"])
        ax.imshow(rgba, zorder=2)

    # Contorno do polígono do estágio — é a paleolinha de costa, que é o dado.
    path = core._path_geometria(est["_geometria"], transform, cfg["crs_origem"])
    if path is not None:
        ax.add_patch(PathPatch(path, facecolor="none", edgecolor=cfg["cores"]["contorno"],
                               lw=cfg["lw_contorno"], zorder=4))

    # Enquadramento. "quadro" usa o retângulo das figuras do artigo (o bbox em
    # PIXEL sai de `_bbox_pixel_geojson`, que continua valendo fora da grade
    # porque geo->pixel é uma afim). "dados" fecha no que foi classificado.
    # Nenhum dos dois muda número nenhum — ver `enquadramento_padrao`.
    enq = enquadramento or cfg["enquadramento_padrao"]
    bb = None
    if enq == "dados":
        bb = _bbox_massa(classes > 0, cfg["fracao_enquadramento_dados"])
    if bb is None:
        bb = core._bbox_pixel_geojson(_fc_quadro(quadro(gj)), transform,
                                      cfg["crs_origem"])
    if bb:
        c0, c1, l0, l1 = bb
        mx = cfg["fracao_margem_quadro"] * max(c1 - c0, l1 - l0)
        ax.set_xlim(c0 - mx, c1 + mx)
        ax.set_ylim(l1 + mx, l0 - mx)          # y invertido: origem no topo
    ax.set_xticks([]); ax.set_yticks([])
    for lado in ax.spines.values():
        lado.set_color(pal["borda"])

    nmrm = est.get("nmrm_m")
    sub = (f"{est.get('idade_rotulo', '')}"
           + (f" · NMRM {nmrm:+.1f} m" if isinstance(nmrm, (int, float)) else "")
           + " · reconstrução redesenhada de Andrade et al. (2003), "
             f"{est.get('figura', '')}")
    ax.set_title(f"Paleoambiente de Caravelas — Estágio {est.get('estagio')}: "
                 f"{est.get('titulo', '')}",
                 fontsize=13, weight="bold", loc="left", pad=24, color=pal["texto"])
    ax.text(0, 1.012, sub, transform=ax.transAxes, fontsize=8.5, color=pal["texto_fraco"])

    # Seta norte (a grade está em UTM, então norte é o topo) e barra de escala,
    # ambas em cor fixa: são conteúdo do mapa, não papel (regra do tema, v1.2).
    ax.annotate("N", xy=(0.965, 0.955), xytext=(0.965, 0.875),
                xycoords="axes fraction", ha="center", fontsize=11, weight="bold",
                arrowprops=dict(arrowstyle="-|>", color="k", lw=1.6), zorder=10)
    if bb:
        core._barra_escala(ax, transform, dem.shape[1],
                           quadro=(bb[0], bb[1], bb[2], bb[3]))

    itens = [Patch(facecolor=cfg["cores"][k], edgecolor="none",
                   label=f"{cfg['rotulos'][k]} — {v:,.0f} km²")
             for k, v in _pares_legenda(stats)]
    if itens:
        ax.legend(handles=itens, loc="lower right", fontsize=8, framealpha=.85)

    q = quadro(gj)
    creditos = (f"Paleolinha: {FONTE_PALEO['referencia']} · {FONTE_PALEO['metodo']}\n"
                f"Terra de hoje: FABDEM V1-2 (Hawker et al. 2022), 30 m · análise "
                f"restrita ao quadro da figura ({q['lon_min']:.2f}/{q['lon_max']:.2f}°W, "
                f"{q['lat_min']:.2f}/{q['lat_max']:.2f}°); azul = mar nos dois "
                f"momentos, cinza = fora da análise.\n"
                f"{FONTE_PALEO['precisao']}")
    if stats.get("area_perda_km2", 0.0) >= cfg["area_min_legenda_km2"]:
        creditos += ("\n\"Terra então, água hoje\" inclui a rede de canais de maré e o "
                     "estuário atuais — não é, por si, recuo de linha de costa.")
    ax.text(0, -0.035, creditos, transform=ax.transAxes, fontsize=7,
            va="top", color=pal["texto_fraco"])
    return fig, ax
