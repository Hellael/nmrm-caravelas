# Simulador de exposição ao NMRM — Caravelas (BA)

Disciplina **Ecossistemas Marinhos Costeiros** — UERJ / FAOC / DOB
(Prof. Filipe Chaves), semestre 2026.2.

**Pergunta do semestre:** como a elevação do Nível Médio Relativo do Mar
(NMRM) poderá reorganizar os ecossistemas costeiros da planície de Caravelas,
extremo sul da Bahia, e quais consequências ecológicas e sociais emergem
dessa transformação?

## O que a ferramenta faz

Ferramenta geoespacial interativa e parametrizada de **exposição potencial**
ao NMRM sobre a planície costeira de Caravelas. A partir do Modelo Digital de
Elevação FABDEM V1-2 (~30 m), ela recorta, reprojeta e mascara o oceano,
depois aplica uma cota de inundação composta (cenário IPCC AR6 + nível de
sensibilidade) e classifica o terreno em **terra seca**, **inundada** (com
caminho hidráulico até o mar) e **isolada** (abaixo da cota mas sem conexão).
O teste de **conectividade hidráulica** — ligado por padrão — é o principal
diferencial frente aos simuladores online, que costumam somar como inundada
qualquer depressão abaixo da cota. A saída inclui mapa hipsométrico sombreado,
curva hipsométrica, curva de exposição área × cota, matriz de cenários e
exports carimbados (PNG / GeoTIFF / CSV).

A saída é **exposição potencial, não previsão de inundação real**: não resolve
hidrodinâmica, atenuação de maré no estuário, ondas, drenagem nem resposta
morfodinâmica (acresção de manguezal, migração de duna).

## Estrutura de pastas

```
nmrm-caravelas/
├── CLAUDE.md                  # memória do projeto entre sessões
├── README.md
├── LICENSE                    # CC BY-NC-SA 4.0
├── requirements.txt           # pisos de versão para o Streamlit Cloud
├── .gitignore                 # ignora dados/ e saidas/ (dados_web/ é versionado)
├── .streamlit/config.toml     # tema e limites do app publicado
├── config.py                  # caminhos, bbox, CRS — fonte única
├── .vscode/                   # launch.json + settings.json
├── src/
│   ├── __init__.py
│   ├── slr_core.py            # MOTOR — sem interface, toda a ciência
│   ├── fonte_dados.py         # decide modo local x web, lê MDE e limiar
│   ├── mapa_web.py            # camadas do mapa interativo (overlays, isolinhas)
│   └── cobertura.py           # legenda MapBiomas Col. 11 + leitura do recorte
├── 01_mapa_elevacao.py        # mosaico/recorte/reprojeção FABDEM + mapa base
├── 02_simulador_nmrm.py       # interface Streamlit sobre slr_core
├── 03_prepara_dem_web.py      # gera os dados leves de dados_web/
├── 04_prepara_cobertura.py    # recorta o MapBiomas na grade do projeto
├── 05_valida_cobertura_elevacao.py  # cobertura x elevação (FABDEM completo)
├── docs/
│   ├── logica_da_ferramenta.md        # como a ferramenta raciocina, ponta a ponta
│   └── validacao_mapbiomas_laudo.md   # cobertura x Laudo biológico do Cassurubá
├── teste_sintetico.py         # valida o pipeline sem precisar do FABDEM
├── dados/                     # SÓ se NMRM_DIR_DADOS não estiver definida (ver "Onde ficam os dados")
├── dados_web/                 # dados leves 30 m p/ deploy (VERSIONADO, ~2,3 MB)
└── saidas/                    # PNG, GeoTIFF, CSV (NÃO versionar)
```

## Como instalar

```powershell
# 1. Ambiente virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate

# 2. Dependências
pip install -r requirements.txt
```

`teste_sintetico.py` roda o pipeline inteiro sobre um MDE sintético e não
exige o download do FABDEM — útil para validar a instalação.

## Como rodar

O simulador tem **modo duplo**. `src/fonte_dados.py` decide qual usar sem
configuração manual: se `NMRM_DIR_DADOS` (ou `./dados/`) contém o MDE
processado, roda em **modo local**; caso contrário, cai para o **modo web**
usando `dados_web/`.

### Onde ficam os dados (`NMRM_DIR_DADOS`)

Os dados pesados **não** ficam no repositório. `config.py` lê a variável de
ambiente `NMRM_DIR_DADOS`; nesta máquina ela vale `C:\dados_nmrm`, e é lá que
vivem `fabdem/` (tiles brutos), `auxiliar/` (MapBiomas nacional
`brazil_coverage-col11_2025.tif`, o recorte de cobertura, `ucs_regiao.geojson`)
e `processado/` (MDE e máscara de água). **Sem a variável**, o projeto cai
para `dados/` dentro do repositório (pasta ignorada pelo git, recriada por
`config.criar_estrutura()`); se você clonou o repositório e não definiu a
variável, é nessa pasta que as entradas precisam estar. Nenhum script lê
`dados/` do repositório quando `NMRM_DIR_DADOS` está definida.

### Modo local — dados completos, flood-fill em tempo real

Extensão inteira da planície em `float32`, com o teste de conectividade
recalculado a cada movimento de controle. É o modo para trabalho de análise.

```powershell
# (opcional) dados fora de pasta sincronizada — os tiles FABDEM somam alguns GB.
# Se o repositório estiver em OneDrive / Google Drive / Dropbox:
$env:NMRM_DIR_DADOS = "C:\dados_nmrm"   # Linux/macOS: export NMRM_DIR_DADOS=~/dados_nmrm
# Sem a variável, o projeto usa ./dados/.

# 1. Pré-processamento do MDE (gera dados/processado/caravelas_fabdem_utm24s_30m.tif
#    e a máscara de água caravelas_mascara_agua_utm24s_30m.tif)
python 01_mapa_elevacao.py

# 2. (opcional) regenerar os dados leves de dados_web/ a partir do MDE processado
python 03_prepara_dem_web.py

# 3. Simulador interativo
streamlit run 02_simulador_nmrm.py
```

### Modo web — dados leves versionados (`dados_web/`)

É o modo do deploy no **Streamlit Community Cloud** e roda em qualquer clone
sem o download do FABDEM. `03_prepara_dem_web.py` produz, a partir do MDE
processado, três rasters de 30 m recortados à planície: DEM em `int16`
(centímetros), máscara de água, e um **raster de limiar de conexão
hidráulica pré-computado** — cada pixel guarda a menor cota de mar em que
passa a estar inundado *e* conectado ao oceano. Isso substitui o flood-fill
em tempo real por uma consulta `limiar <= cota`, mantendo os mesmos números
(validado pixel a pixel). O conjunto todo fica em ~2,3 MB.

```powershell
# Basta ter dados_web/ no repositório (já versionado). Sem NMRM_DIR_DADOS:
streamlit run 02_simulador_nmrm.py
```

No modo web o toggle "água pode entrar pelas bordas do recorte" fica
desabilitado: seu valor foi fixado na geração dos dados leves. O terreno
acima de **+20 m** foi achatado (teto) — cenários acima disso não são
válidos nesse modo.

### Pré-visualizar localmente a versão que vai ao público

O resolvedor escolhe o modo sozinho: se o MDE completo existe, roda em local.
Para ver na sua máquina exatamente a ferramenta que vai ao ar — mesmos dados
leves, mesmo limiar pré-computado, mesmos controles bloqueados — force o modo
com a variável `NMRM_MODO`:

```powershell
# Windows / PowerShell
$env:NMRM_MODO = "web"
streamlit run 02_simulador_nmrm.py

# para voltar ao modo local
Remove-Item Env:NMRM_MODO
```

```bash
# Linux / macOS — vale só para este comando
NMRM_MODO=web streamlit run 02_simulador_nmrm.py
```

A barra lateral mostra uma tarja **Pré-visualização do modo público** enquanto
a variável está ligada, para não confundir controle bloqueado de propósito com
bug. `NMRM_MODO=local` explicita o padrão; qualquer outro valor é ignorado com
aviso no console.

O que muda no modo público: cenários IPCC AR6 fora do seletor, maré travada em
NM, campo de caminho do MDE oculto, semeadura de bordas fixa (vem
pré-computada no raster de limiar) e tema escuro nas figuras por padrão.

### Deploy no Streamlit Community Cloud

Aponte o app para `02_simulador_nmrm.py`. `requirements.txt` traz pisos de
versão (não versões exatas), e `.streamlit/config.toml` fixa o tema escuro.
Nenhuma variável de ambiente é necessária — a ausência de `NMRM_DIR_DADOS`
já seleciona o modo web.

### Licença dos dados em `dados_web/`

Os rasters de `dados_web/` são **produtos derivados do FABDEM V1-2** (Hawker
et al. 2022) — recorte, mudança de tipo de dado e processamento de
conectividade. Herdam a licença da fonte, **CC BY-NC-SA 4.0**: uso não
comercial, atribuição obrigatória e compartilhamento pela mesma licença.
Ver `dados_web/LICENSE.txt`. A licença do **código** deste repositório é
declarada à parte, no `LICENSE` da raiz.

## Como obter os dados

**FABDEM V1-2** (Hawker et al. 2022) — MDE principal.

1. Abra a página do dataset:
   <https://data.bris.ac.uk/data/dataset/s5hqmjcdj8yo2ibzi9b4ew3sn>
   (DOI: <https://doi.org/10.5523/bris.s5hqmjcdj8yo2ibzi9b4ew3sn>)
2. Aceite a licença **CC BY-NC-SA 4.0** e baixe o bloco de 10°×10°
   **`S20W040-S10W030_FABDEM_V1-2.zip`**, que contém Caravelas (~17,7°S / 39,2°W).
   Link direto:
   <https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn/S20W040-S10W030_FABDEM_V1-2.zip>
3. Extraia para `fabdem/` da pasta de dados (`NMRM_DIR_DADOS/fabdem`) os tiles de 1°×1° que intersectam o recorte:
   `S18W040`, `S18W039`, `S19W040` (o `S19W039` é opcional e pode não existir —
   é área quase toda oceânica).

Os diretórios `dados/` e `saidas/` **não são versionados**: redistribuir os
tiles FABDEM no repositório violaria a cláusula NonCommercial/ShareAlike.

Bases auxiliares (GEBCO 2025, constantes harmônicas BNDO/CHM): ver seção 4 do
`CLAUDE.md`.

**MapBiomas.** Baixe o mosaico nacional de cobertura da Coleção 11
(`brazil_coverage-col11_2025.tif`) em <https://brasil.mapbiomas.org>, coloque em
`auxiliar/` da pasta de dados (`$env:NMRM_DIR_DADOS/auxiliar`, ou `dados/auxiliar/`
sem a variável) e rode. O `04` procura o arquivo **só** ali; ausente, ele para
com um erro que diz onde o arquivo deveria estar:

```bash
python 04_prepara_cobertura.py
```

O script lê apenas a janela de Caravelas do arquivo nacional, reprojeta com
reamostragem *nearest* (dado categórico) e grava o recorte alinhado à grade do
MDE, em `dados/auxiliar/` e em `dados_web/`. A camada aparece no mapa
interativo; se o recorte não existir, o controle fica desligado e a simulação
segue normalmente.

## Novidades da v1.3

- **O mapa interativo virou a aba principal.** A figura de 300 dpi passou para a
  segunda aba e continua sendo o produto do relatório.
- **Camada topográfica gerada do próprio FABDEM.** Hipsométrico em 11 faixas
  (0,5 m de degrau nas cotas baixas) mais isolinhas de
  0,5 / 1 / 2 / 3 / 5 / 10 / 20 m. Nenhum basemap topográfico de terceiros: o
  relevo exibido é o mesmo que a simulação corta. Os dois toggles — topografia
  e isolinhas — vêm **desligados por padrão** na seção "5 · Camadas do mapa
  interativo"; o usuário liga quando quiser.
- **Clique lê o ponto, num balão sobre ele.** Coordenada, cota FABDEM sem
  interpolação, faixa hipsométrica, situação naquela cota (inundada / isolada /
  acima), quantos metros faltam para alagar e classe de cobertura do MapBiomas.
  Clicar sobre manguezal acrescenta o aviso de viés de dossel. As mesmas
  informações aparecem em métricas abaixo do mapa.
- **Camada MapBiomas Coleção 11 (2025)**, com legenda oficial conferida.
  Nesta versão é **apenas visual** — não entra em nenhum cálculo.
  Gerada por `python 04_prepara_cobertura.py`.
- **Os mapas cabem numa tela.** Altura do mapa interativo e largura da figura
  estática viraram controles da barra lateral.
- **Validação da cobertura contra o Laudo biológico do Cassurubá**
  (`docs/validacao_mapbiomas_laudo.md`) — e, dela, o achado abaixo.

> ⚠️ **Viés de dossel sobre manguezal.** O cruzamento FABDEM × MapBiomas mostrou
> o mangue em cota mediana de **4,31 m** e o apicum em **1,91 m** — ordem
> invertida em relação à zonação de maré, que põe a planície hipersalina *acima*
> da floresta de mangue. O resíduo de dossel sobre mangue é da ordem de 3 m,
> maior que todo o NMRM projetado para 2100. Consequência prática: a ferramenta
> **subestima** a exposição do manguezal, e área de mangue perdida por cenário
> não deve ser reportada enquanto isso não for tratado. O apicum, sem dossel,
> mede certo e responde como esperado (56 % abaixo de +2 m).

## Novidades da v1.2

Ajustes vindos da apresentação ao grupo:

- **Modo Manual até +10 m.** O teto é recalculado em execução contra o
  alcance do raster de limiar e contra o `clamp_m` do MDE leve. Acima de
  +3 m a interface avisa que a simulação saiu da faixa projetada pelo AR6
  (máx. +1,60 m em 2100, SSP5-8.5 de baixa confiança, p83) e passa a valer
  como teste de sensibilidade do terreno — ou comparação com os paleoníveis
  holocênicos da própria planície (+4,8 / +3,5 / +2,5 m, Andrade et al. 2003).
- **"Área mínima de mancha" agora explicada na interface.** Filtro de ruído
  do MDE: descarta cada mancha contígua (vizinhança 8) menor que o valor
  informado, nas duas classes — inundada e depressão isolada. Na grade de
  30 m, 1 pixel = 0,09 ha.
- **Relevo sombreado virou o fundo padrão**, com o hipsométrico como opção
  secundária.
- **Maré travada no nível médio na ferramenta pública (modo web).** PM, PMS
  e HAT continuam visíveis, porém desabilitados, com o aviso "Demais níveis
  de maré em desenvolvimento". No modo local o seletor segue editável.
- **Procedência declarada na aba Metadados:** de onde vêm os cenários AR6 e
  o que significa exatamente "nível médio" nesta ferramenta.
- **Ferramenta pública mais enxuta.** No modo web o seletor de cenário
  oferece só *Níveis da turma* e *Manual* — os cenários IPCC AR6 aparecem
  como "em desenvolvimento", porque os valores em `CENARIOS_AR6` ainda são
  globais (NMGM) e não o NMRM local de Caravelas. O campo de caminho do MDE
  também some: lá o raster é o `dados_web/` versionado com o app.
- **Tema escuro.** A aplicação publicada usa paleta preto azulado
  (`.streamlit/config.toml`). As figuras têm toggle próprio — **Tema escuro
  nas figuras** — com padrão escuro no modo web e claro no modo local, que é
  de onde saem os PNG do relatório. O tema muda apenas o papel da figura;
  as cores de inundação, depressão isolada e oceano são as mesmas nos dois
  temas, para o mapa da tela e o do relatório serem lidos igual.

## Estado atual e limitações conhecidas

- **O "nível médio" é herdado, não calculado.** O corte é feito em z = 0 m no
  datum vertical do próprio FABDEM (geoide EGM2008): assume-se
  `NM local ≈ geoide`, com `OFFSET_GEOIDE_NM_M = 0.00`. A diferença real é a
  topografia dinâmica média (MDT) — decimétrica no Atlântico Sul tropical,
  portanto da mesma ordem do NMRM projetado para 2050.
- **Os valores SSP não foram calculados aqui.** Vêm da Tabela 9.9 do IPCC AR6
  WGI Cap. 9 (Fox-Kemper et al. 2021): NMGM, mediana e faixa provável 17–83 %,
  base 1995–2014. São **globais**; os valores locais de Caravelas devem sair
  do NASA/IPCC AR6 Sea Level Projection Tool.
- **Amarração vertical ao datum da DHN ainda pendente.** O FABDEM usa datum
  vertical EGM2008; a diferença para a superfície média do mar real (MDT)
  segue desconhecida, e `OFFSET_GEOIDE_NM_M` continua em `0.00`.
- **Maré: TPXO9-atlas v5, não mais placeholder (22/09/2026).** Os campos de
  `NIVEIS_MARE` (NM/PMQ/PM/PMS/HAT) deixaram de estar em `0.00` com flag
  `PROVISORIO = True` — agora vêm do TPXO9-atlas v5 (OSU), extraído por
  `07_mare_tpxo.py`. Continua sendo **modelo, não medição de marégrafo**
  (`NIVEIS_MARE["MEDIDA"] = False`), com ponto AO LARGO da barra (célula de
  ~3,7 km — não resolve o estuário) e **sem** resolver o item anterior (o
  datum vertical do MDE é problema independente). A solicitação de
  constantes harmônicas de **marégrafo** ao **BNDO/CHM**
  (`chm.bndo@marinha.mil.br`) é caminho crítico e **ainda não foi feita** —
  é a única fonte que tornaria `MEDIDA = True`. Nenhum valor de maré, datum
  ou projeção local é inventado — se o dado não chegou, permanece `0.00`
  sinalizado.
- **Viés do FABDEM sobre manguezal.** O FABDEM remove dossel e edificações
  por machine learning, mas em manguezal denso o resíduo de altura de árvore
  ainda pode superar o próprio sinal de NMRM simulado. Não substituir por
  SRTM / Copernicus GLO-30 bruto / Terrain-RGB: nesse terreno o problema
  seria maior.
- **Máscara de água incompleta em rios estreitos.** A conectividade
  hidráulica propaga a partir dos pixels de oceano/estuário codificados como
  `0.0` exato no FABDEM. Canais e gamboas com menos de ~1 pixel de largura
  podem não estar nessa máscara, subestimando a via de propagação estuário
  adentro.
- **Cruzamento com MapBiomas ainda não implementado** (Parte 2 — resposta
  ecológica). A v1 entrega só a camada física de exposição.
- Todo produto declara suas limitações no rodapé da figura e na aba de
  metadados. Distinguir sempre **NMGM** (média global do mar) de **NMRM**
  (relativo local).

## Citação e licença

Modelo Digital de Elevação:

> Hawker, L., Uhe, P., Paulo, L., Sosa, J., Savage, J., Sampson, C., Neal, J.
> (2022). A 30 m global map of elevation with forests and buildings removed.
> *Environmental Research Letters*, 17, 024016.
> <https://doi.org/10.1088/1748-9326/ac4d4f>

FABDEM V1-2 é distribuído sob **CC BY-NC-SA 4.0**. Este repositório adota a
mesma licença (ver `LICENSE`): uso acadêmico e não comercial, com
compartilhamento pela mesma licença.
