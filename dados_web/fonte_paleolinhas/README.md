# `dados_web/fonte_paleolinhas/` — origem das paleolinhas de costa

Insumo de `10_paleolinhas.py`, que fecha estas linhas em polígonos de terra
emersa e grava `dados_web/paleolinhas_turma.geojson`.

Mesma lógica de `fonte_limite_turma/`: **o que está aqui é trabalho manual
insubstituível e por isso é versionado no repositório**, não em
`NMRM_DIR_DADOS`. Se sumir, a reconstrução paleoambiental some junto.

## Arquivos

| arquivo | o que é |
|---|---|
| `paleolinhas.shp` (+ `.shx`, `.dbf`, `.prj`, `.cpg`) | **A camada de trabalho.** Linhas de costa digitalizadas no QGIS sobre as figuras georreferenciadas de Andrade et al. (2003). Um registro por linha, campo `estagio` com o número romano (`I` a `VII`). É este arquivo que o `10` lê. |
| `originais_qgis/*.gpkg` | Cópia como-digitalizada saída do QGIS, por figura. Redundante com o `.shp` — existe só como rede de segurança. |
| `georref/*.tif` | **A figura georreferenciada** (EPSG:4326, transform embutido). É a prova do georreferenciamento e, na prática, o insumo de que a digitalização saiu. |
| `georref/*.points` | Pontos de controle do georreferenciador do QGIS, quando existirem. Minúsculos e preferíveis ao TIF: com eles mais a figura do artigo, qualquer pessoa refaz o warp. **Para a Fig. 9 não existe** — daí o TIF estar versionado. |

## Por que o GeoTIFF está versionado (e como sair disso)

O plano original era deixar os TIFF fora do repositório, em
`NMRM_DIR_DADOS/auxiliar/paleo/`, por serem pesados e **regeneráveis** a partir
da figura mais o `.points`. Só que o `.points` da Fig. 9 não foi salvo, então o
TIF virou o único registro do georreferenciamento — perder o arquivo é perder o
trabalho. Ficou aqui, 1,9 MB.

Para as Figs. 10 a 15: **salve o `.points`** (no georreferenciador do QGIS,
Arquivo → Salvar pontos GCP como...). Com ele versionado, o TIF correspondente
pode ir para `C:\dados_nmrm\auxiliar\paleo\` e sair do git, e o da Fig. 9 junto.

## Validação do georreferenciamento (Fig. 9, 24/09/2026)

`docs/validacao_georref_fig9.png`. A costa atual derivada do FABDEM, de forma
independente, cai sobre a linha tracejada "present day coastline" desenhada por
Andrade et al. na própria figura — ao longo de ~60 km, acompanhando a saliência
da Ponta da Baleia, a reentrância e a Ponta do Catoeiro. A moldura impressa
coincide com o quadro 39°30'–39°00'W × 17°30'–18°00'S do `CONFIG_PALEO`.
Vale repetir esse teste a cada figura nova: é barato e pega erro de warp na hora.

## Convenções

- **Geometria:** LINHA, nunca polígono. O polígono é fechado pelo `10` contra o
  quadro da figura — ver o cabeçalho do script para o porquê.
- **CRS:** EPSG:4326 (WGS 84). O `10` para se o `.prj` for projetado.
- **Quadro das Figs. 9 a 15:** 39°30'W–39°00'W × 17°30'S–18°00'S, idêntico nas
  sete. Georreferencie uma com capricho e reaproveite a transformação nas outras
  — warps independentes fariam a diferença de área entre estágios virar ruído.
- **Metadados de cada estágio** (idade, cota, figura, descrição) moram no
  dicionário `ESTAGIOS` de `10_paleolinhas.py`, não na tabela de atributos. No
  QGIS só se preenche `estagio`.

## Estado

- [x] Estágio I — Fig. 9, 73 vértices. Terra emersa: 1.144 km² no quadro
      (contra 1.425 km² hoje pelo FABDEM: +281 km², +24,5 % de progradação).
- [ ] Estágios II a VII — Figs. 10 a 15.

## Armadilha já encontrada (24/09/2026)

Ao exportar do QGIS, a caixa **"Salvar apenas feições selecionadas"** marcada
com nada selecionado grava um shapefile de 100 bytes: só cabeçalho, zero
feições, sem aviso. Foi o que aconteceu com a primeira versão da Fig. 9 —
recuperada do `.gpkg`. Confira o tamanho do arquivo depois de exportar.
