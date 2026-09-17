# A lógica por trás do simulador de NMRM — Caravelas (BA)

**Projeto 26.09** · Ecossistemas Marinhos Costeiros — UERJ / FAOC / DOB
Documento de apoio à apresentação · versão 1.4b · setembro de 2026

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
contém. Na v1.2, três dessas quatro parcelas valem zero — e é importante
saber **por quê**.

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

### Por que a maré está zerada

Nenhuma constante harmônica foi usada. Os datums PM (preamar média), PMS
(sizígia) e HAT (maior maré astronômica) estão em `0,00 m`, marcados como
`PROVISORIO`, à espera dos dados do **BNDO/CHM** ou do catálogo FEMAR.

Isso segue a regra de conduta nº 1 do projeto: **nunca inventar valor de maré,
datum ou projeção local.** Um número inventado num mapa vira citação em
relatório. Por isso, na versão pública, o seletor de maré aparece travado em
"Nível médio" com os demais níveis visíveis mas desabilitados — o usuário vê
que existem e que estão em desenvolvimento.

**Consequência prática para a apresentação:** os mapas mostram a planície
*no nível médio*. Uma preamar de sizígia sobe a cota antes mesmo de qualquer
mudança climática. O mapa atual é, nesse sentido, **conservador**.

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
conjunto *(terreno abaixo da cota) ∪ (água de área) ∪ (margem d'água real) ∪
(canal MapBiomas, até +6,0 m)* com vizinhança de 8, e pergunta de cada
mancha: **ela toca o oceano, o estuário, ou a borda do recorte?** Se sim, é
`inundada`. Se não, é `depressão isolada` — uma classe separada, com cor
própria, **nunca somada à área inundada**. A margem e o canal entram só como
**caminho**: eles deixam a água atravessar, mas — ao contrário do
oceano/estuário — nunca são eles próprios a fonte que injeta água (uma
lagoa interior sem ligação com o mar, classe 33, não pode virar conexão
falsa só por estar na mesma classe; ver `docs/v1.4_notas_tecnicas.md` para a
distinção entre as duas máscaras de água).

### O que isso muda, em números

A v1.4b corrigiu a conectividade em duas frentes (ver
`docs/v1.4_notas_tecnicas.md` para o detalhe técnico e para uma etapa
intermediária testada e descartada no caminho):

1. A máscara de água passa a ser detectada na grade nativa, antes da
   reprojeção — e reprojetada em **duas** versões: `agua_area`
   (`Resampling.average` ≥ 0,5, decide o que sai da terra) e `agua_conexao`
   (`Resampling.max`, decide o que conduz conexão). A diferença é a MARGEM
   d'água real — fica terra, mas conduz.
2. Canais do MapBiomas (classe 33, até +6,0 m de cota) funcionam como
   caminho hidráulico adicional — conduzem a água sem serem fonte.

Por isso a tabela abaixo tem duas colunas de inundada: **sem canais**
(margem d'água real, sempre ativa) e **com canais** (margem + canal
MapBiomas, comportamento ligado por padrão na interface). A v1.3 entra só
como referência histórica — os números que a turma viu na apresentação de
05/09 vinham, em boa parte, do bug de reprojeção da máscara de água
corrigido nesta versão, não de um sinal físico novo.

Recorte de Caravelas, área emersa 2.440,9 km² (v1.3, referência histórica) →
**2.429,4 km² (v1.4b)**, nível médio, sem maré:

| Cota | Inundada v1.3 | Inundada v1.4b sem canais | Inundada v1.4b com canais | Isolada v1.3 | Isolada v1.4b com canais | Bathtub v1.3 | Bathtub v1.4b |
|-----:|---:|---:|---:|---:|---:|---:|---:|
| +0,5 m | 4,29 | 0,58 | 0,69 | 0,57 | 0,14 | 4,86 | 0,83 |
| +1,0 m | 6,98 | 0,94 | 1,19 | 1,53 | 0,70 | 8,50 | 1,89 |
| +1,5 m | 10,84 | 2,32 | 4,80 | 14,33 | 11,41 | 25,17 | 16,21 |
| +2,0 m | 27,59 | 17,68 | **19,87** | 43,02 | **39,94** | 70,62 | 59,81 |
| +3,0 m | 119,29 | 107,42 | 140,18 | 74,69 | **41,58** | 193,98 | 181,77 |

**Leia a linha de +3 m.** Sem canal MapBiomas, 74,7 km² ficariam
classificados como depressão isolada. Com canal — a mesma planície, só que
reconhecendo que o rio e seus afluentes conduzem água mesmo onde o FABDEM
não zera a cota — 33,1 km² dessa área na verdade tem caminho até o mar, e a
área isolada cai para 41,6 km². Em +1,5 m o efeito já aparece: a área
isolada cai de 14,3 para 11,4 km², porque é ali que os cordões litorâneos
começam a ser transpostos pelos canais que os cruzam.

Um achado que vale registrar: a coluna "Isolada com canais" sai **idêntica**
entre a etapa intermediária (só `Resampling.max`, descartada) e a v1.4b
final, em toda cota testada. Não é porque as depressões isoladas ficam
"longe" da correção da máscara — é porque todo pixel de margem, por
definição, já encosta fisicamente na água: se ele está abaixo da cota,
conecta na hora, não importa qual das duas máscaras de área está em uso. A
margem nunca alcança uma depressão interior isolada por um cordão litorâneo;
ela só estende a conexão um pixel além da própria água. Quem muda a área
isolada é o canal MapBiomas (que pode atravessar um cordão inteiro), não a
margem.

### A honestidade da classe "isolada"

A classe isolada é um **limite superior** do que "não alaga de verdade". Dois
motivos:

1. A v1.4b tratou o caso mais grosseiro (canal MapBiomas até 30 m de
   largura, como caminho hidráulico até +6,0 m) e corrigiu a máscara de água
   na grade nativa, separando o que sai da área (`agua_area`) do que conduz
   conexão (`agua_conexao`/margem) — canais de 1–2 px que antes
   desapareciam na reamostragem agora sobrevivem como margem. O que sobra:
   gamboas mais estreitas que 1 pixel nativo de qualquer forma, e o degrau
   de dossel de mata ciliar/mangue nas margens de canal (o FABDEM ainda mede
   o topo da vegetação ribeirinha, não o solo) — nenhum dos dois foi
   corrigido, por decisão (ver `docs/v1.4_notas_tecnicas.md` §9).
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

---

## 7. De onde vêm os cenários

Três origens, com status bem diferentes:

**Cenários IPCC AR6.** Vêm da Tabela 9.9 do AR6 WGI, Cap. 9 (Fox-Kemper et al.
2021): mediana e faixa provável (17–83%), base 1995–2014. **Nada foi calculado
por nós** — a ferramenta apenas soma o valor à cota. O problema é que esses
números são **NMGM, o nível médio GLOBAL**, e a disciplina pede **NMRM,
relativo local**. Eles não incluem movimento vertical da terra, impressão
digital gravitacional do degelo, nem variação estérica regional. Por isso,
**na versão pública os cenários AR6 estão marcados como "em desenvolvimento"**:
oferecer um valor global rotulado como cenário local seria o mesmo erro de
inventar um datum. A substituição virá do NASA/IPCC AR6 Sea Level Projection
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
| Constantes harmônicas do BNDO/CHM | Destrava PM, PMS e HAT. Caminho crítico. |
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
- Andrade, A. C. S. et al. (2003). Evolução quaternária da planície costeira de
  Caravelas, extremo sul da Bahia.

---

*Nota de revisão: os valores da Tabela 9.9 conferidos linha a linha até aqui
são os do SSP5-8.5 (0,23 m em 2050; 0,77 m em 2100), verificados contra o
Sumário Executivo do Capítulo 9. SSP1-2.6, SSP2-4.5 e SSP5-8.5 de baixa
confiança ainda merecem conferência na tabela impressa antes de irem para o
relatório final.*
