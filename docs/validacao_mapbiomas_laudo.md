# Validação qualitativa do MapBiomas Coleção 11 contra o Laudo biológico do Cassurubá

**Projeto 26.09 — Simulador NMRM Caravelas** · Ecossistemas Marinhos Costeiros / UERJ-FAOC-DOB
Data: 05/09/2026 · versão da ferramenta: v1.3

## 1. O que foi comparado

| | |
|---|---|
| **Dado testado** | MapBiomas Brasil, Coleção 11 (2025), 30 m — recorte de Caravelas gerado por `04_prepara_cobertura.py` |
| **Referência** | *Laudo biológico do sistema Caravelas–Nova Viçosa com vistas à criação da Reserva Extrativista do Cassurubá* |
| **Tipo de validação** | Qualitativa. O laudo é descritivo (fitofisionomias, espécies, salinidade intersticial, estrutura das florestas) e não fornece área por classe, então não há comparação numérica direta possível. |
| **Método** | Traduzir as afirmações espaciais e ecológicas do laudo em testes que o raster consegue responder — presença de classe, adjacência entre classes, posição relativa no terreno — e verificar cada uma. |

O terceiro dado entra sem ter sido convidado e acaba sendo o principal resultado: as
estatísticas de posição no terreno usam o **FABDEM**, o mesmo MDE que a simulação
corta. Cruzar cobertura com elevação testa os dois ao mesmo tempo.

> **Aviso sobre os números de elevação — reprocessado em 05/09/2026.** As tabelas
> abaixo foram recalculadas com o MDE **completo** (float32, sem teto), por
> `05_valida_cobertura_elevacao.py`. Confirma-se a hipótese: mangue, apicum, restinga
> herbácea, restinga arbórea e praia/duna — todos abaixo de 20 m — saem **idênticos**
> ao cálculo anterior com o MDE leve. As classes que sobem serra acima e estavam
> contaminadas pelo clamp de +20 m (Silvicultura, Formação Florestal, Pastagem) agora
> têm a mediana correta: **36,2 / 16,0 / 33,0 m** respectivamente. A única divergência
> encontrada foi nas *frações* "abaixo de X m" de Praia/Duna/Areal (não na mediana) —
> ver nota de rodapé da tabela da seção 4.4.

## 2. Composição do recorte

Área classificada: 2.584,2 km². Classes presentes: 17 (todas conferidas contra o CSV
oficial da Coleção 11).

| Classe | Área (km²) | % |
|---|---:|---:|
| Silvicultura | 967,1 | 37,4 |
| Formação Florestal | 404,1 | 15,6 |
| Pastagem | 321,6 | 12,4 |
| Campo Alagado e Área Pantanosa | 307,0 | 11,9 |
| Restinga Herbácea ou Arbustiva | 200,5 | 7,8 |
| Rio, Lago e Oceano | 165,4 | 6,4 |
| **Mangue** | **96,7** | **3,7** |
| Restinga Arbórea | 36,9 | 1,4 |
| Mosaico de Usos | 33,6 | 1,3 |
| Área Urbanizada | 20,2 | 0,8 |
| **Apicum** | **17,7** | **0,7** |
| Praia, Duna e Areal | 10,3 | 0,4 |
| demais (Café, Outras Áreas não Vegetadas, Lavouras, Formação Campestre) | 3,1 | 0,1 |

## 3. Por setor

Os setores do laudo são delimitados por rios (Massangano, Macaco, Caribê, do Largo,
Cupido). **Não temos essas linhas em vetor**, então aqui os setores são *faixas de
latitude aproximadas* — servem para ler tendência, não para citar área de setor.
Obter os limites reais (ICMBio/RESEX Cassurubá) é pendência.

| Classe (km²) | Norte (≥ −17,72°) | Central/Tapera (−17,72 a −17,82°) | Sul/Nova Viçosa (< −17,82°) |
|---|---:|---:|---:|
| Mangue | 25,2 | 39,9 | 31,7 |
| Apicum | 1,1 | 10,7 | 5,9 |
| Restinga Arbórea | 22,0 | 3,5 | 11,3 |
| Restinga Herbácea ou Arbustiva | 137,0 | 27,8 | 35,7 |
| Campo Alagado e Área Pantanosa | 194,0 | 42,4 | 70,5 |
| Praia, Duna e Areal | 5,8 | 0,6 | 3,9 |
| Silvicultura | 586,4 | 184,3 | 196,4 |
| Área classificada | 1.520 | 477 | 587 |

## 4. Testes

### 4.1 CONVERGE — a sequência mangue → apicum → restinga existe no raster

O laudo (seção B.3) define o *continuum* do ecossistema manguezal: planície lamosa,
floresta de mangue, planície hipersalina ("espacelado"), e o "apicum" propriamente dito
estendendo-se do capim salgado (*Sporobolus virginicus*) **até a transição com a
restinga arbórea/arbustiva**.

O raster reproduz a vizinhança:

| Teste (janela de 5×5 px = 150 m) | Resultado |
|---|---:|
| pixels de apicum com mangue na vizinhança | 35,5 % |
| pixels de apicum com restinga na vizinhança | 7,6 % |
| pixels de mangue com apicum na vizinhança | 7,1 % |
| pixels de apicum a ≤ 150 m do mangue (distância euclidiana) | **63,0 %** |
| distância mediana apicum → mangue | **120 m** |

O apicum do MapBiomas é, de fato, uma feição **interna ou marginal ao manguezal**, como
o laudo insiste (o apicum "integra o ecossistema manguezal"). Nenhuma outra classe tem
essa assinatura: a restinga herbácea fica a 2,9 km de mangue na mediana, a pastagem a
17,9 km.

### 4.2 CONVERGE — restinga arbórea mais alta que a herbácea

O laudo descreve a formação **arbustiva de moitas** como ocorrendo "onde o lençol
freático não aflora, pelo terreno ser topograficamente mais elevado que os outros tipos
de formação", e as formações **herbácea fechada inundada** e **arbustiva aberta
inundada** como áreas de afloramento de água doce, com lagoas.

FABDEM: Restinga Arbórea mediana **7,16 m** contra Restinga Herbácea/Arbustiva **5,49 m**
(p25 5,59 contra 4,35 m). A ordem bate. Ressalva: parte dessa diferença pode ser dossel
residual da restinga arbórea, não terreno — o mesmo problema da seção 4.4.

### 4.3 CONVERGE — a carcinicultura de 1.500 ha não foi implantada

O laudo dedica uma seção à pressão para construir 1.500 ha de viveiros de camarão entre
o rio do Macaco e o rio Massangano, na porção norte. **Nenhuma das 17 classes presentes
no recorte de 2025 é aquicultura ou tanque**. O que o MapBiomas mapeia hoje naquela
faixa é campo alagado, restinga herbácea e silvicultura. A ameaça central do laudo não
se materializou como cobertura.

### 4.4 DIVERGE — o mangue aparece alto demais no FABDEM (viés de dossel)

Este é o achado importante da sessão.

| Classe | p10 | p25 | **mediana** | p75 | p90 |
|---|---:|---:|---:|---:|---:|
| **Mangue** | 2,62 | 3,23 | **4,31** | 6,27 | 8,67 |
| **Apicum** | 1,35 | 1,55 | **1,91** | 2,37 | 2,92 |
| Restinga Herbácea/Arbustiva | 3,02 | 4,35 | 5,49 | 7,34 | 16,26 |
| Restinga Arbórea | 4,53 | 5,59 | 7,16 | 9,36 | 11,42 |
| Praia, Duna e Areal | 1,12 | 2,83 | 5,40 | 7,98 | 9,56 |

*(elevação FABDEM em m, datum EGM2008)*

O laudo, citando Hutchings & Saenger (1987), posiciona as feições em cotas bem
definidas: floresta de mangue **entre o nível médio do mar e a preamar de quadratura**;
planície hipersalina **entre a preamar de quadratura e a preamar média de sizígia** — ou
seja, **o apicum é mais alto que a floresta de mangue**, e ambos estão dentro da faixa
de maré, portanto abaixo de ~1,5 m.

O FABDEM devolve o **oposto e em cota errada**: mangue com mediana de 4,31 m, apicum a
1,91 m. Só 0,9 % dos pixels de mangue estão abaixo de 1 m — quando, por definição
ecológica, o manguezal é intermarés e deveria estar quase todo ali.

*(Confirmado com o MDE completo, sem clamp, em 05/09/2026 — os percentis desta tabela
não mudaram uma casa decimal em relação ao cálculo com o MDE leve. Estas cinco classes
já estavam inteiramente abaixo do teto de +20 m, então o clamp nunca as tocou.)*

A explicação mais direta é **dossel residual**. O FABDEM remove dossel e edificações do
Copernicus GLO-30 por aprendizado de máquina, treinado majoritariamente em floresta
"seca"; sobre manguezal a remoção fica incompleta, e o que sobra (2–6 m, compatível com
a altura das florestas de *Rhizophora* descritas no laudo) é exatamente a diferença
observada. O apicum, sem dossel nenhum — planície hipersalina de vegetação herbácea ou
sem vegetação —, é o único da lista que o MDE mede de verdade, e é o que cai na faixa
de cota que a ecologia prevê.

Ou seja: **a inversão mangue/apicum no FABDEM não é erro do MapBiomas, é assinatura do
viés de dossel do MDE** — e o apicum funciona como controle interno, porque é a mesma
paisagem sem a interferência.

**Consequência para a ferramenta.** A simulação subestima sistematicamente a exposição
do manguezal: nos cenários AR6 até 2100 o mangue aparece praticamente intocado
(0,9 % abaixo de +1 m; 2,7 % abaixo de +2 m), o que é resultado do MDE, não do clima.
O apicum, medido corretamente, responde como esperado: **55,6 % abaixo de +2 m** e
**91,4 % abaixo de +3 m**. Qualquer leitura de resposta ecológica na Parte 2 tem que
partir daí — a Parte 2 não pode simplesmente cruzar máscara de inundação com a classe
Mangue e reportar o número.

| Fração da classe abaixo da cota (MDE completo, 05/09/2026) | ≤0,5 m | ≤1 m | ≤2 m | ≤3 m |
|---|---:|---:|---:|---:|
| Mangue | 0,5 % | 0,9 % | 2,7 % | 19,1 % |
| Apicum | 0,1 % | 1,1 % | **55,6 %** | **91,4 %** |
| Restinga Herbácea/Arbustiva | 0,0 % | 0,1 % | 2,0 % | 9,8 % |
| Restinga Arbórea | 0,0 % | 0,0 % | 0,1 % | 0,9 % |
| Campo Alagado e Área Pantanosa | 0,0 % | 0,1 % | 8,4 % | 23,7 % |
| Praia, Duna e Areal¹ | 3,8 % | 6,2 % | 11,8 % | 18,8 % |

¹ *Única linha que divergiu do cálculo anterior com o MDE leve (que dava 5,3 / 8,8 /
16,8 / 26,5 %) — as demais bateram na casa decimal. Causa identificada, não é
indefinição: os dois caminhos de leitura do MDE tratam o zero do FABDEM de forma
diferente. `slr_core.carregar_dem` (modo local, float32) aplica `dem == 0.0 → NaN` —
a convenção de oceano do FABDEM — e os pixels de Praia/Duna que caem exatamente em
0,0 m saem da amostra. `fonte_dados.carregar_dem_auto` (modo web, int16 em cm)
desliga esse teste de propósito: em cm ele apagaria terreno real próximo de zero, e
o oceano ali já vem como nodata explícito (gravado assim por `03_prepara_dem_web.py`),
então não precisa do teste de novo. Por isso o modo web mantém mais pixels de
Praia/Duna na amostra e a fração nas caudas baixas sai maior — e por isso só essa
classe é afetada: é a única colada na linha d'água (só 70,9 % dos seus pixels têm z
válido). Mangue, Apicum e Restinga não têm pixels em 0,0 m, então nenhum dos dois
caminhos os toca. A mediana de Praia/Duna não muda (5,40 m nos dois). Os números
locais desta tabela são os **conservadores** (amostra menor, sem os pixels em zero);
os do modo web são os **generosos** nessa classe — nenhum dos dois está errado, são
recortes diferentes da mesma borda água–terra.*

### 4.5 A CONFERIR — eucalipto na margem do manguezal

O laudo é repetitivo sobre isso: no rio Cupido, "a plantação de eucalipto encontra-se
muito próxima à margem do rio", com o manguezal reduzido a "uma estreita faixa"
(figuras 87 a 93, pontos C3 a C9).

O raster não reproduz: a Silvicultura está a **13,9 km do mangue na mediana**, e apenas
**0,1 %** dos seus pixels ficam a ≤ 150 m de mangue. Apenas 0,3 % dos pixels de mangue
têm silvicultura na vizinhança de 150 m.

Três hipóteses, nenhuma testada ainda:

1. **Recuo real.** O laudo é anterior à criação da RESEX; o plantio junto à margem pode
   ter sido retirado ou substituído desde então. O MapBiomas seria simplesmente atual.
2. **Rio Cupido fora do recorte.** O BBOX do projeto vai até −18,05°; se os pontos C3–C9
   estiverem ao sul disso, o teste não os viu.
3. **Faixa estreita demais para 30 m.** Uma orla de mangue de 20–30 m de largura é
   sub-pixel e vira a classe vizinha na classificação.

Resolver a hipótese 2 é barato (localizar o rio Cupido) e vale fazer antes de escrever
qualquer coisa sobre pressão de silvicultura no relatório.

### 4.6 A CONFERIR — as restingas inundadas viraram "Campo Alagado"?

O laudo separa em campo pelo menos quatro fitofisionomias de restinga inundada
(herbácea fechada inundada, arbustiva aberta inundada, arbustiva de moitas, mata
inundada). O MapBiomas tem duas classes de restinga (arbórea, herbácea/arbustiva) e uma
classe genérica **Campo Alagado e Área Pantanosa** — que, com 307 km², é a 4ª maior do
recorte e, na figura, ocupa boa parte da mesma planície.

Suspeita: parte das restingas inundadas do laudo está sendo classificada como Campo
Alagado, e não como restinga. Isso não é erro do MapBiomas (a legenda dele é nacional e
não tem por que replicar a taxonomia de restinga do laudo), mas **muda o número** se a
Parte 2 tratar "restinga" e "campo alagado" como respostas ecológicas diferentes.
Pendência: decidir se as duas classes entram agrupadas na resposta ecológica.

## 5. Conclusão

A camada de cobertura **passa** na validação qualitativa como camada de cobertura: as
classes costeiras estão nos lugares certos, na vizinhança certa, e a ausência de
aquicultura é consistente com a história da área. As duas ressalvas de taxonomia
(4.5, 4.6) são de escopo, não de erro.

O que **não passa** é a leitura conjunta com o FABDEM sobre manguezal. O viés de dossel
sobre mangue é grande o bastante — ordem de 3 m — para inverter a posição relativa de
duas feições cuja diferença real é decimétrica, e é maior que todo o NMRM projetado
para 2100. Enquanto isso não for corrigido, **a ferramenta não deve reportar área de
manguezal perdida por cenário**, e a Parte 2 precisa de um caminho alternativo para o
mangue (correção por altura de dossel, MDE alternativo em área de mangue, ou tratar o
manguezal por regra ecológica em vez de por cota).

Isso também é a confirmação empírica, dentro do próprio projeto, da regra 2 do
`CLAUDE.md`: se o FABDEM — que já removeu dossel — ainda erra 3 m sobre manguezal, um
SRTM ou tile Terrain-RGB genérico erraria mais.

## 6. Pendências geradas

- [ ] Obter os limites vetoriais da RESEX Cassurubá e dos sub-sistemas (ICMBio) para
      trocar as faixas de latitude por setores reais.
- [ ] Localizar o rio Cupido e verificar se está dentro do BBOX (hipótese 2 de 4.5).
- [x] Reprocessar as estatísticas de elevação em modo local, sem o teto de +20 m —
      feito em 05/09/2026 (`05_valida_cobertura_elevacao.py`); confirma o achado
      original. (Também explicou a diferença de Praia/Duna entre modo local e
      web — tratamento do zero do FABDEM, não indefinição; ver nota da tabela em 4.4.)
- [ ] Decidir o tratamento do mangue na Parte 2, dado o viés de dossel.
- [ ] Decidir se Campo Alagado entra agrupado com restinga na resposta ecológica.

---

*Fontes: MapBiomas Brasil, Coleção 11 (2025); FABDEM V1-2 (Hawker et al. 2022, ERL
17:024016); Laudo biológico do sistema Caravelas–Nova Viçosa (RESEX Cassurubá);
Hutchings & Saenger (1987) apud laudo; Andrade et al. (2003).*
