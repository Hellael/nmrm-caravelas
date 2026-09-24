# Diagnóstico dos pixels ==0.0 do FABDEM (máscara de oceano do `01_mapa_elevacao.py`)

**Script:** `diagnostico_zeros.py` (avulso, não faz parte do pipeline oficial)
**Execução:** 2026-08-26
**Figura:** [`saidas/diagnostico_zeros_20260826.png`](../saidas/diagnostico_zeros_20260826.png)

## Pergunta

O FABDEM codifica oceano como exatamente `0.0`. O `01_mapa_elevacao.py` trata
todo pixel `==0.0` como oceano e o mascara. A dúvida era se esse critério
também apaga, por coincidência de valor, manguezal ou planície de maré
legitimamente próximos da cota zero — o que inflaria artificialmente a área
"emersa" descartada e comprometeria qualquer métrica de exposição costeira
construída sobre o MDE.

## Método

Os pixels `==0.0` do mosaico reprojetado (antes de qualquer máscara) foram
separados por conectividade de 8-vizinhos, usando `src.slr_core.mascara_inundacao`
com a borda leste do recorte como única fonte de água:

- **Grupo (a):** conectado à borda leste → oceano aberto.
- **Grupo (b):** sem conexão com a borda leste → candidato a manguezal,
  planície de maré, laguna ou canal interno mascarado por engano.

Separadamente, a faixa de cota `0 < z ≤ 6 m` (terraços holocênicos, limite de
Andrade et al. 2003) foi dividida em contígua à costa (conectada ao oceano)
vs. confinada (fundos de vale sem conexão hidráulica).

## Resultado

| Grupo | Área | Observação |
|---|---|---|
| Total de pixels ==0.0 | 2.125,4 km² | antes de qualquer máscara |
| (a) oceano aberto, conectado à borda leste | 2.124,4 km² | 99,95% do total |
| (b) isolado, candidato a manguezal/maré/laguna/canal | **1,00 km²** | 289 manchas separadas |

| Faixa 0–6 m | Área | Observação |
|---|---|---|
| Contígua à costa (planície propriamente dita) | 586,37 km² | conectada ao oceano |
| Desconectada (fundos de vale no Barreiras) | 11,33 km² | confinada, fora dos tabuleiros |

## Conclusão

A máscara de oceano do `01_mapa_elevacao.py` (pixel `==0.0`) **não está
apagando manguezal ou planície de maré de forma significativa**. Do total de
2.125,4 km² classificado como oceano, apenas 1,00 km² (289 manchas pequenas
e espalhadas, ver mapa) não tem conexão hidráulica com a borda leste — o
restante é oceano aberto inequívoco. A limitação apontada no docstring do
`01_mapa_elevacao.py` é real, mas de magnitude marginal (~0,05% da área
mascarada), não uma incógnita que comprometa a Parte 1 do projeto.

Adicionalmente, dentro da faixa de cota 0–6 m há **11,33 km² de fundos de
vale desconectados**, encravados nos tabuleiros do Grupo Barreiras — terreno
baixo por relevo interno de drenagem, sem qualquer relação com exposição
costeira ao NMRM. Essas manchas devem ser **excluídas de qualquer métrica de
exposição costeira** (curva hipsométrica, matriz de cenários) para não
inflar artificialmente a área "vulnerável"; a área relevante para a Parte 1/2
do projeto é a faixa contígua de 586,37 km².

## Limitações deste diagnóstico

- Não resolve a origem física do grupo (b): pode ser manguezal real, ruído
  de borda de tile, corpo d'água interior codificado como 0.0 pelo processo
  de ML do FABDEM, ou combinação dos três — apenas quantifica a magnitude.
- A separação contígua/confinada da faixa 0–6 m usa a mesma cota fixa de
  6 m (Andrade et al. 2003) para toda a planície; não diferencia setores
  norte/sul do estuário Caravelas–Peruípe.
- Resultado condicionado à conectividade de 8-vizinhos e ao datum de maré
  usado na corrida (NM = 0,00 m por padrão). Desde 22/09/2026 `NIVEIS_MARE`
  vem do TPXO9-atlas v5, não mais de placeholder (`PROVISORIO` saiu do
  dicionário; ver `NIVEIS_MARE["MEDIDA"]`) — mas o nível médio (NM)
  continua em offset 0,00 m, então este diagnóstico não muda se rodado de
  novo com o datum padrão. Parâmetros centralizados em `src/slr_core.py`.
