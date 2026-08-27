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
│   └── mapa_web.py            # mapa base interativo (folium)
├── 01_mapa_elevacao.py        # mosaico/recorte/reprojeção FABDEM + mapa base
├── 02_simulador_nmrm.py       # interface Streamlit sobre slr_core
├── 03_prepara_dem_web.py      # gera os dados leves de dados_web/
├── teste_sintetico.py         # valida o pipeline sem precisar do FABDEM
├── dados/                     # entradas (NÃO versionar — FABDEM é CC BY-NC-SA)
│   ├── fabdem/                # tiles brutos .tif
│   ├── auxiliar/              # MapBiomas, GEBCO, maregrafia
│   └── processado/            # caravelas_fabdem_utm24s_30m.tif
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

### Deploy no Streamlit Community Cloud

Aponte o app para `02_simulador_nmrm.py`. `requirements.txt` traz pisos de
versão (não versões exatas), e `.streamlit/config.toml` fixa o tema claro.
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
3. Extraia para `dados/fabdem/` os tiles de 1°×1° que intersectam o recorte:
   `S18W040`, `S18W039`, `S19W040` (o `S19W039` é opcional e pode não existir —
   é área quase toda oceânica).

Os diretórios `dados/` e `saidas/` **não são versionados**: redistribuir os
tiles FABDEM no repositório violaria a cláusula NonCommercial/ShareAlike.

Bases auxiliares (MapBiomas, GEBCO 2025, constantes harmônicas BNDO/CHM):
ver seção 4 do `CLAUDE.md`.

## Estado atual e limitações conhecidas

- **Amarração vertical ao datum da DHN ainda pendente.** O FABDEM usa datum
  vertical EGM2008; a v1 roda no **nível médio**, sem offset de maré. Os
  campos em `NIVEIS_MARE` estão em `0.00` com flag `PROVISORIO = True`.
  A solicitação de constantes harmônicas e datums locais ao **BNDO/CHM**
  (`chm.bndo@marinha.mil.br`) é caminho crítico e **ainda não foi feita**.
  Nenhum valor de maré, datum ou projeção local é inventado — se o dado não
  chegou, permanece `0.00` sinalizado.
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
