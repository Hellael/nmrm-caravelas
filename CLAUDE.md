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
├── docs/
│   ├── logica_da_ferramenta.md        # como a ferramenta raciocina, ponta a ponta
│   ├── diagnostico_zeros.md           # investigação dos 0,0 m suspeitos no FABDEM
│   └── validacao_mapbiomas_laudo.md   # validação da cobertura contra o laudo
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
- **Máscara de água classificada na grade nativa, ANTES da reprojeção (22/09/2026).** `01_mapa_elevacao.py`: `classificar_agua()` testa `dem==0.0` no mosaico bruto (WGS84, ~30 m) e `reprojetar()` leva essa máscara para a grade UTM com `nearest` — separado da elevação, que continua reprojetada com `bilinear`. Corrige a causa raiz de rios/canais estreitos não entrarem na grade de conectividade: testar `dem==0.0` DEPOIS do bilinear (como antes) borra o 0,0 exato em qualquer canal mais estreito que a vizinhança do reamostrador. Efeito colateral relevante, não um bug: pixels de rio que antes vazavam para "terra de baixa cota" (e inflavam bathtub/conectado) agora são excluídos corretamente como água preexistente — os valores de referência antigos (4,33 / 7,00 / 27,84 km² em +0,5 / +1,0 / +2,0 m) caem para 0,64 / 1,28 / 19,07 km² e ficam OBSOLETOS; recalculados em `dados_web/metadados_web.json` (rodado com os tiles reais em 22/09). **Atualizar** `docs/logica_da_ferramenta.md`, README e qualquer relatório que cite os números antigos. `diagnostico_zeros.py` e `histograma_cauda_costeira.py` foram ajustados para a nova assinatura de `reprojetar()`.

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
- [ ] Imagem de satélite de fundo (`contextily`, reprojeção para WebMercator).
- [ ] Solicitação ao BNDO e integração da maré.
- [ ] Tratar o viés de dossel sobre manguezal (ver regra 6) — bloqueia a Parte 2.
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
