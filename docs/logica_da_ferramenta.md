# A lógica por trás do simulador de NMRM — Caravelas (BA)

**Projeto 26.09** · Ecossistemas Marinhos Costeiros — UERJ / FAOC / DOB
Documento de apoio à apresentação · escrito na v1.2 (setembro de 2026) e revisado em 26/10/2026 para a v3.2

---

## 1. O que a ferramenta responde, e o que ela não é

A pergunta é: **onde a água chegaria, na planície de Caravelas, se o nível
médio relativo do mar subisse X metros?**

A resposta que ela dá é **exposição potencial**, não previsão de inundação.
A diferença não é retórica. Previsão exigiria resolver hidrodinâmica, atrito,
propagação de maré no estuário, ondas, drenagem e resposta do sedimento.
A ferramenta não resolve nada disso: ela responde a uma pergunta geométrica —
*que terreno fica abaixo de uma dada cota d'água e tem caminho físico até o
mar?* É a camada de **Exposição** da cadeia da disciplina:

```
Cenário → EXPOSIÇÃO → Processo → Resposta ecológica → Serviço → Sociedade → Adaptação
```

Tudo o que vem depois da segunda caixa é interpretação nossa. O mapa é
insumo para a hipótese ecológica, não a conclusão dela.

---

## 2. A cadeia de decisões, em cinco passos

Toda simulação percorre a mesma sequência. Vale ter isso na cabeça ao
apresentar, porque cada passo é uma escolha metodológica defensável — e cada
um deles é onde o resultado pode ser questionado.

| # | Passo | Pergunta que responde |
|---|-------|----------------------|
| 1 | **Terreno** | Qual é a altura do chão, e em relação a quê? |
| 2 | **Cota** | Qual altura a água atinge, e como ela foi composta? |
| 3 | **Corte** | Que pixels estão abaixo dessa cota? |
| 4 | **Conectividade** | Desses, quais a água realmente alcança? |
| 5 | **Contagem** | Quantos km² isso representa? |

---

## 3. Passo 1 — O terreno: por que FABDEM

Usamos o **FABDEM V1-2** (Hawker et al. 2022, *ERL* 17:024016), a ~30 m,
reprojetado para SIRGAS 2000 / UTM 24S (EPSG:31984).

O FABDEM é o Copernicus GLO-30 com **dossel de vegetação e edificações
removidos por machine learning**. Essa escolha não é detalhe: modelos globais
de elevação são *modelos de superfície* — em manguezal denso eles medem o topo
das árvores, não o solo. Um erro de altura de dossel de 5 a 10 m em cima de um
sinal de NMRM de 0,5 a 1 m tornaria o exercício inteiro sem sentido.

**Por isso o projeto proíbe** trocar por SRTM, Copernicus bruto ou tiles
Terrain-RGB genéricos dos simuladores online. Numa planície com manguezal, o
viés de dossel é maior que o próprio fenômeno simulado.

O que o FABDEM **não** resolve: sobra incerteza vertical de ordem decimétrica
a métrica, comparável aos incrementos de NMRM que estamos simulando. Isso é
limitação declarada, não defeito escondido.

---

## 4. Passo 2 — A cota: a parte que mais confunde

A cota d'água é uma soma explícita:

```
cota = NMRM (cenário) + maré (datum) + (nível médio − geoide) + sobrelevação
```

A ferramenta mostra essa decomposição na aba **Metadados**, parcela por
parcela, justamente para que ninguém cite um número sem saber o que ele
contém. Por padrão, duas dessas quatro parcelas valem zero (a diferença entre o nível
médio e o geoide, e a sobrelevação meteorológica, que é um campo opcional) —
e é importante saber **por quê**.

### O que significa "nível médio" aqui

Esta é a pergunta que mais aparece, e a resposta honesta é:
**o nível médio não foi calculado — ele foi herdado.**

O FABDEM é referenciado ao geoide **EGM2008**. A simulação corta o terreno em
z = 0 m nesse datum. Ou seja, assumimos:

> nível médio local ≈ geoide EGM2008

Isso é uma **aproximação**, não uma medida. A diferença real entre o geoide e
a superfície média do mar é a **topografia dinâmica média (MDT)** — o desnível
sustentado por correntes, vento e gradientes de densidade. No Atlântico Sul
tropical ela é de ordem decimétrica, ou seja, **da mesma ordem do NMRM
projetado para 2050**. Fechar esse offset depende de CMEMS/DTU ou de
nivelamento geodésico amarrado ao marégrafo.

### De onde vem a maré (atualizado em 22/09/2026)

Até 22/09/2026 nenhuma constante harmônica tinha sido usada: PM, PMS e HAT
viviam em `0,00 m`, marcados `PROVISORIO`, à espera do **BNDO/CHM** ou do
catálogo FEMAR. Isso mudou — os cinco datums de `NIVEIS_MARE` (NM, PMQ, PM,
PMS, HAT) agora vêm do **TPXO9-atlas v5** (OSU), extraídos por
`07_mare_tpxo.py` a partir de 8 constituintes harmônicos num ponto ao largo
da barra de Caravelas. PMQ (preamar de quadratura) é nível novo, incluído
para a turma comparar sizígia x quadratura.

Isso NÃO é a mesma coisa que uma constante de **marégrafo**. TPXO é um
modelo global assimilado a altimetria de satélite e a marégrafos — não é
uma medição em Caravelas — e a célula usada tem ~3,7 km, representando a
condição **ao largo da barra**, não dentro dos canais do estuário
Caravelas–Peruípe (amplificação e defasagem de maré no estuário não estão
representadas). Por isso `NIVEIS_MARE["MEDIDA"] = False`, e a procedência (modelo, não medição)
é declarada na página **Metadados** e na seção "O que esta ferramenta NÃO diz"
da página Turma.

Isso segue a regra de conduta nº 1 do projeto: **nunca inventar valor de
maré, datum ou projeção local.** Antes disso significava manter tudo em
`0,00 m` sinalizado; agora significa usar um valor real, mas continuar
sinalizando sua procedência (modelo, não medição) em vez de apresentá-lo
como se fosse constante de marégrafo. A solicitação ao BNDO/CHM continua em
aberto — é a única fonte que tornaria `MEDIDA = True`.

**Consequência prática para a apresentação:** os mapas no datum NM continuam
mostrando a planície no nível médio, como antes. Selecionar PMS agora soma
+1,244 m de verdade à cota — uma preamar de sizígia sobe a cota antes mesmo
de qualquer mudança climática, e esse efeito passou a aparecer no mapa.

**O que isto não resolve:** o datum VERTICAL do MDE. O FABDEM segue em
EGM2008, e a diferença entre o geoide e a superfície média do mar real
(topografia dinâmica média) segue desconhecida — `OFFSET_GEOIDE_NM_M`
continua `0,00`. É um problema independente da maré (ver seção anterior);
a troca do TPXO não o resolve.

---

## 5. Passos 3 e 4 — O corte e a conectividade: o diferencial

Aqui está o que separa esta ferramenta dos simuladores online.

O corte simples é trivial: marque todo pixel com elevação ≤ cota. É o método
conhecido como **"bathtub"** (banheira) — enche tudo que está abaixo da linha,
como se a paisagem fosse uma bacia sendo preenchida.

O problema é que **estar abaixo da cota não significa que a água chega lá**.
Uma depressão atrás de um cordão litorâneo pode estar 50 cm abaixo do nível do
mar e continuar seca, porque não existe caminho físico entre ela e o oceano.

Então a ferramenta faz um passo a mais. Ela rotula os componentes conexos do
conjunto *(terreno abaixo da cota) ∪ (água atual)* com vizinhança de 8, e
pergunta de cada mancha: **ela toca o oceano, o estuário, ou a borda do
recorte?** Se sim, é `inundada`. Se não, é `depressão isolada` — uma classe
separada, com cor própria, **nunca somada à área inundada**.

### O que isso muda, em números

Recorte de Caravelas, 2.440,9 km² de área emersa, nível médio, sem maré:

| Cota | Inundada (conectada) | Depressão isolada | Bathtub ingênuo |
|-----:|---------------------:|------------------:|----------------:|
| +0,5 m | 4,3 km² | 0,6 km² | 4,9 km² |
| +1,0 m | 7,0 km² | 1,5 km² | 8,5 km² |
| +1,5 m | 10,9 km² | 14,7 km² | 25,6 km² |
| +2,0 m | **27,8 km²** | **43,3 km²** | **71,1 km²** |
| +3,0 m | 119,6 km² | 75,0 km² | 194,6 km² |

**Leia a linha de +2 m.** Um simulador bathtub pintaria 71 km² de azul.
Desses, apenas 28 km² têm caminho hidráulico até o mar — **61% do que seria
mostrado como inundação não é inundação**, é depressão fechada.

Repare também no salto entre +1,0 e +1,5 m: a área isolada pula de 1,5 para
14,7 km². Isso é a assinatura geomorfológica da planície — os cordões
litorâneos quaternários funcionam como diques, e as intercordões alagam por
trás deles antes de qualquer conexão se abrir. É exatamente o tipo de leitura
que um mapa bathtub apaga.

### A honestidade da classe "isolada"

A classe isolada é um **limite superior** do que "não alaga de verdade". Dois
motivos:

1. Canais e gamboas mais estreitos que um pixel (30 m) podem não estar na
   máscara de água, então uma conexão real pode passar despercebida.
2. A ferramenta não modela infiltração, lençol freático nem galgamento por
   onda — uma depressão "isolada" pode salinizar por baixo sem nunca receber
   água por cima.

Ou seja: a verdade está entre as duas colunas, mais perto da coluna
"inundada". O ponto não é que o número isolado seja irrelevante — é que somá-lo
à inundação, como fazem os simuladores online, é **errado na direção do
alarme**.

---

## 6. Passo 5 — Da máscara ao número

Cada pixel de 30 × 30 m vale 900 m², ou **0,09 hectare**. Contar pixels e
multiplicar dá a área. Simples — com um cuidado.

O controle **"área mínima de mancha"** existe porque a incerteza vertical do
FABDEM, numa planície tão plana, produz pixels soltos abaixo da cota que não
correspondem a feição real. Definir 0,5 ha, por exemplo, descarta toda mancha
contígua com menos de ~6 pixels, nas duas classes. O padrão é **zero** — não
filtramos nada por default, para não maquiar o resultado sem o usuário saber.

Uma ressalva para a apresentação: a coluna "% da área emersa" fica pequena
(1,1% em +2 m) porque o recorte de 2.441 km² inclui o platô do Grupo
Barreiras, terreno alto que jamais alagaria. **O número em km² é o que
importa** para a planície; a porcentagem está diluída pela extensão do
recorte.

### O limite da turma é desenho, não derivação (v1.5)

`limite_turma.geojson` **não é calculado por este projeto**. É a área de estudo
que a turma desenhou no QGIS, sobre a batimetria (isóbata de 500 m) e os
limites das unidades de conservação. `09_limite_turma.py` só converte o
shapefile para GeoJSON, com conferências: para se o .prj for projetado,
corrige anel auto-interceptante com `buffer(0)` e para se a correção mexer
mais de 1 km² de área, descarta feição contida em outra e para em sobreposição
parcial. O shapefile de origem é versionado em `dados_web/fonte_limite_turma/`,
porque é trabalho manual e insubstituível — se sumir, a definição da área some
junto. Para mudar a área: redesenhar no QGIS, substituir o shapefile e rodar o
`09`. Nunca editar o GeoJSON à mão.

Ele substituiu, em 24/09/2026, a camada `area_turma.geojson` (21.955 km²), um
contorno provisório que fechava a oeste numa reta vertical em -39,59° — a borda
oeste do domínio do MDE — e por isso continha 97,5 % da terra do domínio:
recortar por ela não recortava nada de útil. Aquela camada foi REMOVIDA do
projeto (arquivo, constantes e controle na interface); quem precisar dela pega
no histórico do git. O limite desenhado acompanha o contorno das UCs, que segue
a costa e entra no estuário: 18,5 % da terra, 450,5 km².

### Recorte à área da turma: a ordem importa (v1.5)

No modo de uso **Turma** a análise é recortada à área de estudo da turma. No
modo **Livre** nada é recortado: vale o domínio inteiro do MDE, como em todas
as versões anteriores. A ordem das operações é a parte que não pode ser
trocada:

1. **Conectividade** — resolvida no domínio INTEIRO do MDE (flood-fill no modo
   local; `limiar_conexao_web.tif`, pré-computado sobre o domínio inteiro, no
   modo web).
2. **Recorte** — só depois, na hora de contar, de desenhar e de exportar.

Se o MDE fosse recortado antes do passo 1, a água que entra pela borda do
recorte deixaria de ter caminho até o mar e a ferramenta inventaria depressões
"isoladas" que não são. Por isso o recorte é **de relato, não de cálculo**.

Em números, medido em 24/09/2026 sobre `dados_web/` (o recorte leve que a
ferramenta publicada lê, 30 m), com conectividade ligada e mancha mínima de
1 ha:

| cota | domínio inteiro (modo Livre) | dentro da área de estudo (modo Turma) | da inundação do domínio |
|------|------------------------------|---------------------------------------|-------------------------|
| terra | 2.440,9 km² | **450,5 km² (18,5 %)** | — |
| +1,00 m | 5,01 km² (0,21 %) | 4,47 km² (**0,99 %**) | 89 % |
| +2,00 m | 26,52 km² (1,09 %) | 23,02 km² (**5,11 %**) | 87 % |
| +3,00 m | 118,77 km² (4,87 %) | 78,23 km² (**17,37 %**) | 66 % |

O recorte fica com 18,5 % da terra e **captura 87–89 % da inundação** nas cotas
que interessam. É esse o ganho: o que sai é o platô do Grupo Barreiras, terreno
alto que não alaga em cenário nenhum e que só servia para diluir a
porcentagem — o problema descrito duas seções acima. A +2,00 m a leitura passa
de "1,1 % da área" para "5,1 % da área de estudo da turma", e as duas frases
descrevem exatamente os mesmos 23 km² de terra alagada.

A partir de +3,00 m a captura cai para 66 %: acima dessa cota a inundação começa
a avançar para dentro da planície, fora da área de estudo. Vale lembrar que
+3,00 m já está fora da faixa do AR6 — ali o mapa é teste de sensibilidade do
terreno, não cenário climático.

### O recorte é duro: o de fora não é desenhado

No modo Turma a ferramenta mostra **só o que está dentro da área de estudo** —
na figura e no mapa interativo. Não há fantasma esmaecido do lado de fora: o
terreno fora do polígono simplesmente não é desenhado
(`CONFIG_MAPA["alpha_fora_recorte"] = 0,0`; um valor maior o traz de volta, e
aí o item de legenda correspondente reaparece sozinho).

Três detalhes que não são óbvios e que alguém vai querer "simplificar" um dia:

- **O fundo do eixo deixa de ser o oceano.** Sem recorte, o fundo da figura É
  `cor_oceano` e o raster inteiro é o mapa. Com recorte isso não pode: a
  planície continental que fica de fora apareceria pintada de azul-oceano, e
  terra alta lida como mar é o pior erro que este mapa poderia cometer. Então
  o fundo vira o papel da figura e o oceano passa a ser uma camada desenhada
  só DENTRO do recorte.
- **A escala de cor do hipsométrico olha só para dentro.** O percentil 99,5
  que define o topo da rampa é calculado sobre o terreno recortado. Caso
  contrário o platô do Grupo Barreiras continuaria esticando a rampa de um
  terreno que nem aparece no mapa.
- **Nas isolinhas, a ordem das operações importa.** O NaN do recorte entra
  DEPOIS do preenchimento de oceano e DEPOIS da suavização gaussiana. Antes do
  preenchimento, a borda do corte viraria uma isolinha de 0,5 m falsa
  acompanhando o recorte; antes da suavização, o gaussiano espalharia NaN por
  toda a vizinhança do kernel e comeria isolinha boa lá dentro.

No mapa interativo, além da exposição, passaram a ser recortadas a camada
topográfica, as isolinhas e a cobertura MapBiomas — antes vinham do domínio
inteiro e desenhavam relevo que não entra em conta nenhuma. E o clique fora do
recorte não devolve cota, faixa nem classe: devolve "fora da área de estudo".
Mostrar "3,4 m, acima da cota" num pixel que não entra em conta nenhuma
convidaria a ler aquilo como resultado da análise.

### O quadro da figura é o polígono, não a grade

A figura é desenhada em coordenadas de PIXEL da grade do FABDEM — é o que
permite `imshow` e geometria vetorial conviverem no mesmo eixo. Isso NÃO
limita o quadro à grade: a conversão geo->pixel é uma afim e continua valendo
fora dela, com coordenadas negativas ou maiores que a largura. Por isso o
enquadramento vem do bbox do POLÍGONO da área de estudo
(`_bbox_pixel_geojson`), não do bbox da máscara rasterizada, que seria
recortada pela grade e devolveria o retângulo do MDE.

Pelo mesmo motivo o mar dentro da área de estudo é desenhado como POLÍGONO
(`_preencher_geojson`), não como imagem sobre a grade: uma imagem pararia na
borda do raster e deixaria um retângulo azul de canto reto, com cara de dado.

O quadro cobre de -39,49° a -37,24°, cerca de 240 km. Três consequências, todas
tratadas: a figura é reproporcionada ao quadro mantendo a mesma área em
polegadas (teto de aspecto 2,4); a barra de escala escolhe um valor redondo da
série 1-2-5 proporcional à largura (50 km aqui, 10 km na planície); e a legenda
sai para uma faixa abaixo do mapa, porque no canto ela cobria o traçado do
limite.

**A conta a pagar:** a planície de Caravelas ocupa cerca de 8 % da largura
desse quadro. Mostrar a área de estudo como ela é — quase toda plataforma —
custa a leitura fina da exposição. Por isso o enquadramento é escolha, não
decisão fixa: os **Ajustes avançados** oferecem **Área de estudo inteira** e **Só a
planície (onde há MDE)**, com padrão na segunda. **Enquadramento não é
recorte** — os dois contam exatamente os mesmos km², e o que muda é só o que
entra no quadro. Num relatório, as duas juntas contam a história inteira: a
geral situa a área de trabalho, a de detalhe mostra onde a água chega.

O rodapé declara o que os km² são. Nada disso mexe nos NÚMEROS: o recorte já
valia na contagem desde a primeira versão.

Os km² do modo Turma são a **terra** da área de estudo que o MDE cobre. Não são
os ~16.255 km² de extensão do polígono: a maior parte dele é plataforma
continental, onde o FABDEM não distribui tile e não há o que medir.

---

## 7. De onde vêm os cenários

Três origens, com status bem diferentes:

**Cenários IPCC AR6.** Vêm da Tabela 9.9 do AR6 WGI, Cap. 9 (Fox-Kemper et al.
2021): mediana e faixa provável (17–83%), base 1995–2014. **Nada foi calculado
por nós** — a ferramenta apenas soma o valor à cota. O problema é que esses
números são **NMGM, o nível médio GLOBAL**, e a disciplina pede **NMRM,
relativo local**. Eles não incluem movimento vertical da terra, impressão
digital gravitacional do degelo, nem variação estérica regional. Por isso,
**desde a v3.0 os cenários AR6 aparecem nas duas páginas de simulador, sempre
rotulados como nível GLOBAL (NMGM)**, com o sufixo "(NMGM)" no nome do cenário:
oferecer um valor global como se fosse local seria o mesmo erro de inventar um
datum, então o que mudou foi declarar a procedência, não escondê-la. A substituição virá do NASA/IPCC AR6 Sea Level Projection
Tool (Garner et al., Zenodo 10.5281/zenodo.5914709), no grid point de
Caravelas.

**Níveis da turma (+0,5 / +1 / +2 m).** Não são projeções — são **cotas
declaradas**, escolhidas para teste de sensibilidade espacial. Não têm
problema de procedência, e é por isso que seguem disponíveis ao público.

**Modo manual (0 a 10 m).** Livre. Acima de +3 m a interface avisa que a
simulação saiu da faixa do AR6 (o máximo projetado para 2100 é +1,60 m, no
SSP5-8.5 de baixa confiança, percentil 83) e passa a valer como teste de
sensibilidade do terreno — ou como comparação com os **paleoníveis holocênicos
da própria planície**, que Andrade et al. (2003) situam em +4,8 / +3,5 /
+2,5 m. Essa comparação é interessante: a planície de Caravelas *já esteve*
sob níveis mais altos, e os cordões que vemos hoje são o registro dessa
regressão.

---

## 8. O que a ferramenta não faz

Vale dizer isso em voz alta na apresentação, antes que perguntem:

- **Não resolve hidrodinâmica.** Sem atrito, sem tempo de propagação, sem
  atenuação da maré estuário adentro.
- **Não tem resposta morfodinâmica.** Manguezal acresce verticalmente com o
  nível do mar; duna migra; a planície é progradante e recebe sedimento. Nada
  disso é representado — o que tende a **superestimar** a perda.
- **Não modela ondas, galgamento nem drenagem.**
- **Não distingue tipo de cobertura.** O cruzamento com MapBiomas é a Parte 2.
- **Não é previsão.** Cenário não é previsão; projeção não é mapa final;
  NMRM não é média global.

---

## 9. Como ler um mapa da ferramenta em trinta segundos

1. **Leia o rodapé primeiro.** Ele traz a cota total, o datum vertical e a
   projeção. Sem isso o mapa não significa nada.
2. **Azul** = inundação conectada ao mar. É o número que vale.
3. **Roxo** = abaixo da cota, sem conexão hidráulica. É a coluna que os
   simuladores online somariam ao azul.
4. **Azul-escuro** = oceano/estuário atual, o ponto de partida.
5. **Confira o subtítulo:** ele diz se o teste de conectividade está ligado.
   Desligado, você está vendo um bathtub — útil só para comparação.

---

## 10. O que falta (roadmap honesto)

| Pendência | Por que importa |
|---|---|
| Constantes harmônicas do BNDO/CHM | Troca a maré de modelo (TPXO) pela de marégrafo e resolve o estuário. Caminho crítico. |
| Offset geoide → nível médio local | Corrige o datum vertical na ordem de decímetros. |
| NMRM local do AR6 Sea Level Tool | Substitui o global pelo relativo, que é o que a disciplina pede. |
| Cruzamento com MapBiomas | Parte 2 — transforma exposição física em resposta ecológica. |

---

## Referências

- Hawker, L., Uhe, P., Paulo, L., Sosa, J., Savage, J., Sampson, C., Neal, J.
  (2022). A 30 m global map of elevation with forests and buildings removed.
  *Environmental Research Letters*, 17, 024016.
- Fox-Kemper, B. et al. (2021). Ocean, Cryosphere and Sea Level Change.
  In: *Climate Change 2021: The Physical Science Basis*. IPCC AR6 WGI, Cap. 9.
- Garner, G. G. et al. (2021). IPCC AR6 Sea Level Projections.
  Zenodo, 10.5281/zenodo.5914709.
- Andrade, A. C. S., Dominguez, J. M. L., Martin, L., Bittencourt, A. C. S. P.
  (2003). Quaternary evolution of the Caravelas strandplain – Southern Bahia
  State – Brazil. *Anais da Academia Brasileira de Ciências*, 75(3), 357-382.

---

*Nota de revisão: o SSP5-8.5 (0,23 m em 2050; 0,77 m em 2100) foi verificado
contra o Sumário Executivo do Capítulo 9. Em 26/10/2026 as quatro linhas da
tabela do código (SSP1-2.6, SSP2-4.5, SSP5-8.5 e SSP5-8.5 baixa confiança)
foram conferidas contra uma reprodução secundária da Tabela 9.9 (Hong Kong
Observatory) e batem; falta conferir contra a tabela impressa do capítulo antes
de citar no relatório final.*
