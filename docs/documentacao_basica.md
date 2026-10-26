# Documentação básica — Simulador de exposição ao NMRM, Caravelas (BA)

**Projeto 26.09** · Ecossistemas Marinhos Costeiros — UERJ / FAOC / DOB (Prof. Filipe Chaves) · semestre 2026.2
Versão do app descrita aqui: **v3.2** (26/10/2026)

Este documento é o ponto de partida para escrever o relatório da turma. Explica
(1) o conceito do trabalho, (2) como o app foi construído, (3) o que ele
entrega e (4) o que ele **não** diz. Uma documentação completa virá depois; para
o raciocínio detalhado, ver `logica_da_ferramenta.md`, e para as decisões
datadas, o `CLAUDE.md` da raiz.

---

## 1. O conceito

### A pergunta e a cadeia analítica

A disciplina organiza o semestre em torno de uma pergunta: *como a elevação do
Nível Médio Relativo do Mar (NMRM) poderá reorganizar os ecossistemas costeiros
e quais consequências ecológicas e sociais emergem disso?* A resposta é
construída em uma cadeia:

```
Cenário → Exposição → Processo → Resposta ecológica → Serviço → Sociedade → Adaptação
```

O app cobre o elo **Exposição**: dado um nível do mar, **onde a água chega** na
planície costeira de Caravelas. Os elos seguintes (resposta ecológica e adiante)
são a Parte 2 do trabalho e ainda não estão no app; a camada de biomas
(MapBiomas) está disponível como contexto visual, mas não entra em nenhuma conta.

### Área de estudo

Planície costeira de Caravelas, extremo sul da Bahia: praia, restinga, duna,
manguezal e o sistema estuarino Caravelas–Peruípe. É uma planície
**extremamente plana** e progradante, com cordões litorâneos quaternários — por
isso poucos decímetros de variação de nível mudam muito o mapa. A **área de estudo
da turma** foi desenhada no QGIS sobre a batimetria (isóbata de 500 m) e as três
unidades de conservação: RESEX Cassurubá, APA Ponta da Baleia/Abrolhos e PARNA
Marinho dos Abrolhos.

### Quatro ideias que sustentam o app

**1. Exposição potencial, não previsão.** O app responde a uma pergunta
geométrica: *que terreno está abaixo de uma cota d'água e tem caminho físico
até o mar?* Não resolve hidrodinâmica, propagação de maré no estuário, ondas,
drenagem nem a resposta do sedimento (o manguezal acresce, a duna migra, a
planície recebe sedimento). Por isso o resultado tende a **superestimar** perda
física e deve ser lido como *potencial*.

**2. NMGM ≠ NMRM.** O nível médio **global** (NMGM) é o que o IPCC projeta nos
cenários SSP; o nível médio **relativo** (NMRM) é o que a costa sente, e inclui
movimento vertical da terra e efeitos regionais. Os cenários do app são globais
e estão sempre rotulados "(NMGM)". Misturar os dois seria o erro central a
evitar no relatório.

**3. A cota é composta.** O app corta o terreno numa cota que soma parcelas:

```
cota = NMRM (cenário ou nível escolhido) + maré (datum) + (nível médio − geoide) + sobrelevação
```

A página **Metadados** mostra a decomposição, parcela por parcela. Hoje a maré
vem de um modelo (TPXO9) e as parcelas "nível médio − geoide" e sobrelevação
valem zero por padrão (a segunda é opcional).

**4. Conectividade hidráulica.** Terreno abaixo da cota **sem caminho até o mar**
é uma *depressão isolada*, não inundação. Os simuladores online costumam somar
as duas. O app as separa: azul = inundação conectada ao mar; roxo = abaixo da
cota, sem conexão. Esse é o principal diferencial do trabalho. A +2,00 m, por
exemplo, o "bathtub" simples contaria 71,1 km² no domínio inteiro, mas só
27,8 km² têm conexão com o mar (cenário de nível médio, dados do modo web).

---

## 2. Como o app foi construído

### Arquitetura em três camadas

```
 dados brutos  ──►  scripts 01…12 (preparo)  ──►  dados_web/ (leve, versionado)
                                                        │
                       src/slr_core.py  (MOTOR: toda a ciência, sem interface)
                                                        │
                       02_simulador_nmrm.py (INTERFACE Streamlit, só desenha controles)
```

- **Motor (`src/slr_core.py`).** Calcula a cota, a máscara de inundação com
  conectividade, as estatísticas de área e as figuras. Não importa Streamlit nem
  nenhuma biblioteca de interface — assim a mesma ciência serve ao app, aos
  scripts e aos testes.
- **Módulos de apoio (`src/`).** `fonte_dados.py` decide o modo de execução e lê
  os dados; `mapa_web.py` monta as camadas do mapa interativo; `cobertura.py`
  trata o MapBiomas; `correntes.py`, as correntes; `paleo.py`, o paleoambiente.
- **Interface (`02_simulador_nmrm.py`).** Cinco páginas (Simulador, Turma,
  Paleoambiente, Exposição e cenários, Metadados). O Streamlit executa só a
  página aberta, o que mantém o app leve no servidor.
- **Parâmetros em um só lugar.** Todo limiar numérico vive em dicionários
  `CONFIG_*`, `CENARIOS_*` e `NIVEIS_*` no topo de cada módulo — nada
  "escondido" dentro de funções. `config.py` guarda caminhos, bbox e CRS.

### Pipeline de preparo dos dados

| Script | O que faz |
|---|---|
| `01_mapa_elevacao.py` | Mosaico dos tiles FABDEM, recorte, reprojeção para SIRGAS 2000 / UTM 24S (EPSG:31984, 30 m), máscara de oceano |
| `03_prepara_dem_web.py` | Gera os dados leves (~5 MB) e o **raster de limiar de conexão**: para cada pixel, a menor cota de mar em que ele fica inundado *e* conectado |
| `04_prepara_cobertura.py` | Recorta o MapBiomas Col. 11 alinhado pixel a pixel ao MDE (reamostragem *nearest*, por ser dado categórico) |
| `07_mare_tpxo.py` | Extrai os datums de maré do TPXO9-atlas v5 (roda fora do repositório) |
| `08`, `09` | Camadas da turma: UCs (CNUC) e limite da área de estudo (shapefile do QGIS) |
| `10_paleolinhas.py` | Fecha em polígonos de terra emersa as linhas digitalizadas pela turma para os sete estágios |
| `11`, `12` | Baixam e reduzem as correntes do CMEMS (climatologia e trimestres) |

### Dois modos de execução

- **Modo local:** usa o MDE completo e refaz o teste de conectividade
  (*flood-fill*) a cada mudança de controle. É para análise.
- **Modo web:** usa `dados_web/`. Em vez de refazer o flood-fill, consulta o
  raster de limiar (`limiar <= cota`), o que dá os mesmos números e roda em
  qualquer computador sem baixar o FABDEM. É o modo do app publicado. Limite:
  terreno acima de +20 m foi achatado, então não vale para cotas acima disso.

### O recorte da turma: relato, não cálculo

No modo Turma os números e o desenho se restringem à área de estudo. Mas a
conectividade é resolvida **antes**, no domínio inteiro, e o polígono entra
depois, só na contagem e no desenho. Recortar antes cortaria caminhos de água
que entram pela borda e inventaria depressões "isoladas" que não são. Os km²
reportados são a **terra** da área de estudo coberta pelo MDE (cerca de 450 km²),
não a extensão do polígono (~16.255 km², quase toda plataforma continental).

### As figuras

A figura de 300 dpi é gerada **sob demanda** (botão "Gerar figura") porque é a
parte mais pesada do app. Vem com escala, seta norte, legenda e rodapé com a
cota, o datum, as fontes e as limitações. Opções:

- **Um mapa ou dois lado a lado** — o segundo pode repetir a cota ou usar outra,
  para comparar dois níveis.
- **Biomas (MapBiomas)** em cada mapa, no lugar do fundo hipsométrico.
- **Enquadramento**: planície (onde há MDE) ou área de estudo inteira — só muda o
  que entra no quadro, nunca os números.
- Tema claro (relatório impresso) ou escuro (tela). O tema só muda o papel da
  figura; as cores cartográficas são as mesmas.

### Paleoambiente

A página reconstrói os sete estágios de Andrade et al. (2003) a partir das
figuras 9 a 15 do artigo, georreferenciadas no QGIS e digitalizadas pela turma
como linhas terra/água. O script `10` converte as linhas em polígonos de terra
emersa e a página compara cada estágio com a terra de hoje (FABDEM). É uma
**reconstrução**, com erro posicional de centenas de metros: serve para comparar
estágios entre si, não como medida absoluta.

---

## 3. O que o app entrega (números de referência)

Valores obtidos no modo web (dados de `dados_web/`), maré no nível médio (NM),
conectividade ligada, sem sobrelevação e sem área mínima de mancha. Qualquer um
pode reproduzi-los no app (página Simulador ou Turma). A "área de estudo" é o
recorte da turma; o "domínio" é todo o MDE (2.440,9 km² de terra).

| Nível do mar | Inundada — domínio | Isolada — domínio | Inundada — área de estudo | % da terra da área de estudo |
|---|---|---|---|---|
| +0,5 m | 4,3 km² | 0,6 km² | 3,8 km² | 0,84 % |
| +1,0 m | 7,0 km² | 1,6 km² | 6,1 km² | 1,34 % |
| +2,0 m | 27,8 km² | 43,3 km² | 24,0 km² | 5,34 % |

Terra emersa da área de estudo coberta pelo MDE: 450,5 km². A "área mínima de
mancha" (Ajustes avançados) é um filtro de ruído: com o padrão atual de 0 ha, a
+2,0 m a área de estudo tem 24,0 km² inundados; com 1 ha, 23,0 km² (valor que
aparece em versões antigas da documentação). Declare no relatório qual filtro usou. Note o salto entre
+1 e +2 m: a planície é tão plana que os últimos decímetros alagam muito mais
área que os primeiros. Mudar o recorte muda a porcentagem (a área de estudo
concentra a planície; o domínio inteiro inclui terreno alto que não alaga), mas
descreve os mesmos eventos.

**Maré (TPXO9-atlas v5, ao largo da barra):** NM 0,000 · PMQ 0,456 · PM 0,913 ·
PMS 1,244 · HAT estimado 1,676 m. Selecionar PMS soma +1,24 m à cota antes de
qualquer mudança climática.

**Paleoambiente — terra emersa por estágio** (km², no quadro das figuras do
artigo): I 1.122 · II 916 · III 931 · IV 1.301 · V 1.333 · VI 1.359 · VII 1.383.
Diferenças pequenas entre estágios vizinhos (V, VI, VII) estão dentro do erro de
redesenho.

**Cenários IPCC AR6 (NMGM, relativo a 1995–2014, mediana [17–83 %]):**

| Cenário | 2050 | 2100 |
|---|---|---|
| SSP1-2.6 | 0,19 [0,16–0,25] m | 0,44 [0,32–0,62] m |
| SSP2-4.5 | 0,20 [0,17–0,26] m | 0,56 [0,44–0,76] m |
| SSP5-8.5 | 0,23 [0,20–0,29] m | 0,77 [0,63–1,01] m |
| SSP5-8.5 baixa confiança | 0,24 [0,20–0,40] m | 0,88 [0,63–1,60] m |

Os valores acima do app foram conferidos contra uma reprodução secundária da
Tabela 9.9 do AR6 WGI Cap. 9; confira na tabela impressa antes de citar.

---

## 4. O que o app não diz (cite no relatório)

1. **Não é previsão** de inundação: não há hidrodinâmica, ondas, drenagem nem
   morfodinâmica.
2. **O nível médio é herdado do geoide EGM2008**, sem correção por topografia
   dinâmica média (decimétrica, da mesma ordem do NMRM de 2050).
3. **Os cenários são globais (NMGM).** A troca pelos valores locais de Caravelas
   (NASA/IPCC AR6 Sea Level Projection Tool) está pendente.
4. **A maré é de modelo**, ao largo da barra, e não resolve o estuário
   Caravelas–Peruípe. O HAT é um limite superior. Constantes de marégrafo
   (BNDO/CHM) ainda não foram solicitadas.
5. **Viés de dossel no manguezal.** O FABDEM coloca o mangue em cota mediana de
   4,31 m e o apicum em 1,91 m — ordem invertida em relação à zonação de maré. A
   exposição do manguezal sai subestimada; **não reporte área de mangue perdida
   por cenário.** O apicum, sem dossel, serve de controle.
6. **Resolução de 30 m e rios estreitos:** canais com menos de ~1 pixel podem
   faltar na máscara de água.
7. **Correntes oceânicas e biomas são camadas visuais**: não entram em nenhuma
   conta. Correntes são de modelo assimilativo (grade de ~8 km), não medição.
8. **O paleoambiente é redesenho** de figuras de 2003, não simulação nem medida.
9. **Acima de +3 m o mapa deixa de ser cenário climático** e passa a ser teste de
   sensibilidade do terreno (o máximo do AR6 para 2100 é +1,60 m); serve para
   comparar com os paleoníveis holocênicos de Andrade et al. (+4,8 / +3,5 / +2,5 m).

---

## 5. Roteiro sugerido para o relatório

1. **Introdução** — a pergunta do semestre, a cadeia analítica e o recorte do
   trabalho (Parte 1: exposição).
2. **Área de estudo** — Caravelas, ecossistemas, UCs, mapa da área (use a figura
   de dois mapas: exposição | biomas, ou a visão da área de estudo inteira).
3. **Métodos** — dados (seção 2 e a tabela de fontes do README), cota composta,
   conectividade hidráulica, recorte (relato × cálculo).
4. **Resultados** — tabela da seção 3 para os níveis da turma; figura de dois
   mapas comparando +1 m e +2 m; contraste bathtub × conectividade; paleoambiente.
5. **Discussão** — o que a exposição significa para cada ecossistema (resposta
   ecológica é interpretação sua, não saída do app), sempre ancorada nas
   limitações da seção 4.
6. **Limitações e próximos passos** — NMRM local, maré de marégrafo, tratamento
   do dossel, Parte 2.
7. **Referências** — abaixo.

---

## Referências

- Hawker, L., Uhe, P., Paulo, L., Sosa, J., Savage, J., Sampson, C., Neal, J.
  (2022). A 30 m global map of elevation with forests and buildings removed.
  *Environmental Research Letters*, 17, 024016. <https://doi.org/10.1088/1748-9326/ac4d4f>
- Fox-Kemper, B. et al. (2021). Ocean, Cryosphere and Sea Level Change. In:
  *Climate Change 2021: The Physical Science Basis*. IPCC AR6 WGI, Cap. 9.
- Garner, G. G. et al. (2021). IPCC AR6 Sea Level Projections. Zenodo,
  <https://doi.org/10.5281/zenodo.5914709>
- Andrade, A. C. S., Dominguez, J. M. L., Martin, L., Bittencourt, A. C. S. P.
  (2003). Quaternary evolution of the Caravelas strandplain – Southern Bahia
  State – Brazil. *Anais da Academia Brasileira de Ciências*, 75(3), 357-382.
- MapBiomas Brasil, Coleção 11 (2025). <https://brasil.mapbiomas.org>
- Copernicus Marine Service. GLOBAL_MULTIYEAR_PHY_001_030 (GLORYS12).
  <https://doi.org/10.48670/moi-00021>
- TPXO9-atlas v5 — Egbert, G. D. & Erofeeva, S. Y. (2002). Efficient inverse
  modeling of barotropic ocean tides. *J. Atmos. Oceanic Technol.*, 19, 183-204.
