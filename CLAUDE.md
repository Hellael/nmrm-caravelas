# CLAUDE.md — Projeto NMRM Caravelas

> Arquivo lido automaticamente pelo Claude Code no início de cada sessão.
> Mantenha-o atualizado: é a memória do projeto entre sessões.

## 1. Contexto

Disciplina **Ecossistemas Marinhos Costeiros** — UERJ / FAOC / DOB
(Prof. Filipe Chaves). Semestre 2026.2.

**Pergunta do semestre:** como a elevação do Nível Médio Relativo do Mar (NMRM)
poderá reorganizar os ecossistemas costeiros, e quais consequências ecológicas
e sociais emergem dessa transformação?

**Cadeia analítica da disciplina:**
`Cenário → Exposição → Processo → Resposta ecológica → Serviço → Sociedade → Adaptação`

**Área de estudo:** planície costeira de Caravelas, extremo sul da Bahia.
Praia, restinga, duna, manguezal e o sistema estuarino Caravelas–Peruípe.
Planície **extremamente plana** e progradante, com cordões litorâneos
quaternários. O usuário tem experiência de campo na área.

**Escopo do trabalho:**
- **Parte 1 (atual):** ferramenta geoespacial interativa e parametrizada de
  exposição ao NMRM.
- **Parte 2:** modelagem da resposta ecológica.
- **Parte 3 (fora de escopo):** hidrodinâmica SFINCS e/ou paleoclima.

**Prazos:** mapa de elevação simples já entregue; demais entregas em meados
de outubro.

## 2. Estrutura do repositório

```
nmrm-caravelas/
├── CLAUDE.md                  # este arquivo
├── README.md
├── LICENSE                    # CC BY-NC-SA 4.0
├── requirements.txt           # pisos de versão do app (Streamlit Cloud)
├── requirements-geracao.txt   # shapely: SÓ p/ scripts que geram dados_web/; NÃO é instalado no app
├── .gitignore                 # ignora dados/ e saidas/ (dados_web/ é versionado)
├── .streamlit/config.toml     # tema escuro e limites do app publicado
├── .devcontainer/             # devcontainer.json (ambiente reproduzível)
├── .vscode/                   # launch.json + settings.json
├── config.py                  # caminhos, bbox, CRS, BBOX_TURMA, nomes de arquivo — fonte única
├── src/
│   ├── __init__.py
│   ├── slr_core.py            # MOTOR — sem interface, toda a ciência (cota, máscara, estatística, figura)
│   ├── fonte_dados.py         # resolve modo local x web; leitura tolerante; guarda de saturação do limiar
│   ├── mapa_web.py            # camadas do mapa interativo (overlays, isolinhas, camadas da turma)
│   └── cobertura.py           # legenda MapBiomas Col. 11 + leitura do recorte
├── 01_mapa_elevacao.py        # mosaico/recorte/reprojeção FABDEM + mapa base
├── 02_simulador_nmrm.py       # interface Streamlit sobre slr_core (modos Turma/Livre)
├── 03_prepara_dem_web.py      # dados leves + limiar de conexão pré-computado (dados_web/)
├── 04_prepara_cobertura.py    # recorte do MapBiomas alinhado à grade do projeto
├── 05_valida_cobertura_elevacao.py  # [diagnóstico] cobertura x elevação (FABDEM completo)
├── 06_diagnostico_dossel.py   # [diagnóstico] quanto do "isolada" vem do viés de dossel no mangue (somente leitura)
├── 07_mare_tpxo.py            # proveniência da maré TPXO9-atlas v5 (roda FORA deste repo)
├── 08_prepara_camadas_turma.py  # regenera ucs_turma.geojson a partir do CNUC bruto e compara
├── 09_limite_turma.py         # converte o shapefile da área de estudo -> limite_turma.geojson
├── diagnostico_zeros.py       # [diagnóstico] os 0,0 m do FABDEM são todos oceano? (docs/diagnostico_zeros.md)
├── histograma_cauda_costeira.py  # [diagnóstico] histograma fino da cauda inferior de cota
├── teste_sintetico.py         # valida o pipeline sem FABDEM; grava o MDE sintético em saidas/, NUNCA em processado/
├── docs/
│   ├── logica_da_ferramenta.md        # como a ferramenta raciocina, ponta a ponta
│   ├── diagnostico_zeros.md           # investigação dos 0,0 m suspeitos no FABDEM
│   └── validacao_mapbiomas_laudo.md   # validação da cobertura contra o laudo
├── dados_web/                 # dados leves VERSIONADOS (~2,3 MB) — o que o app publicado lê
│   ├── dem_30m_web.tif, mascara_agua_web.tif, limiar_conexao_web.tif, cobertura_web.tif
│   ├── metadados_web.json     # diagnóstico do recorte e proveniência dos dados leves
│   ├── mare_caravelas_tpxo9v5.json    # produto do 07 (constituintes e datums de maré)
│   ├── ucs_turma.geojson      # 3 UCs da turma (CNUC 07/2026) — reproduzível pelo 08
│   ├── isobatas_turma.geojson # isóbatas 20–500 m (CPRM/ANP 2013) — filtragem NÃO reprodutível
│   ├── limite_turma.geojson   # área de estudo da turma (produto do 09) — camada E geometria do recorte
│   └── fonte_limite_turma/    # shapefile de origem da área de estudo (QGIS) — VERSIONADO
│   └── LICENSE.txt
├── dados/                     # SÓ existe se NMRM_DIR_DADOS não estiver definida (nesta máquina: vazia/ausente)
└── saidas/                    # PNG, GeoTIFF, CSV com carimbo de data (NÃO versionar; faxina periódica)
```

Os dados pesados vivem em **`NMRM_DIR_DADOS`** (nesta máquina, `C:\dados_nmrm`),
não em `dados/`: `fabdem/` (tiles), `auxiliar/` (MapBiomas nacional
`brazil_coverage-col11_2025.tif`, recorte de cobertura, `ucs_regiao.geojson`) e
`processado/` (MDE e máscara de água). `config.DIR_DADOS` resolve para lá.

`abrir_tiff_mapbiomas.py` foi o exploratório que originou o `04`. Está superado —
não usar; o `04` alinha à grade e usa a legenda oficial conferida.

## 3. Convenções de código (obrigatórias)

- **Idioma:** código, comentários, docstrings e nomes de variáveis em
  **português**.
- **Parâmetros centralizados:** todo limiar numérico vive em dicionário
  `CONFIG_*` / `CENARIOS_*` / `NIVEIS_*` no topo do módulo.
  **Nunca hardcodar valor dentro de função.**
- **Prints diagnósticos sempre**, no formato de tag. Dentro de
  `src/slr_core.py` use `_print`, não `print` — o console do Windows roda em
  cp1252 e estoura `UnicodeEncodeError` em qualquer caractere fora dessa
  tabela (→, Δ, ≈), derrubando a simulação no meio de uma linha de log:
  ```python
  _print(f"[MASCARA] cota={cota:.2f} m | inundada={n_px} px")
  _print(f"[AREA] terra={a:.1f} km² | inundada={b:.1f} km² ({p:.1f}%)")
  ```
  `config.configurar_console()` (chamado no import de `config.py`) resolve na
  origem, colocando stdout/stderr em UTF-8; `_print` é a rede de segurança
  para quem importar o motor sem passar pelo config. Em texto que vai só para
  a interface Streamlit (emoji, `≈`) não há restrição — a UI é UTF-8.
- **Scripts completos e executáveis**, nunca trechos parciais.
- **Exports com carimbo de data:** `matriz_cenarios_20260826.csv`.
- **Separação motor/interface:** `slr_core.py` não importa Streamlit,
  ipywidgets ou qualquer UI. Interfaces só desenham controles.
- Nível Python do usuário: **intermediário**. Explicar decisões não óbvias
  em comentário, sem encher de abstração.

## 4. Dados

| Base | Uso | Observação |
|------|-----|------------|
| **FABDEM V1-2** | MDE principal | Hawker et al. 2022, ERL 17:024016. Copernicus GLO-30 com dossel e edificações removidos por ML. 1 arcsec (~30 m), 60°S–80°N, datum vertical **EGM2008**. Licença **CC BY-NC-SA 4.0** (uso acadêmico OK). Oceano codificado como exatamente `0.0`. |
| **IPCC AR6** | Cenários SSP | Valores de `CENARIOS_AR6` vêm da **Tabela 9.9 do AR6 WGI Cap. 9** (Fox-Kemper et al. 2021) — NMGM, mediana e faixa provável 17–83 %, base 1995–2014. **Nada foi calculado por nós.** SSP5-8.5 conferido contra o Sumário Executivo do Cap. 9 (set/2026): 0,23 [0,20–0,29] m em 2050 e 0,77 [0,63–1,01] m em 2100. SSP1-2.6, SSP2-4.5 e SSP5-8.5 LC ainda **não conferidos linha a linha**. São **globais (NMGM)**: substituir pelos locais do NASA/IPCC AR6 Sea Level Projection Tool (Garner et al., Zenodo 10.5281/zenodo.5914709). Ver `core.FONTE_CENARIOS`. |
| **GEBCO 2025** | Batimetria de contexto | — |
| **MapBiomas Col. 11 (2025)** | Cobertura do solo | `brazil_coverage-col11_2025.tif` (nacional, 763 MB, uint8, EPSG:4326; em `DIR_AUXILIAR`, constante `config.ARQ_MAPBIOMAS_NACIONAL` — o `04` procura só ali). Recortado por `04_prepara_cobertura.py`, reamostragem **nearest** (categórico), alinhado pixel a pixel à grade do MDE. Legenda (código, nome, cor) transcrita do CSV oficial da Coleção 11 e conferida em set/2026 para os **17 códigos presentes** no recorte — os demais não foram transcritos e a interface os mostra como "fora da legenda conferida". Na v1.3 a camada é **apenas visual**. |
| **TPXO9-atlas v5 (OSU)** | Datums de maré (`core.NIVEIS_MARE`) | Extraído em 22/09/2026 por `07_mare_tpxo.py` (roda fora deste repo; `dados_web/mare_caravelas_tpxo9v5.json` é o produto versionado). Grade 1/30°, ponto ao largo da barra (~3,7 km de célula, ~2,55 km do alvo original). 8 constituintes (Q1, O1, P1, K1, N2, M2, S2, K2) → NM/PMQ/PM/PMS/HAT (este último estimado — soma das amplitudes, limite superior). **Modelo, não medição** — `NIVEIS_MARE["MEDIDA"] = False`. Não resolve o estuário (regra 7); não mexe no datum vertical do MDE (regra 8). |
| **Camadas da turma (vetoriais)** | Contexto desenhado sobre o mapa. Desde a v1.5, `limite_turma.geojson` também é a geometria do **recorte de relato** do modo Turma (contagem, desenho e GeoTIFF — nunca a conectividade); as demais seguem sem entrar em conta nenhuma | `dados_web/limite_turma.geojson` (~16.255 km², aferição esférica na propriedade `area_km2_aprox_esferica`): a **área de estudo que a turma desenhou no QGIS** sobre a batimetria (isóbata de 500 m) e as UCs. Um polígono, 2.771 vértices. O shapefile de origem é **versionado** em `dados_web/fonte_limite_turma/` (~45 KB) — é trabalho manual e insubstituível, então não fica em `NMRM_DIR_DADOS` como o CNUC bruto. `09_limite_turma.py` só CONVERTE: confere o .prj (para se for projetado), corrige anel auto-interceptante com `buffer(0)` e para se a correção mexer mais de 1 km², descarta feição contida em outra (o arquivo tem um rascunho de 84 km² dentro do polígono bom) e para em sobreposição parcial. Para mudar a área: redesenhar no QGIS, substituir o shapefile e rodar o `09` — nunca editar o GeoJSON à mão. Rótulo de CRS EPSG:4674 com coordenadas em CRS84 sem transformar, igual às camadas irmãs. Em 24/09/2026 SUBSTITUIU a camada `area_turma.geojson` (21.955 km², contorno provisório que fechava a oeste numa reta em -39,59° e engolia a planície continental inteira): o arquivo, `ARQ_AREA_TURMA`, `AREA_TURMA_KM2` e a camada na interface foram REMOVIDOS — quem precisar do antigo pega no histórico do git. `dados_web/ucs_turma.geojson` (3 UCs: APA Ponta da Baleia/Abrolhos, RESEX Cassurubá, PARNA Marinho dos Abrolhos — CNUC 07/2026, ICMBio/MMA): **reproduzível** por `08_prepara_camadas_turma.py` a partir de `ucs_regiao.geojson` (CNUC bruto, 42 UCs, em `DIR_AUXILIAR`); a regeneração bate com o versionado em feições, campos, vértices, coordenadas (dif. 0°) e área. A tolerância de simplificação (0,0008°, ~89 m) é **ajuste reverso, não a receita original**, e o CRS é só rotulado como EPSG:4674 (coordenadas em CRS84, sem transformar). `isobatas_turma.geojson` (Batimetria do Brasil CPRM/ANP 2013, derivada do GEBCO 925 m): origem declarada em `config.py`, **mas o passo de filtragem/derivação NÃO é reprodutível hoje** — a fonte bruta não está no repositório nem em `NMRM_DIR_DADOS`. **Atenção RESEX Cassurubá:** `ucs_turma.geojson` já contém o limite dela (item pendente do §6), mas a 249 vértices e ~89 m de tolerância (o original tem 2.482): serve para DESENHAR; para definir setor de análise, usar a geometria cheia de `ucs_regiao.geojson`. |
| **BNDO/CHM · FEMAR** | Constantes harmônicas de MARÉGRAFO (substituiria o TPXO) | `chm.bndo@marinha.mil.br`. **Ainda não solicitado.** Caminho crítico — é a única fonte que tornaria `MEDIDA = True`. |
| **Laudo biológico Cassurubá** | Validação da cobertura | Conferência qualitativa por setor em `docs/validacao_mapbiomas_laudo.md`. Convergiu em zonação, adjacência mangue–apicum e ausência de carcinicultura; **divergiu** na cota do manguezal (ver decisão do viés de dossel). |
| **Andrade et al. 2003** | Evolução quaternária da planície | Paleoníveis +4,8 / +3,5 / +2,5 m — validação opcional. |

**Projeção de trabalho:** SIRGAS 2000 / UTM 24S — **EPSG:31984**, 30 m.

## 5. Decisões metodológicas fechadas

- **Cenários:** SSP1-2.6, SSP2-4.5, SSP5-8.5 (+ SSP5-8.5 baixa confiança).
  Horizontes 2050 e 2100. Percentis 17 / mediana / 83.
- **Níveis de sensibilidade da turma:** +0,5 m, +1 m, +2 m.
  A ferramenta deve extrapolar além desses valores, não travar neles.
- **Modo Manual vai até +10 m (v1.2).** Teto real recalculado em tempo de
  execução contra (a) o alcance do raster de limiar e (b) 75 % do `clamp_m`
  do MDE leve — no modo web isso dá 10 m com folga sobre o teto de 20 m.
  Acima de +3 m a interface avisa que saiu da faixa AR6: ali o mapa é teste
  de sensibilidade do terreno / comparação com paleonível, não cenário
  climático.
- **Conectividade hidráulica LIGADA por padrão.** Terreno abaixo da cota mas
  sem caminho até o mar é classificado à parte (`isolada`), nunca somado à
  área inundada. É o principal diferencial frente aos simuladores online.
- **Maré: TPXO9-atlas v5 substitui os offsets provisórios (22/09/2026).**
  `NIVEIS_MARE` passou de `PROVISORIO = True` (tudo em 0,00 m) para os cinco
  níveis extraídos do TPXO9-atlas v5 (OSU) por `07_mare_tpxo.py` — script
  versionado como proveniência, mas que RODA FORA deste repo, contra o atlas
  de ~10 GB; aqui só entra `dados_web/mare_caravelas_tpxo9v5.json`:
  NM (0,000), PMQ (0,456), PM (0,913), PMS (1,244), HAT estimado (1,676 m —
  soma das 8 amplitudes lidas: Q1, O1, P1, K1, N2, M2, S2, K2. É um LIMITE
  SUPERIOR, não o HAT real — ignora modulação nodal e não inclui M4, MS4, MF,
  MM). PMQ (preamar de quadratura) é nível novo: entra porque a disciplina
  precisa do contraste sizígia x quadratura para ler exposição.
  Continua sendo **modelo, não medição** — a flag virou `MEDIDA = False`
  (a lógica inverteu: antes a tarja aparecia com `PROVISORIO = True`, depois
  passou a aparecer com `MEDIDA = False`). A tarja em si foi retirada da
  barra lateral em 24/09/2026 — ver a decisão "Tarja de maré sai da barra
  lateral" abaixo; `MEDIDA = False` segue valendo. Duas ressalvas que valem enquanto a fonte for
  TPXO, não BNDO/CHM — ver regras 7 e 8 do CLAUDE.md: (1) célula de ~3,7 km,
  ponto AO LARGO da barra, não resolve o estuário; (2) isto NÃO mexe no
  datum vertical do MDE, que é problema independente. O pedido ao BNDO/CHM
  por constantes de marégrafo de verdade segue em aberto.
- **O "nível médio" não é calculado, é herdado (v1.2 documentou isso).**
  O corte é feito em z = 0 m no datum do próprio FABDEM (geoide EGM2008),
  ou seja, assume-se `NM local ≈ geoide` com `OFFSET_GEOIDE_NM_M = 0.00`.
  A diferença real é a topografia dinâmica média (MDT), decimétrica no
  Atlântico Sul tropical — mesma ordem do NMRM de 2050. Nenhuma constante
  harmônica foi usada PARA ESTE OFFSET até aqui — as constantes do TPXO
  (22/09/2026, ver decisão acima) resolvem os datums de MARÉ, não este.
  `OFFSET_GEOIDE_NM_M` segue 0,00 e é problema independente (regra 8).
- **`NMRM_MODO` força o modo (v1.2).** `web` ignora os dados completos e roda
  em `dados_web/` mesmo com o MDE local presente — é como pré-visualizar a
  ferramenta pública na própria máquina. A interface mostra tarja enquanto
  estiver ligado. Valor inválido é ignorado com aviso.
- **Modo web esconde o cenário IPCC AR6 (v1.2).** Na ferramenta pública o
  seletor "Origem do valor" oferece só *Níveis da turma* e *Manual*, com o
  aviso "Cenários IPCC AR6 em desenvolvimento". Motivo: `CENARIOS_AR6` é
  NMGM (global) e a disciplina pede NMRM local — oferecer o global rotulado
  como cenário é o mesmo erro da regra 1. Níveis da turma e Manual são cotas
  declaradas, não projeções, então ficam. A aba **Matriz de cenários** e as
  linhas SSP da curva continuam (decisão do Helio, 04/09): quem chega lá já
  passou pelo aviso de procedência na aba Metadados. No modo local o seletor
  segue completo.
- **Modo web esconde o campo de caminho do MDE (v1.2).** Lá o raster é o
  `dados_web/` versionado junto com o app; expor o caminho só oferece um jeito
  de quebrar a página.
- **NÃO usar basemap da CARTO no mapa interativo.** Desde 2025 `dark_matter`
  e `positron` exigem API key e as tiles voltam carimbadas com
  "API KEY REQUIRED". Tentado e revertido na v1.2. O mapa fica com Esri World
  Imagery + OpenStreetMap.
- **Modo web NÃO trava mais a maré em NM (superada em 22/09/2026).** A trava
  da v1.2 existia só porque PM/PMS/HAT eram placeholder em 0,00 m — travar
  era melhor que oferecer um offset inventado. Essa razão não existe mais
  (ver decisão de maré acima): o seletor de datum tem efeito real nos dois
  modos agora. A tarja de aviso sobreviveu à v1.4 por outro motivo (modelo,
  não marégrafo) e saiu na v1.5 — ver "Tarja de maré sai da barra lateral".
- **Fundo cartográfico padrão = relevo sombreado (v1.2).** O hipsométrico
  vira opção secundária: em Caravelas ele gasta a faixa de cor toda nos
  primeiros metros e compete com a lâmina d'água.
- **Tema escuro (v1.2).** Dois níveis independentes: a APLICAÇÃO tem tema
  fixo em `.streamlit/config.toml` (`base = "dark"`, preto azulado #0B1220 /
  #15202B, destaque #1D9BF0); as FIGURAS têm toggle próprio na barra lateral,
  padrão escuro no modo web e claro no modo local. Regra: **o tema mexe só no
  papel da figura** (fundo, título, eixos, grade, créditos). As cores
  cartográficas — inundada, isolada, oceano — e o que é desenhado dentro do
  mapa (seta norte, barra de escala, legenda) NÃO mudam, porque carregam
  significado e precisam ser idênticas na tela e no relatório. Paletas em
  `core.CONFIG_TEMA`, acesso por `core.paleta(tema)`.
- **Exagero vertical ~50** no sombreamento — a planície é plana demais para
  hillshade sem exagero.
- **Mapa interativo é a aba PRINCIPAL (v1.3).** A figura de 300 dpi passa a ser a
  segunda aba. A pergunta da disciplina é "onde", e "onde" só fecha com base
  cartográfica real embaixo; a figura continua sendo o produto do relatório.
- **Topografia do mapa interativo é gerada do PRÓPRIO FABDEM (v1.3).** Camada
  hipsométrica em 11 faixas (`mapa_web.CONFIG_TOPO`) mais isolinhas de
  0,5 / 1 / 2 / 3 / 5 / 10 m em GeoJSON. Nenhum basemap topográfico de terceiros
  (OpenTopoMap, Terrarium, Terrain-RGB): regra 2. O relevo exibido é, por
  construção, o mesmo que a simulação corta. As isolinhas passam por suavização
  gaussiana, subamostragem 3x e Douglas-Peucker de 45 m — são **guia de leitura**;
  a cota que vale é a do clique, que lê o pixel sem interpolar.
- **Clique no mapa abre um popup no ponto (v1.3.1).** Coordenada, cota FABDEM,
  faixa hipsométrica, situação na cota do cenário, folga em metros até alagar e
  classe do MapBiomas — no balão sobre o ponto e, repetido, nas métricas abaixo
  do mapa (mesma função `_leitura_ponto`, para os dois nunca divergirem).
  `st_folium(returned_objects=["last_clicked"])`: clique rerroda o script, pan e
  hover não. O ponto vive em `st.session_state[CHAVE_PONTO]` porque o marcador
  precisa existir no `folium.Map` **antes** da renderização, e o retorno do
  clique só chega depois — daí o clique guardar e disparar `st.rerun()`, com
  comparação de coordenada para não entrar em rerun infinito.
- **Popup sobre manguezal avisa do viés de dossel (v1.3.1).** Quem clica no
  mangue e lê 4,3 m precisa saber que aquilo é limite superior, não cota do solo.
  A lista de classes com esse aviso é `cobertura.CONFIG_COBERTURA["codigos_alerta_dossel"]`.
- **Cota sob o cursor (hover) não foi implementada** e não deve ser: exigiria
  mandar a grade inteira (~5 M px) para o navegador. A leitura contínua que
  existe é o tooltip das isolinhas; o resto é por clique.
- **Cobertura MapBiomas é camada VISUAL na v1.3.** Não entra em nenhuma conta. O
  cruzamento com a máscara de inundação é a Parte 2 e depende das decisões
  ecológicas ainda em aberto (ver `docs/validacao_mapbiomas_laudo.md` §6).
- **Tamanho dos mapas controlado pelo usuário (v1.3).** O recorte é quase quadrado
  (65,8 x 69,8 km), então figura em largura cheia não cabe na tela. A altura do mapa
  interativo (padrão 620 px) e a largura da figura estática (padrão 58 %) são
  controles da barra lateral; `figsize` caiu de (10, 8) para (8, 7).
- **Faxina e reorganização pré-v2.0 (24/09/2026).** (1) O trabalho de 22–24/09
  foi commitado em 5 commits temáticos (o commit "Motor e interface" é misto por
  arquivo: `slr_core.py`, `02` e `config.py` carregam as três frentes). (2) A pasta
  manual `_backup_24set_pre_reversao/` virou o branch
  **`experimento-v2.0-limite-turma`** (limite único da turma + recorte de relato;
  parado e guardado) e foi apagada depois de conferir que nenhum arquivo ficou
  fora do git. Nesse experimento a união das UCs com `area_turma` devolve
  `area_turma` inalterada — o ganho era só de apresentação — e o recorte deixava
  de fora só ~2,5 % da terra (faixa oeste, Barreiras), sem mudar a área inundada.
  (3) **Os dados vivem em `NMRM_DIR_DADOS` (`C:\dados_nmrm`), não em `dados/`**;
  o MapBiomas nacional e `ucs_regiao.geojson` foram movidos para
  `C:\dados_nmrm\auxiliar\` e a árvore `dados/` do repositório foi removida
  (o `.gitignore` mantém `dados/` como rede de segurança). (4) O `04` deixou de
  varrer uma lista de candidatos (que incluía caminho literal do OneDrive) e
  resolve só `DIR_AUXILIAR / config.ARQ_MAPBIOMAS_NACIONAL`, com erro claro se
  ausente — única edição de lógica desta faxina; saída verificada (pixels de
  `cobertura_web.tif` idênticos, só a tag `gerado_em` muda). (5) Removidos de
  `saidas/`, `__pycache__/` e da raiz: logs, previews e comparações órfãs,
  `dem_teste.tif` (resíduo de nome antigo do `teste_sintetico.py`) e duplicatas
  byte a byte de 26/08 × 15–16/09 (mantida a data mais antiga do par).
  `abrir_tiff_mapbiomas.py` foi POUPADO de propósito (nunca versionado; remoção
  seria irreversível). (6) `08_prepara_camadas_turma.py` + `requirements-geracao.txt`
  dão proveniência a `ucs_turma.geojson` (§4).
- **Topografia e isolinhas vêm desligadas por padrão (16/09/2026).** Os dois
  toggles da seção "5 · Camadas do mapa interativo" abrem em `value=False`;
  Exposição ao NMRM continua ligada por padrão. Motivo: são as duas camadas
  mais pesadas para o navegador (overlay reprojetado + GeoJSON de isolinhas) e,
  na v1.3, opcionais para a leitura principal do mapa — o usuário liga quando
  quiser. O usuário continua podendo ativá-las manualmente; a lógica de
  renderização e os dados não mudaram.
- **O "Modo de uso" passa a decidir a ÁREA analisada (v1.5, 24/09/2026).**
  Antes ele só trocava valores padrão de cenário e de camadas. Agora carrega
  também `recorte_padrao`: no modo **Turma**, a análise é recortada à **área de
  estudo que a turma desenhou no QGIS** (`limite_turma.geojson`, convertido do
  shapefile versionado — traçado sobre a isóbata de 500 m e as UCs APA Ponta da
  Baleia/Abrolhos, RESEX Cassurubá e PARNA Marinho dos Abrolhos); no modo
  **Livre**, segue valendo o domínio inteiro do MDE, como em todas as versões
  anteriores. Isso REVISA a decisão de 22/09 (que deixava a área da turma como
  camada puramente vetorial), mas NÃO revisa o motivo dela: `BBOX_WGS84`
  continua sendo o domínio de leitura do raster nos dois modos, porque o FABDEM
  não cobre o banco dos Abrolhos. Consequências assumidas, todas declaradas na
  interface: (1) **o recorte é de RELATO, não de cálculo** — a conectividade
  hidráulica é resolvida antes, no domínio inteiro, e o polígono entra depois,
  na contagem, no desenho e no GeoTIFF; recortar antes do flood-fill cortaria
  caminhos de água que entram pela borda e inventaria depressões "isoladas" que
  não são (não inverter essa ordem numa refatoração); (2) os km² do modo Turma
  são a TERRA da área de estudo coberta pelo MDE — 450,5 km², não os ~16.255 km²
  de extensão do polígono, cuja maior parte é plataforma sem FABDEM; (3) fica de
  fora a planície continental a oeste, que o modo Livre conta: o recorte tem
  18,5 % da terra e captura 87–89 % da inundação a +1 e +2 m, então o que sai é
  terreno alto que não alaga. A porcentagem para de ser diluída — a +2,00 m,
  1,09 % do domínio vira 5,11 % da área de estudo, descrevendo os MESMOS 23 km²
  alagados. O limite usa a cor de borda do .qlr do QGIS (`#232323`), a mesma
  linha na tela, no relatório e no projeto do QGIS. O controle "Recortar à área da turma" fica visível nos dois
  modos: o modo define o padrão, não tranca (mesma regra das outras chaves de
  `CONFIG_MODOS`). Sem `limite_turma.geojson` o controle é desabilitado e o
  app roda sem recorte — nunca exceção.
- **Tarja de maré sai da barra lateral (v1.5, 24/09/2026).** O
  `st.sidebar.warning` permanente que a v1.4 pendurou na seção "2 ·
  Empilhamento de maré" ("Maré de modelo global, não medição…") foi removido a
  pedido do Helio. O que ele dizia NÃO virou opcional: a procedência completa
  — fonte, referência vertical, ressalva do JSON, ponto usado, distância do
  alvo e constituintes — segue declarada na aba **Metadados** ("Procedência da
  maré"), visível nos dois modos de uso, e na aba 📚 Turma ("O que esta
  ferramenta NÃO diz"). `core.NIVEIS_MARE["MEDIDA"]` segue `False`: mudou onde
  se avisa, não o que o dado é. Regra 3 continua valendo — se um dia a
  procedência sair da aba Metadados, a tarja precisa voltar para a barra
  lateral.

- **O recorte do modo Turma é DURO, em tudo (24/09/2026).** Decisão pedida
  depois de ver a primeira versão: no modo Turma a ferramenta mostra e conta
  **só o que está dentro da área de estudo**, sem fantasma do lado de fora.
  O que isso tocou, item por item: (1) na figura, `alpha_fora_recorte` passou
  de 0,25 para **0,0** — o terreno de fora não é desenhado, e o item de legenda
  "Terreno fora da área da turma" só reaparece se alguém puser esse alpha acima
  de zero de novo; (2) o FUNDO do eixo deixa de ser `cor_oceano` quando há
  recorte, senão a planície continental de fora apareceria pintada de azul e
  terra alta lida como mar é o pior erro possível neste mapa — o oceano virou
  camada desenhada só DENTRO do recorte, e o de fora é o papel da figura;
  (3) a escala do hipsométrico (`nanpercentile` 99,5) passou a ser calculada só
  sobre o que está dentro, senão o platô do Barreiras seguiria esticando a
  rampa de cor de um terreno que nem aparece; (4) no mapa interativo, a camada
  topográfica, as isolinhas e a cobertura MapBiomas passaram a ser recortadas
  também — antes vinham do domínio inteiro e desenhavam relevo que não entra em
  conta nenhuma (a exposição já era recortada); (5) nas isolinhas a ORDEM
  importa: o NaN do recorte entra DEPOIS do preenchimento de oceano e DEPOIS da
  suavização — antes do preenchimento, a borda do corte viraria uma isolinha de
  0,5 m falsa; antes da suavização, o gaussiano espalharia NaN e comeria
  isolinha boa lá dentro; (6) clique fora do recorte não devolve mais cota,
  faixa nem classe de cobertura: devolve "fora da área de estudo", no balão e
  nas métricas, porque mostrar "3,4 m, acima da cota" num pixel que não entra
  em conta nenhuma convida a ler aquilo como resultado. Os NÚMEROS não mudaram
  com nada disso (450,5 km² de terra, 23,02 km² inundados a +2,00 m): o recorte
  já valia na contagem desde a primeira versão — o que mudou foi o desenho.
- **Paleolinhas de costa: entrada é LINHA, polígono é derivado (v2.1 preliminar,
  24/09/2026 — SUPERADO em 01/10/2026, ver item abaixo).**
  A reconstrução paleoambiental de Andrade et al. (2003) entra pelas Figs. 9 a 15,
  georreferenciadas no QGIS e digitalizadas à mão. A camada de origem
  (`dados_web/fonte_paleolinhas/paleolinhas.shp`) guarda apenas a LINHA de costa
  de cada estágio, com o campo `estagio` (I a VII); `10_paleolinhas.py` fecha o
  polígono de terra emersa contra o quadro da figura e grava
  `dados_web/paleolinhas_turma.geojson`. Motivo de não digitalizar polígono: o
  contorno fechado obrigaria a redesenhar a moldura do quadro a cada uma das sete
  figuras, e a diferença de área ENTRE estágios — que é o que a comparação mede —
  passaria a conter erro de moldura. Com linha, a moldura é idêntica por
  construção. O fechamento usa `polygonize` mais uma ÂNCORA DO CONTINENTE no canto
  noroeste (`CONFIG_PALEO["ancora_continente"]`); ilhas destacadas, como a
  ilha-barreira do Estágio II, entram por ponto-semente. A regra anterior ("terra
  = peça que encosta na borda oeste") foi descartada: quando a paleolinha sai pela
  própria borda oeste ela parte essa borda em dois trechos, as duas peças passam a
  encostar nela e o script devolvia o quadro inteiro como terra. Três verificações
  param o script em vez de gravar número errado em silêncio: soma das peças igual à
  área do quadro, terra acima de 98 % do quadro, e linha que não atravessa o quadro.
- **Paleolinhas da turma: um shapefile por estágio, fechamento por 2-coloração
  (v2.1, 01/10/2026).** SUPERA a entrada e o fechamento descritos no item
  anterior (o item "v2.1 preliminar" acima). A turma digitalizou os sete
  estágios (Figs. 9 a 15), um shapefile de
  LINHAS por estágio em `dados_web/fonte_paleolinhas/estagios/estagio_<N>.shp`;
  o estágio sai do nome do arquivo e o `paleolinhas.shp` da v2.1 preliminar
  (só Estágio I) foi descartado. Convenção: **toda linha é fronteira terra/água** (costa,
  margem de laguna, contorno de ilha, margem de canal). `10_paleolinhas.py`
  (1) descarta o traçado a menos de ~220 m da borda (moldura redesenhada) e usa
  o quadro exato; (2) prolonga pontas junto à borda, costura frestas de até
  ~440 m e fecha anéis quase fechados; (3) `polygonize`; (4) classifica por
  2-coloração a partir de UMA semente de mar (`ponto_mar`, mar aberto a leste) —
  atravessar uma linha troca a classe, então ilha em laguna em continente sai
  certa sem ponto-semente; lascas < 0,05 km² herdam a vizinha de maior
  fronteira; (5) PARA se o `ponto_continente` (Barreiras) sair mar, se houver
  conflito de classe entre peças grandes, ou se as peças não reconstituírem o
  quadro. Resultado (km² esféricos no quadro): I 1.122 · II 916 · III 931 ·
  IV 1.301 · V 1.333 · VI 1.359 · VII 1.383. O Estágio I da turma difere 2 % do
  traçado anterior (1.144). Validação visual em
  `docs/validacao_paleolinhas_estagios.png`. Os `.points` de todas as figuras
  estão versionados em `georref/`; os GeoTIFF não. **O Estágio VII é quaternário, não a costa atual (correção de
  01/10/2026):** é a "Retomada da progradação" do Holoceno tardio
  (< 1.300 cal AP, `nmrm_m = None`); a primeira versão da v2.1 (01/10/2026,
  antes da correção) o tratou como costa atual e conferência cruzada do
  FABDEM — errado, removido. Metadados dos
  sete estágios (título, período, idade, descrição, nível do mar) revisados
  contra o §VII e as legendas do artigo; idade do I corrigida para "após
  120.000 AP", do VI para "≤ 1.300 cal AP" (1.290 é idade máxima). A aba Paleoambiente ganhou a tabela "Todos os estágios"
  (`paleo.tabela_estagios`, mesma régua de pixel).
- **O quadro das paleolinhas é o das figuras, não o BBOX do projeto (v2.1).**
  39°30'–39°00'W x 17°30'–18°00'S, idêntico nas sete figuras, MENOR que
  `config.BBOX_WGS84`. Fora dele o artigo não desenhou nada, então a camada paleo
  não afirma nada. Comparação com hoje é feita dentro desse mesmo quadro.
- **É RECONSTRUÇÃO, não simulação (v2.1).** Os polígonos são redesenho de figura
  publicada, com erro posicional da ordem de CENTENAS DE METROS (figura de 2003
  escaneada, 4 pontos de controle). Servem para comparar estágios entre si, onde o
  erro é em boa parte sistemático; NÃO são medida absoluta e a interface arredonda
  para km² inteiro. A palavra "simulação" não deve ser usada para esta camada — o
  que o motor simula é exposição a cota, que é outra coisa. E cortar o FABDEM
  MODERNO numa paleocota não reconstrói paleogeografia: o terreno de hoje é
  produto daquele nível do mar, não seu contemporâneo.
- **Georreferenciamento validado contra o FABDEM (24/09/2026).** A costa atual
  derivada do FABDEM cai sobre a linha "present day coastline" que o próprio artigo
  desenha na Fig. 9, ao longo de ~60 km (Ponta da Baleia, reentrância, Ponta do
  Catoeiro) — ver `docs/validacao_georref_fig9.png`. Repetir esse teste a cada
  figura nova: é barato e pega erro de warp antes da digitalização.

- **Redesign em páginas (v3.0, 02/10/2026).** A barra lateral de seis seções e
  as oito abas viraram cinco páginas com `st.navigation(position="top")`:
  **Simulador** (público), **Turma**, **Paleoambiente**, **Exposição e cenários**
  (curva + matriz juntas) e **Metadados**. Inspirado no visual de
  runcell.dev (sea level rise simulator); mockup aprovado no canvas "Simulador
  NMRM Caravelas — redesign". Decisões: (1) **por que páginas** — o Streamlit
  executa todas as abas a cada interação; com páginas só a aberta roda (pico
  de memória da página Simulador caiu de ~1,1–1,5 GB para ~0,43 GB); (2) a
  figura de 300 dpi é **gerada sob demanda** (botão "Gerar figura" + "Baixar
  PNG", com prévia), nunca a cada rerun; (3) Simulador e Turma são a MESMA
  função (`pagina_simulador(perfil)`, `CONFIG_PERFIS`), herdeira do "Modo de
  uso": o perfil define o padrão, **não tranca** (decisão mantida em 02/10);
  cada perfil guarda seus valores (chaves `w_*_{perfil}`, persistidas entre
  páginas por `_manter_estado`); (4) controles num cartão à esquerda do mapa;
  o que não é essencial (sobrelevação, regra hidrológica, área mínima,
  cartografia da figura, tamanho do mapa) foi para o popover "Ajustes
  avançados"; (5) as páginas Exposição e Metadados usam o último cenário
  simulado (`st.session_state[CHAVE_ESTADO]`); a Exposição mostra as curvas do
  domínio inteiro e da área da turma juntas; (6) tema em `.streamlit/config.toml`
  (Rubik no texto, IBM Plex Mono nos números, cantos "large"); CSS próprio
  mínimo, só em classes `nmrm-*`; (7) a aba "📚 Turma" virou a seção "Análises
  da disciplina" da página Turma; (8) "Depressões sem conexão" desligado agora
  some também do mapa interativo, não só da figura; (9) o GeoTIFF classificado
  só é oferecido no modo local (no Cloud ele seria gravado no servidor).
- **Cenários IPCC AR6 de volta ao modo web, rotulados como GLOBAIS (02/10/2026).**
  SUPERA "Modo web esconde o cenário IPCC AR6 (v1.2)". Decisão do Helio: as
  duas páginas de simulador oferecem o AR6 (Público: Manual | AR6; Turma:
  Níveis da turma | Manual | AR6), sempre com a tarja "Nível médio GLOBAL
  (NMGM), não o relativo local de Caravelas" e o sufixo "(NMGM)" no rótulo do
  cenário. A regra 1 continua valendo — o número global não pode ser
  apresentado como local; o que mudou é que ele aparece declarado como global.
  Pendente: trocar pelos valores regionais (Garner et al., Zenodo
  10.5281/zenodo.5914709, ponto em frente a Caravelas).

- **As UCs abrem DESLIGADAS nos dois modos (24/09/2026).** `ucs_ligadas` saiu
  de dentro de `camadas_turma_ligadas` e virou chave própria em `CONFIG_MODOS`.
  Motivo: com o recorte, o limite da área de estudo já é a linha que importa, e
  as três UCs preenchidas por cima disputam a leitura da lâmina d'água bem no
  estuário, que é onde a inundação acontece. Continuam a um clique, nos dois
  modos.

- **A figura enquadra a ÁREA DE ESTUDO INTEIRA, não a grade do MDE
  (24/09/2026).** Duas coisas mudaram juntas, e as duas vêm do mesmo lugar: a
  figura era desenhada em coordenadas de PIXEL da grade do FABDEM, então não
  conseguia mostrar nada fora dela. (1) O mar dentro do recorte era pintado com
  um `imshow` sobre a grade, e parava na borda dela — um **retângulo azul de
  canto reto** com cara de dado. Agora é um `PathPatch` do próprio polígono da
  área de estudo: o mar termina exatamente onde o traçado termina. (2) O
  enquadramento vinha do bbox da máscara RASTERIZADA, que é recortada pela
  grade; agora vem do bbox do POLÍGONO, via `_bbox_pixel_geojson`. Isso funciona
  porque geo->pixel é uma afim, e ela continua valendo fora do raster — as
  coordenadas de pixel simplesmente ficam negativas ou maiores que a grade.
  O quadro passou de 2.195 px de largura para ~8.250, de -39,49° a -37,24°.
  Três ajustes vieram junto: a figura é **reproporcionada** ao quadro mantendo
  a mesma área em polegadas (`aspecto_max = 2.4`), senão o eixo virava uma tira
  no meio da página; a **barra de escala** passou a escolher um valor redondo
  da série 1-2-5 proporcional à largura (50 km na área inteira, 10 km na
  planície) em vez de 5 km fixos; e a **legenda** sai do mapa para uma faixa
  abaixo dele quando o quadro é largo, porque no canto inferior direito ela
  cobria justamente o traçado do limite. **Consequência a encarar:** a planície
  de Caravelas ocupa ~8 % da largura desse quadro: o mapa passou a mostrar a
  área de estudo como ela é — quase toda plataforma continental —, e a leitura
  fina de exposição ficou pequena. Por isso o enquadramento virou **escolha do
  usuário**, não decisão fixa: o parâmetro `enquadramento` de `figura_mapa`
  aceita `"area_estudo"` (o polígono inteiro) e `"planicie"` (o bbox da máscara
  rasterizada, ou seja, a parte com MDE — é onde a exposição acontece), com um
  seletor na barra lateral, padrão em `"planicie"` e desabilitado sem recorte.
  **Enquadramento não é recorte:** os dois contam exatamente os mesmos km², só
  muda o que entra no quadro. Para o relatório, as duas figuras juntas contam a
  história inteira — visão geral e detalhe.

## 6. Estado atual

> **Nomenclatura:** as tags publicadas são v1.0 … v1.3, v2.0, v2.1 e agora **v3.0**.
> Os marcos internos v1.4 (maré TPXO, modos Turma/Livre, camadas da turma) e
> v1.5 (recorte à área de estudo, figura recortada, retirada da tarja de maré)
> nunca foram publicados sozinhos — saíram juntos na v2.0. As marcações "v1.4"
> e "v1.5" espalhadas pelo código e por este arquivo são DATAS de decisão, não
> releases; ficam como estão porque é assim que se sabe quando cada coisa foi
> decidida.
>
> **v2.1 é PUBLICADA** (01/10/2026) — Paleoambiente de Caravelas, os sete
> estágios de Andrade et al. (2003). Houve uma versão preliminar da v2.1
> (24/09/2026, só Estágio I) que nunca foi publicada sozinha — tag local
> `v2.1` apontando para ela, sem push nem release no GitHub — e foi SUPERADA
> em 01/10/2026 antes de qualquer tag ou release sair (ver §5, "Paleolinhas
> de costa… v2.1 preliminar… SUPERADO"). A tag `v2.1` publicada aponta para o
> commit da versão de sete estágios, não para a preliminar.
>
> **v3.0 é PUBLICADA** (02/10/2026) — redesign em cinco páginas, cenários AR6
> liberados como nível global e a correção de memória da figura do
> paleoambiente (commit 4a7ee4a, que saiu depois da tag v2.1). Major porque a
> interface mudou inteira: abas e barra lateral deram lugar a páginas.

- [x] `01_mapa_elevacao.py` — mosaico FABDEM, recorte, reprojeção, máscara de
      oceano, mapa hipsométrico sombreado, curva hipsométrica, tabela altimétrica.
- [x] `slr_core.py` — cota composta, máscara com conectividade, estatísticas de
      área, matriz de cenários, curva de exposição, export PNG/GeoTIFF/CSV.
- [x] `02_simulador_nmrm.py` — interface Streamlit.
- [x] **v1.2** — Manual até +10 m com aviso de extrapolação; maré travada em
      NM no modo web; relevo sombreado como fundo padrão; `help` explicativo
      na área mínima de mancha; procedência dos cenários AR6 e do nível médio
      declaradas na aba Metadados (`core.FONTE_CENARIOS`); tema escuro na
      aplicação e nas figuras (`core.CONFIG_TEMA`).
- [x] Ambiente VS Code reproduzível (config.py, requirements.txt, .vscode/).
- [x] **v1.3** — mapa interativo como aba principal; camada topográfica e isolinhas
      geradas do FABDEM; leitura de cota/cobertura no clique; camada MapBiomas
      Col. 11 (visual); controles de tamanho para o mapa caber numa tela;
      `04_prepara_cobertura.py` e `src/cobertura.py`; validação contra o laudo
      do Cassurubá documentada.
- [x] **v1.5** (24/09/2026) — o modo de uso decide a área analisada: modo Turma
      recorta à área de estudo que a turma desenhou no QGIS
      (`dados_web/fonte_limite_turma/*.shp` -> `09_limite_turma.py` ->
      `limite_turma.geojson`: 450,5 km² de terra, 18,5 % do domínio), modo Livre
      segue no domínio inteiro; recorte propagado para métricas, curva, matriz,
      aba Turma, mapa interativo (reenquadra), figura (esmaecimento +
      enquadramento + rodapé) e GeoTIFF (255 fora); tarja de maré removida da
      barra lateral (procedência segue na aba Metadados).
- [x] **v2.1** (01/10/2026, PUBLICADA) — Paleoambiente de Caravelas, os sete
      estágios de Andrade et al. (2003): `10_paleolinhas.py` lê um shapefile de
      linhas por estágio (`dados_web/fonte_paleolinhas/estagios/`) e fecha os
      polígonos de terra emersa por 2-coloração; `.points` + figuras
      georreferenciadas das Figs. 9–15 em `georref/`;
      `dados_web/paleolinhas_turma.geojson` com os 7 estágios. Nova aba
      "🕰️ Paleoambiente" no `02` (`src/paleo.py`): seletor de estágio,
      comparação com a terra emersa de hoje (FABDEM), tabela "Todos os
      estágios", figura de 300 dpi e metadados dos estágios revisados contra
      o artigo. Terra emersa por estágio (km², esféricos no quadro da figura):
      I 1.122 · II 916 · III 931 · IV 1.301 · V 1.333 · VI 1.359 · VII 1.383.
      Fechamento conferido e validação visual em
      `docs/validacao_paleolinhas_estagios.png`. Ver §5. Houve uma versão
      preliminar (24/09/2026, só Estágio I, 1.144 km² no quadro — marco
      interno, nunca publicado) que foi SUPERADA por esta antes de qualquer
      tag ou release sair.
- [x] **v3.0** (02/10/2026) — redesign em cinco páginas (`st.navigation`),
      controles ao lado do mapa, figura de 300 dpi sob demanda, tema Rubik,
      cenários AR6 liberados no modo web com rótulo de nível GLOBAL. Ver §5.
- [ ] Imagem de satélite de fundo (`contextily`, reprojeção para WebMercator).
- [ ] Solicitação ao BNDO e integração da maré com constante de marégrafo.
      Passo intermediário dado em 22/09/2026: `NIVEIS_MARE` passou a vir do
      TPXO9-atlas v5 (modelo, não medição — ver §5 e regras 7-8) enquanto o
      BNDO/CHM não responde.
- [ ] Tratar o viés de dossel sobre manguezal (ver regra 6) — bloqueia a Parte 2.
- [x] Faxina pré-v2.0 e proveniência de `ucs_turma.geojson` (24/09/2026, ver §5).
- [ ] Limites vetoriais da RESEX Cassurubá para trocar as faixas de latitude por setores reais.
- [ ] Cruzar as paleolinhas com o MapBiomas: idade do substrato sob cada
      ecossistema atual — é a ponte com a Parte 2.
- [ ] Parte 2 — resposta ecológica cruzando com MapBiomas.

## 7. Regras de conduta científica (não negociáveis)

1. **Nunca inventar valor de maré, datum ou projeção local.** Se o dado não
   chegou, manter `0.00` com um flag explícito e avisar na interface — nunca
   um número sem procedência. Os datums de maré passaram de placeholder
   (`PROVISORIO`) para o TPXO9-atlas v5 em 22/09/2026 (ver §5); o datum
   vertical do MDE (`OFFSET_GEOIDE_NM_M`) segue `0.00` pelo mesmo motivo
   original — o dado real (CMEMS/DTU ou nivelamento a marégrafo) ainda não
   chegou. Número inventado em mapa vira citação em relatório.
2. **Não trocar o FABDEM por SRTM, Terrarium ou tiles Terrain-RGB genéricos.**
   Em planície com manguezal o viés de dossel é maior que o próprio sinal
   de NMRM simulado.
3. **Todo produto deve declarar suas limitações** — o rodapé da figura e a
   aba de metadados não são decorativos.
4. Distinguir sempre **NMGM** (média global) de **NMRM** (relativo local).
5. A saída é **exposição potencial**, não previsão de inundação real:
   não resolve hidrodinâmica, atenuação de maré no estuário, ondas, drenagem
   nem resposta morfodinâmica (acresção de manguezal, migração de duna).
6. **Não reportar área de manguezal perdida por cenário** enquanto o viés de dossel
   não for tratado. Medido em 05/09/2026 cruzando FABDEM x MapBiomas: mangue com
   cota mediana de 4,31 m contra apicum de 1,91 m — ordem invertida em relação à
   zonação de maré, resíduo de dossel da ordem de 3 m, maior que todo o NMRM
   projetado para 2100. O manguezal sai artificialmente seguro. O apicum, sem
   dossel, é o controle interno e responde como esperado (56 % abaixo de +2 m).
   Detalhes em `docs/validacao_mapbiomas_laudo.md` §4.4.
7. **A maré do TPXO não resolve o estuário (22/09/2026).** Os datums de
   `NIVEIS_MARE` valem AO LARGO da barra — célula de ~3,7 km do
   TPXO9-atlas v5 (OSU). Amplificação e defasagem de maré DENTRO dos canais
   do estuário Caravelas–Peruípe não estão representadas. Isto é o mesmo
   limite já declarado na regra 5 ("não resolve... atenuação de maré no
   estuário"), agora com número: a célula do modelo, não só a ausência de
   hidrodinâmica.
8. **A troca de maré NÃO resolve o datum vertical (22/09/2026).**
   EGM2008 x nível médio local segue em aberto; `OFFSET_GEOIDE_NM_M` segue
   `0.00`. São dois problemas independentes — maré (regra 7) e datum
   vertical do MDE (este) — e ninguém deve ler o primeiro como resolvido por
   causa do segundo.
