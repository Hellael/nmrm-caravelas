# Simulador de exposição ao NMRM — Caravelas (BA)

Disciplina **Ecossistemas Marinhos Costeiros** — UERJ / FAOC / DOB
(Prof. Filipe Chaves), semestre 2026.2 · Projeto 26.09 · versão **v3.2**.

**Pergunta do semestre:** como a elevação do Nível Médio Relativo do Mar
(NMRM) poderá reorganizar os ecossistemas costeiros da planície de Caravelas,
extremo sul da Bahia, e quais consequências ecológicas e sociais emergem
dessa transformação?

> Para entender o conceito do trabalho e como o app foi construído, comece por
> [`docs/documentacao_basica.md`](docs/documentacao_basica.md). Este README
> cobre instalação, execução, dados e licenças.

## O que a ferramenta faz

Ferramenta geoespacial interativa de **exposição potencial** ao NMRM sobre a
planície costeira de Caravelas. A partir do Modelo Digital de Elevação FABDEM
V1-2 (~30 m), ela aplica uma cota d'água composta (nível do mar + maré +
sobrelevação) e classifica o terreno em **terra seca**, **inundada** (com
caminho hidráulico até o mar) e **isolada** (abaixo da cota, mas sem conexão).
O teste de **conectividade hidráulica** — ligado por padrão — é o principal
diferencial frente aos simuladores online, que costumam somar como inundada
qualquer depressão abaixo da cota.

A saída é **exposição potencial, não previsão de inundação real**: não resolve
hidrodinâmica, atenuação de maré no estuário, ondas, drenagem nem resposta
morfodinâmica (acresção de manguezal, migração de duna).

### As cinco páginas do app

| Página | Para que serve |
|---|---|
| **Simulador** | Uso público: escolha o nível do mar (manual ou cenário IPCC AR6, este rotulado como nível *global*), a maré e as camadas; mapa interativo com leitura por clique. |
| **Turma** | O mesmo simulador com os valores da disciplina pré-selecionados (+0,5 / +1 / +2 m), recorte à área de estudo da turma e análises por unidade de conservação. |
| **Paleoambiente** | Os sete estágios da evolução quaternária da planície (Andrade et al. 2003) comparados com a terra emersa de hoje. |
| **Exposição e cenários** | Curva de exposição (área × cota) e matriz de cenários. |
| **Metadados** | Procedência dos dados, decomposição da cota e limitações declaradas. |

Nas páginas Simulador e Turma, o botão **Gerar figura** monta a figura de
300 dpi para o relatório. O botão **Formato da figura** escolhe entre **um mapa**
ou **dois mapas lado a lado** (o segundo pode usar outra cota) e liga a camada
de **biomas** (MapBiomas) em cada mapa.

## Estrutura de pastas

```
nmrm-caravelas/
├── README.md
├── CLAUDE.md                  # memória técnica do projeto (decisões e histórico)
├── LICENSE                    # CC BY-NC-SA 4.0
├── requirements.txt           # dependências do app (pisos de versão)
├── requirements-geracao.txt   # dependências só dos scripts que geram dados_web/
├── config.py                  # caminhos, bbox, CRS, nomes de arquivo — fonte única
├── .streamlit/config.toml     # tema e limites do app publicado
├── .devcontainer/, .vscode/   # ambiente reproduzível
├── src/
│   ├── slr_core.py            # MOTOR — sem interface, toda a ciência
│   ├── fonte_dados.py         # decide modo local x web, lê MDE e limiar
│   ├── mapa_web.py            # camadas do mapa interativo
│   ├── cobertura.py           # legenda MapBiomas Col. 11 + leitura do recorte
│   ├── correntes.py           # camada de correntes oceânicas (visual)
│   └── paleo.py               # paleoambiente: comparação e figura
├── 01_mapa_elevacao.py        # mosaico/recorte/reprojeção FABDEM + mapa base
├── 02_simulador_nmrm.py       # interface Streamlit (as cinco páginas)
├── 03_prepara_dem_web.py      # gera os dados leves de dados_web/
├── 04_prepara_cobertura.py    # recorta o MapBiomas na grade do projeto
├── 05_…, 06_…                 # [diagnóstico] cobertura x elevação; viés de dossel
├── 07_mare_tpxo.py            # proveniência da maré TPXO9 (roda fora deste repo)
├── 08_prepara_camadas_turma.py  # regenera ucs_turma.geojson a partir do CNUC bruto
├── 09_limite_turma.py         # shapefile da área de estudo -> limite_turma.geojson
├── 10_paleolinhas.py          # shapefiles dos 7 estágios -> paleolinhas_turma.geojson
├── 11_baixa_correntes.py      # baixa correntes do CMEMS (exige login)
├── 12_prepara_correntes.py    # climatologia + trimestres -> correntes_caravelas.npz
├── diagnostico_zeros.py, histograma_cauda_costeira.py   # [diagnóstico]
├── teste_sintetico.py, teste_sintetico_correntes.py     # validam os pipelines sem dados reais
├── docs/                      # documentação (ver abaixo)
├── dados_web/                 # dados leves VERSIONADOS (~5 MB) — o que o app publicado lê
└── saidas/                    # PNG, GeoTIFF, CSV gerados (NÃO versionado)
```

**Documentos em `docs/`:** `documentacao_basica.md` (conceito e construção do
app), `logica_da_ferramenta.md` (como a ferramenta raciocina, ponta a ponta),
`validacao_mapbiomas_laudo.md` (cobertura × laudo biológico do Cassurubá),
`diagnostico_zeros.md` (investigação dos 0,0 m do FABDEM) e as imagens de
validação do georreferenciamento e das paleolinhas.

Os scripts `05`, `06`, `diagnostico_zeros.py` e `histograma_cauda_costeira.py`
são **ferramentas de investigação**: só leem os dados e gravam relatório em
`saidas/`. O app não os importa e nenhum produto de `dados_web/` depende deles.

## Como instalar

```bash
python -m venv .venv
source .venv/bin/activate          # Windows (PowerShell): .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Como rodar

O simulador tem **modo duplo**, escolhido sozinho por `src/fonte_dados.py`:
se a pasta de dados (`NMRM_DIR_DADOS`, ou `./dados/`) contém o MDE processado,
roda em **modo local**; caso contrário, cai para o **modo web**, que usa
`dados_web/`.

**Se você só clonou o repositório, basta rodar:**

```bash
streamlit run 02_simulador_nmrm.py
```

Isso já abre o app completo em modo web, sem baixar nenhum dado.

### Modo web — dados leves versionados (`dados_web/`)

É o modo do deploy no Streamlit Community Cloud e roda em qualquer clone.
`03_prepara_dem_web.py` produz, a partir do MDE processado, três rasters de
30 m recortados à planície: DEM em `int16` (centímetros), máscara de água e um
**raster de limiar de conexão hidráulica pré-computado** — cada pixel guarda a
menor cota de mar em que passa a estar inundado *e* conectado ao oceano. Isso
substitui o flood-fill em tempo real por uma consulta `limiar <= cota`,
mantendo os mesmos números. Limite: o terreno acima de **+20 m** foi achatado,
então cenários acima disso não são válidos nesse modo.

### Modo local — dados completos (só para quem tem o FABDEM)

Extensão inteira da planície em `float32`, com o teste de conectividade
recalculado a cada movimento de controle. Os dados pesados ficam fora do
repositório, na pasta apontada por `NMRM_DIR_DADOS` (subpastas `fabdem/`,
`auxiliar/` e `processado/`):

```bash
export NMRM_DIR_DADOS=~/dados_nmrm       # Windows: $env:NMRM_DIR_DADOS = "C:\dados_nmrm"
python 01_mapa_elevacao.py               # gera o MDE processado e a máscara de água
python 03_prepara_dem_web.py             # (opcional) regenera dados_web/
streamlit run 02_simulador_nmrm.py
```

Sem a variável, o projeto usa `dados/` dentro do repositório (ignorada pelo git).

Para ver na sua máquina exatamente a versão pública, force o modo web mesmo
com os dados completos presentes: `NMRM_MODO=web streamlit run 02_simulador_nmrm.py`
(no PowerShell: `$env:NMRM_MODO = "web"`).

### Deploy no Streamlit Community Cloud

Aponte o app para `02_simulador_nmrm.py`. O `requirements.txt` traz pisos de
versão (não versões exatas) e `.streamlit/config.toml` fixa o tema. Nenhuma
variável de ambiente é necessária: a ausência de `NMRM_DIR_DADOS` já seleciona
o modo web.

## Como obter os dados (só para regenerar produtos)

**FABDEM V1-2** (Hawker et al. 2022) — MDE principal.
Página do dataset: <https://data.bris.ac.uk/data/dataset/s5hqmjcdj8yo2ibzi9b4ew3sn>
(DOI <https://doi.org/10.5523/bris.s5hqmjcdj8yo2ibzi9b4ew3sn>). Aceite a licença
CC BY-NC-SA 4.0, baixe o bloco **`S20W040-S10W030_FABDEM_V1-2.zip`** e extraia
para `fabdem/` os tiles de 1°×1° `S18W040`, `S18W039` e `S19W040`
(`S19W039` é opcional: quase todo oceânico). Os tiles **não** são versionados —
redistribuí-los violaria a cláusula NonCommercial/ShareAlike.

**MapBiomas Coleção 11 (2025).** Baixe o mosaico nacional
`brazil_coverage-col11_2025.tif` em <https://brasil.mapbiomas.org>, coloque em
`auxiliar/` da pasta de dados e rode `python 04_prepara_cobertura.py`. O script
recorta Caravelas com reamostragem *nearest* (dado categórico) e grava o recorte
alinhado à grade do MDE. A camada é **apenas visual**.

**Correntes oceânicas (CMEMS GLORYS12, 2016–2025).** `11_baixa_correntes.py`
(exige conta gratuita em <https://data.marine.copernicus.eu>) e
`12_prepara_correntes.py` produzem `dados_web/correntes_caravelas.npz`. É
**modelo assimilativo, não medição**, e não entra em nenhuma conta de exposição.

> Generated using E.U. Copernicus Marine Service Information;
> <https://doi.org/10.48670/moi-00021>

**Camadas da turma.** O limite da área de estudo e as paleolinhas são trabalho
manual da turma no QGIS, versionado em `dados_web/fonte_limite_turma/` e
`dados_web/fonte_paleolinhas/` — não se regeneram a partir de fonte externa.
As UCs vêm do CNUC (ICMBio/MMA, 07/2026) e as isóbatas da Batimetria do Brasil
(CPRM/ANP 2013); detalhes em `CLAUDE.md` §4.

## Limitações conhecidas

- **O "nível médio" é herdado, não calculado.** O corte é feito em z = 0 m no
  datum vertical do FABDEM (geoide EGM2008): assume-se `NM local ≈ geoide`
  (`OFFSET_GEOIDE_NM_M = 0,00`). A diferença real é a topografia dinâmica média,
  decimétrica no Atlântico Sul tropical — da mesma ordem do NMRM de 2050.
- **Os cenários SSP são globais (NMGM), não NMRM.** Vêm da Tabela 9.9 do IPCC
  AR6 WGI Cap. 9 (Fox-Kemper et al. 2021) e não incluem movimento vertical da
  terra nem efeitos regionais. A interface os rotula como globais; devem ser
  substituídos pelos valores locais do NASA/IPCC AR6 Sea Level Projection Tool.
- **A maré é de modelo, não de marégrafo.** Os datums (NM, PMQ, PM, PMS, HAT)
  vêm do TPXO9-atlas v5 num ponto ao largo da barra (célula de ~3,7 km); não
  resolvem o estuário Caravelas–Peruípe. O HAT é um limite superior estimado.
  As constantes de marégrafo do BNDO/CHM ainda não foram solicitadas.
- **Viés de dossel sobre manguezal.** O FABDEM põe o mangue em cota mediana de
  4,31 m e o apicum em 1,91 m — ordem invertida em relação à zonação de maré.
  O resíduo (~3 m) é maior que todo o NMRM projetado para 2100: a exposição do
  manguezal sai **subestimada** e **não se deve reportar área de mangue perdida
  por cenário**. Detalhes em `docs/validacao_mapbiomas_laudo.md`.
- **Máscara de água incompleta em rios estreitos.** Canais com menos de ~1 pixel
  de largura podem não estar na máscara, subestimando a via de propagação
  estuário adentro.
- **Paleoambiente é reconstrução, não simulação.** Os polígonos são redesenho
  de figuras publicadas em 2003, com erro posicional da ordem de centenas de
  metros. Compare estágios entre si; não cite como medida absoluta.
- **Cruzamento com MapBiomas (Parte 2)** — resposta ecológica — ainda não está
  implementado: a cobertura é só visual.

Todo produto declara suas limitações no rodapé da figura e na página Metadados.
Distinga sempre **NMGM** (média global) de **NMRM** (relativo local).

## Histórico de versões

| Versão | Data | O que entrou |
|---|---|---|
| v1.2 | 09/2026 | Manual até +10 m, relevo sombreado, procedência dos cenários, tema escuro |
| v1.3 | 09/2026 | Mapa interativo principal, topografia e isolinhas do FABDEM, clique lê o ponto, MapBiomas |
| v2.0 | 09/2026 | Maré TPXO9, modos Turma/Livre, camadas da turma, recorte à área de estudo |
| v2.1 | 01/10/2026 | Paleoambiente: sete estágios de Andrade et al. (2003) |
| v3.0 | 02/10/2026 | Redesign em cinco páginas, figura sob demanda, cenários AR6 rotulados como globais |
| v3.1 | 21/10/2026 | Camada de correntes oceânicas (CMEMS GLORYS12) |
| v3.2 | 26/10/2026 | Figura de um ou dois mapas com biomas; figura do paleoambiente enquadrada na área de interesse |

## Fontes, citação e licença

| Dado | Fonte | Termos |
|---|---|---|
| MDE | FABDEM V1-2 — Hawker et al. (2022), *Environmental Research Letters* 17, 024016, <https://doi.org/10.1088/1748-9326/ac4d4f> | CC BY-NC-SA 4.0 |
| Cenários | IPCC AR6 WGI Cap. 9 — Fox-Kemper et al. (2021) | citar a fonte |
| Cobertura | MapBiomas Brasil, Coleção 11 (2025) | citar a fonte conforme os termos do MapBiomas |
| Correntes | CMEMS GLOBAL_MULTIYEAR_PHY_001_030 (GLORYS12) | atribuição ao Copernicus Marine Service |
| Maré | TPXO9-atlas v5 (OSU) — só as constantes derivadas estão no repositório | consultar os termos do OSU antes de redistribuir |
| Paleolinhas | Andrade et al. (2003), *An Acad Bras Cienc* 75(3): 357-382 | redesenho de figuras publicadas; ver aviso abaixo |
| UCs | CNUC 07/2026 (ICMBio/MMA) | dados públicos do governo federal |
| Isóbatas | Batimetria do Brasil (CPRM/ANP 2013), derivada do GEBCO | citar a fonte |

Os rasters de `dados_web/` são **produtos derivados do FABDEM** e herdam a
licença CC BY-NC-SA 4.0 (ver `dados_web/LICENSE.txt`). O código deste
repositório adota a mesma licença (ver `LICENSE`): uso acadêmico e não
comercial, com compartilhamento pela mesma licença.

> Os PNG em `dados_web/fonte_paleolinhas/georref/` são as figuras do artigo de
> 2003 usadas para o georreferenciamento. Antes de tornar o repositório público,
> confirme que a licença da revista permite a redistribuição das figuras; caso
> contrário, remova os PNG e mantenha só os `.points`.

Autor: Helio · Assistência: Claude.
