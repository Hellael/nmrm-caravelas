# A lógica por trás do simulador de NMRM — Caravelas (BA)

**Projeto 26.09** · Ecossistemas Marinhos Costeiros — UERJ / FAOC / DOB
Documento de apoio à apresentação · versão 1.2 · setembro de 2026

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
representadas). Por isso `NIVEIS_MARE["MEDIDA"] = False` continua exibindo
tarja de aviso na interface — agora permanente, e por outro motivo.

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
