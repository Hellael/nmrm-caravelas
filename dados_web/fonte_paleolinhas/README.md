# `dados_web/fonte_paleolinhas/` — origem das paleolinhas de costa

Insumo de `10_paleolinhas.py`, que fecha estas linhas em polígonos de terra
emersa e grava `dados_web/paleolinhas_turma.geojson`.

Mesma lógica de `fonte_limite_turma/`: **o que está aqui é trabalho manual
insubstituível e por isso é versionado no repositório**, não em
`NMRM_DIR_DADOS`. Se sumir, a reconstrução paleoambiental some junto.

## Arquivos

| arquivo | o que é |
|---|---|
| `estagios/estagio_<N>.shp` (+ `.shx`, `.dbf`, `.prj`, `.cpg`), N = I a VII | **As camadas de trabalho.** Uma por estágio, digitalizadas pela turma no QGIS sobre as Figs. 9 a 15 georreferenciadas (entregues em 01/10/2026). Camada de LINHA, EPSG:4326. O estágio sai do nome do arquivo; a tabela só tem o `Id` padrão. |
| `georref/andrade_2003_fig<n>.png` | A figura do artigo como recortada para o georreferenciamento (n = 9 a 15). |
| `georref/andrade_2003_fig<n>.png.points` | Pontos de controle do georreferenciador do QGIS. Com o `.png` + o `.points`, qualquer pessoa refaz o warp (EPSG:4326) — por isso os GeoTIFF georreferenciados (~2,5 MB cada) NÃO são versionados. |

Os `.sbn`/`.sbx` (índice espacial do ArcGIS) e `.lyr` (estilo do ArcMap) que
vieram com os arquivos da turma ficaram de fora: não carregam dado.

## Como digitalizar (convenção que o `10` espera)

- **Toda linha é fronteira TERRA/ÁGUA**: costa oceânica, margem de laguna,
  contorno de ilha, margem de canal. Atravessar uma linha troca a classe — é
  assim que o `10` decide o que é terra (2-coloração a partir do mar aberto).
  Por isso NÃO se traça contorno entre duas unidades geológicas emersas: uma
  linha dessas dentro do continente o partiria em "terra" e "água".
- Fechar o contorno pela moldura da figura é permitido: o trecho a menos de
  ~220 m da borda do quadro é descartado e substituído pelo quadro exato.
- Contornos podem ser feitos em vários trechos; frestas de até ~440 m entre
  pontas são costuradas (e impressas no log). Acima disso o `10` avisa.
- Nenhum ponto-semente, nenhum campo de atributo.

## Validação

`docs/validacao_paleolinhas_estagios.png` (01/10/2026): o polígono de cada
estágio desenhado sobre a própria figura georreferenciada, mais o gráfico de
terra emersa por estágio. `docs/validacao_georref_fig9.png` (24/09/2026)
valida o georreferenciamento da Fig. 9 contra a costa atual do FABDEM.

Os sete estágios são fases da evolução QUATERNÁRIA (I no Pleistoceno, II a
VII no Holoceno). O Estágio VII ("Retomada da progradação", < 1.300 cal AP) é
a última fase do modelo, não a costa atual — a costa atual nas figuras é só a
linha tracejada "present day coastline", e no simulador vem do FABDEM.

## Estado

| Estágio | Figura | Terra emersa no quadro (esférica) | partes |
|---|---|---|---|
| I | 9 | 1.122 km² | 5 |
| II | 10 | 916 km² | 12 |
| III | 11 | 931 km² | 13 |
| IV | 12 | 1.301 km² | 3 |
| V | 13 | 1.333 km² | 3 |
| VI | 14 | 1.359 km² | 3 |
| VII | 15 | 1.383 km² | 3 |

## Histórico

- 24/09/2026 (versão preliminar, não publicada): `paleolinhas.shp` único, só
  o Estágio I, digitalizado pelo Helio, com campo `estagio` e fechamento por
  âncora + ponto-semente.
- 01/10/2026 (v2.1, publicada): substituído pelos sete arquivos da turma. O
  Estágio I da turma dá 1.122 km² contra 1.144 km² do traçado anterior (−2 %).

## Armadilha já encontrada (24/09/2026)

Ao exportar do QGIS, a caixa **"Salvar apenas feições selecionadas"** marcada
com nada selecionado grava um shapefile de 100 bytes: só cabeçalho, zero
feições, sem aviso. O `10` agora para nesse caso. Confira o tamanho do arquivo
depois de exportar.
