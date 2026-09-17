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
├── requirements.txt
├── .gitignore                 # ignorar dados/ e saidas/
├── config.py                  # caminhos, bbox, CRS — fonte única
├── .vscode/                    # launch.json + settings.json
├── src/
│   ├── __init__.py
│   ├── slr_core.py            # MOTOR — sem interface, toda a ciência
│   ├── fonte_dados.py         # resolve modo local x web; leitura tolerante
│   ├── mapa_web.py            # camadas do mapa interativo (overlays, isolinhas)
│   └── cobertura.py           # legenda MapBiomas Col. 11 + leitura do recorte
├── 01_mapa_elevacao.py        # mosaico/recorte/reprojeção FABDEM + mapa base
├── 02_simulador_nmrm.py       # interface Streamlit sobre slr_core
├── 03_prepara_dem_web.py      # dados leves + limiar de conexão pré-computado
├── 04_prepara_cobertura.py    # recorte do MapBiomas alinhado à grade do projeto
├── 05_valida_cobertura_elevacao.py  # cobertura x elevação (FABDEM completo): percentis,
│                                    # fração abaixo de cota, adjacência, distância ao mangue
├── teste_sintetico.py         # valida o pipeline sem precisar do FABDEM
├── teste_conectividade.py     # v1.4: máscara de água na grade nativa + canais MapBiomas
├── docs/
│   ├── logica_da_ferramenta.md        # como a ferramenta raciocina, ponta a ponta
│   ├── diagnostico_zeros.md           # investigação dos 0,0 m suspeitos no FABDEM
│   ├── validacao_mapbiomas_laudo.md   # validação da cobertura contra o laudo
│   └── v1.4_notas_tecnicas.md         # máscara de água (área x conexão) + canais MapBiomas
├── dados/                     # entradas (NÃO versionar — FABDEM é CC BY-NC-SA)
│   ├── fabdem/                # tiles brutos .tif
│   ├── auxiliar/              # MapBiomas recortado, GEBCO, maregrafia
│   └── processado/            # caravelas_fabdem_utm24s_30m.tif
├── dados_web/                 # dados leves VERSIONADOS (dem, água, limiar, cobertura)
└── saidas/                    # PNG, GeoTIFF, CSV (NÃO versionar)
```

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
| **MapBiomas Col. 11 (2025)** | Cobertura do solo | `brazil_coverage-col11_2025.tif` (nacional, 728 MB, uint8, EPSG:4326). Recortado por `04_prepara_cobertura.py`, reamostragem **nearest** (categórico), alinhado pixel a pixel à grade do MDE. Legenda (código, nome, cor) transcrita do CSV oficial da Coleção 11 e conferida em set/2026 para os **17 códigos presentes** no recorte — os demais não foram transcritos e a interface os mostra como "fora da legenda conferida". Na v1.3 a camada é **apenas visual**. |
| **BNDO/CHM · FEMAR** | Constantes harmônicas e datums de maré | `chm.bndo@marinha.mil.br`. **Ainda não solicitado.** Caminho crítico. |
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
- **Maré: adiada para a v2.** Offsets em `NIVEIS_MARE` estão em `0.00` com
  `PROVISORIO = True`. A v1 roda no nível médio.
- **O "nível médio" não é calculado, é herdado (v1.2 documentou isso).**
  O corte é feito em z = 0 m no datum do próprio FABDEM (geoide EGM2008),
  ou seja, assume-se `NM local ≈ geoide` com `OFFSET_GEOIDE_NM_M = 0.00`.
  A diferença real é a topografia dinâmica média (MDT), decimétrica no
  Atlântico Sul tropical — mesma ordem do NMRM de 2050. Nenhuma constante
  harmônica foi usada até aqui.
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
- **Modo web trava a maré em NM (v1.2).** Na ferramenta pública o seletor de
  datum aparece com PM/PMS/HAT visíveis porém desabilitados, com o aviso
  "Demais níveis de maré em desenvolvimento". No modo local segue editável,
  para testar assim que o BNDO/CHM responder.
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
- **Máscara de água detectada na grade nativa, com DUAS reamostragens — área
  e conexão (v1.4b).** Testar `dem==0.0` DEPOIS do bilinear (como a v1.3
  fazia) mistura o 0.0 da água com a cota da margem antes do teste — a
  máscara perdia ~1 px em toda margem e canais de 1–2 px de largura somiam
  por completo. Agora a água é detectada e zerada para NaN na grade WGS84,
  antes de qualquer reamostragem, e reprojetada DUAS vezes para propósitos
  diferentes: `agua_area` (`Resampling.average` sobre 0/1, limiar
  `>= 0,5` — só sai da terra o pixel cuja MAIORIA da área é água de
  verdade; é o que mascara o DEM e vira `config.MASCARA_AGUA`) e
  `agua_conexao` (`Resampling.max` — qualquer fração de água já conta para
  conexão). A diferença `agua_conexao & ~agua_area` é a MARGEM
  (`config.MASCARA_MARGEM`): fica como TERRA na área (cota real preservada),
  mas conduz conexão hidráulica — soma-se ao caminho por canal MapBiomas
  (mesmas regras, sem a salvaguarda de cota, porque é água real medida no
  próprio FABDEM). A etapa intermediária só com `Resampling.max` (v1.4a) foi
  descartada: tirava da conta de área todo pixel com qualquer fração de água
  real, mesmo sendo majoritariamente terra — ver `docs/v1.4_notas_tecnicas.md`
  §2 para o porquê e os números. Ganho medido em 16/09/2026: `agua_area`
  +10,76 km² (11.960 px), `agua_conexao` +23,43 km² (26.028 px), margem
  12,66 km² (14.068 px) — área emersa final: **2.429,4 km²**.
  **Cuidado ao reprojetar máscara categórica 0/1 com `rasterio.warp.reproject`:**
  passar `dst_nodata=0` junto com `src_nodata=None` corrompeu o resultado
  (quase 100% do destino virava "água" com `Resampling.max`/`average`/
  `nearest`) — bug real do par GDAL/rasterio 1.5.1 testado neste projeto, não
  suposição. Correção: não declarar `dst_nodata` nessas reprojeções (os
  arrays de destino já nascem zerados com `np.zeros`, que é o preenchimento
  correto fora do domínio). `teste_conectividade.py` cobre isso (casos 1 e 7).
- **Canais MapBiomas (classe 33) como caminho hidráulico, não fonte (v1.4b).**
  Um pixel de canal fora da máscara de água CONDUZ a água (entra no
  `candidato` do flood-fill) mas nunca a INJETA sozinho (nunca entra em
  `fonte`) — necessário porque a classe 33 também cobre lagoas interiores sem
  ligação com o mar, que virariam conexão falsa se fossem fonte. Só conta
  como caminho até `caminho_cota_max_m = 6.0` (teto dos terraços holocênicos
  de Andrade et al. 2003, o mesmo de `config.FAIXAS_ALTIMETRICAS`) — evita
  religar uma depressão distante através de um lago/rio alto no tabuleiro
  Barreiras. A margem d'água real (acima) soma-se por união a este caminho,
  mas é SEMPRE ativa — não depende do toggle "canais", que controla só a
  camada extra do MapBiomas. Controlado por `CONFIG_INUNDACAO["caminhos_canais"]`
  em `slr_core.py`; a interface tem um toggle próprio, ligado por padrão,
  desabilitado sem conectividade ou sem cobertura/raster de canais. Gera
  DOIS rasters de limiar no modo web (`limiar_conexao_web.tif` = margem
  sozinha, `limiar_conexao_canais_web.tif` = margem união canal) para a
  interface mostrar as duas áreas lado a lado. **Achado que parecia
  coincidência e não era:** a área isolada sai IDÊNTICA entre v1.4a e v1.4b
  em toda cota testada — não é porque as depressões isoladas ficam "longe"
  da correção; é porque todo pixel de margem abaixo da cota já encosta
  fisicamente na água (é a própria definição de margem) e por isso já
  conecta na hora, sem depender de qual das duas máscaras de área está em
  uso. A margem nunca alcança uma depressão interior isolada por um cordão —
  só estende a conexão um pixel além da água em si. Ver
  `docs/v1.4_notas_tecnicas.md`.
- **Tamanho dos mapas controlado pelo usuário (v1.3).** O recorte é quase quadrado
  (65,8 x 69,8 km), então figura em largura cheia não cabe na tela. A altura do mapa
  interativo (padrão 620 px) e a largura da figura estática (padrão 58 %) são
  controles da barra lateral; `figsize` caiu de (10, 8) para (8, 7).
- **Topografia e isolinhas vêm desligadas por padrão (16/09/2026).** Os dois
  toggles da seção "5 · Camadas do mapa interativo" abrem em `value=False`;
  Exposição ao NMRM continua ligada por padrão. Motivo: são as duas camadas
  mais pesadas para o navegador (overlay reprojetado + GeoJSON de isolinhas) e,
  na v1.3, opcionais para a leitura principal do mapa — o usuário liga quando
  quiser. O usuário continua podendo ativá-las manualmente; a lógica de
  renderização e os dados não mudaram.

## 6. Estado atual

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
- [x] **v1.4b** — máscara de água detectada na grade nativa (WGS84) antes da
      reprojeção (corrige o bug de bilinear misturando o 0,0 da água na cota
      da margem e apagando canais de 1–2 px), reprojetada em DUAS versões —
      `agua_area` (`Resampling.average` ≥ 0,5, decide o que sai da terra) e
      `agua_conexao` (`Resampling.max`, decide o que conduz conexão); a
      diferença é a MARGEM d'água real, que fica terra mas conduz. Canais
      MapBiomas (classe 33) continuam funcionando como caminho hidráulico —
      conduzem, não injetam água — até +6,0 m de cota, somados à margem por
      união; toggle próprio na interface e dois rasters de limiar no modo web
      (`limiar_conexao_web.tif` = margem sozinha, `limiar_conexao_canais_web.tif`
      = margem + canal). Área emersa final: 2.429,4 km². `teste_conectividade.py`
      (7 casos). Ver `docs/v1.4_notas_tecnicas.md` — inclui a v1.4a
      (só `Resampling.max`) como etapa intermediária descartada.
- [ ] Imagem de satélite de fundo (`contextily`, reprojeção para WebMercator).
- [ ] Solicitação ao BNDO e integração da maré.
- [ ] Tratar o viés de dossel sobre manguezal (ver regra 6) — bloqueia a Parte 2.
- [ ] Tratar o degrau de dossel de mata ciliar/mangue nas margens de canal —
      não entrou no escopo da v1.4 (decisão: descartado nesta versão; ver
      `docs/v1.4_notas_tecnicas.md`).
- [ ] Limites vetoriais da RESEX Cassurubá para trocar as faixas de latitude por setores reais.
- [ ] Parte 2 — resposta ecológica cruzando com MapBiomas.

## 7. Regras de conduta científica (não negociáveis)

1. **Nunca inventar valor de maré, datum ou projeção local.** Se o dado não
   chegou, manter `0.00` com flag `PROVISORIO` e avisar na interface.
   Número inventado em mapa vira citação em relatório.
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
