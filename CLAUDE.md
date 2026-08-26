# CLAUDE.md — Projeto NMRM Caravelas

> Arquivo lido automaticamente pelo Claude Code no início de cada sessão.
> Mantenha-o atualizado: é a memória do projeto entre sessões.

## 1. Contexto

Disciplina **Ecossistemas Marinhos Costeiros** — UERJ / FAOC / DOB
(Prof. Filipe Chaves). Semestre 2026.2.

**Pergunta do semestre:** como a elevação do Nível Médio Relativo do Mar (NMRM)
poderá reorganizar os ecossistemas costeiros, e quais consequências ecológicas
e sociais emergem dessa transformação?

**Cadeia analítica da disciplina:**
`Cenário → Exposição → Processo → Resposta ecológica → Serviço → Sociedade → Adaptação`

**Área de estudo:** planície costeira de Caravelas, extremo sul da Bahia.
Praia, restinga, duna, manguezal e o sistema estuarino Caravelas–Peruípe.
Planície **extremamente plana** e progradante, com cordões litorâneos
quaternários. O usuário tem experiência de campo na área.

**Escopo do trabalho:**
- **Parte 1 (atual):** ferramenta geoespacial interativa e parametrizada de
  exposição ao NMRM.
- **Parte 2:** modelagem da resposta ecológica.
- **Parte 3 (fora de escopo):** hidrodinâmica SFINCS e/ou paleoclima.

**Prazos:** mapa de elevação simples já entregue; demais entregas em meados
de outubro.

## 2. Estrutura do repositório

```
nmrm-caravelas/
├── CLAUDE.md                  # este arquivo
├── README.md
├── requirements.txt
├── .gitignore                 # ignorar dados/ e saidas/
├── config.py                  # caminhos, bbox, CRS — fonte única
├── requirements.txt
├── .vscode/                    # launch.json + settings.json
├── src/
│   ├── __init__.py
│   └── slr_core.py            # MOTOR — sem interface, toda a ciência
├── 01_mapa_elevacao.py        # mosaico/recorte/reprojeção FABDEM + mapa base
├── 02_simulador_nmrm.py       # interface Streamlit sobre slr_core
├── teste_sintetico.py         # valida o pipeline sem precisar do FABDEM
├── dados/                     # entradas (NÃO versionar — FABDEM é CC BY-NC-SA)
│   ├── fabdem/                # tiles brutos .tif
│   ├── auxiliar/              # MapBiomas, GEBCO, maregrafia
│   └── processado/            # caravelas_fabdem_utm24s_30m.tif
└── saidas/                    # PNG, GeoTIFF, CSV (NÃO versionar)
```

## 3. Convenções de código (obrigatórias)

- **Idioma:** código, comentários, docstrings e nomes de variáveis em
  **português**.
- **Parâmetros centralizados:** todo limiar numérico vive em dicionário
  `CONFIG_*` / `CENARIOS_*` / `NIVEIS_*` no topo do módulo.
  **Nunca hardcodar valor dentro de função.**
- **Prints diagnósticos sempre**, no formato de tag:
  ```python
  print(f"[MASCARA] cota={cota:.2f} m | inundada={n_px} px")
  print(f"[AREA] terra={a:.1f} km² | inundada={b:.1f} km² ({p:.1f}%)")
  ```
- **Scripts completos e executáveis**, nunca trechos parciais.
- **Exports com carimbo de data:** `matriz_cenarios_20260826.csv`.
- **Separação motor/interface:** `slr_core.py` não importa Streamlit,
  ipywidgets ou qualquer UI. Interfaces só desenham controles.
- Nível Python do usuário: **intermediário**. Explicar decisões não óbvias
  em comentário, sem encher de abstração.

## 4. Dados

| Base | Uso | Observação |
|------|-----|------------|
| **FABDEM V1-2** | MDE principal | Hawker et al. 2022, ERL 17:024016. Copernicus GLO-30 com dossel e edificações removidos por ML. 1 arcsec (~30 m), 60°S–80°N, datum vertical **EGM2008**. Licença **CC BY-NC-SA 4.0** (uso acadêmico OK). Oceano codificado como exatamente `0.0`. |
| **IPCC AR6** | Cenários SSP | Valores atuais em `CENARIOS_AR6` são **globais (NMGM)** e provisórios. Substituir pelos locais do NASA/IPCC AR6 Sea Level Projection Tool (Garner et al., Zenodo 10.5281/zenodo.5914709). |
| **GEBCO 2025** | Batimetria de contexto | — |
| **MapBiomas** | Cobertura do solo | Entra na Parte 2, cruzando com o GeoTIFF classificado. |
| **BNDO/CHM · FEMAR** | Constantes harmônicas e datums de maré | `chm.bndo@marinha.mil.br`. **Ainda não solicitado.** Caminho crítico. |
| **Andrade et al. 2003** | Evolução quaternária da planície | Paleoníveis +4,8 / +3,5 / +2,5 m — validação opcional. |

**Projeção de trabalho:** SIRGAS 2000 / UTM 24S — **EPSG:31984**, 30 m.

## 5. Decisões metodológicas fechadas

- **Cenários:** SSP1-2.6, SSP2-4.5, SSP5-8.5 (+ SSP5-8.5 baixa confiança).
  Horizontes 2050 e 2100. Percentis 17 / mediana / 83.
- **Níveis de sensibilidade da turma:** +0,5 m, +1 m, +2 m.
  A ferramenta deve extrapolar além desses valores, não travar neles.
- **Conectividade hidráulica LIGADA por padrão.** Terreno abaixo da cota mas
  sem caminho até o mar é classificado à parte (`isolada`), nunca somado à
  área inundada. É o principal diferencial frente aos simuladores online.
- **Maré: adiada para a v2.** Offsets em `NIVEIS_MARE` estão em `0.00` com
  `PROVISORIO = True`. A v1 roda no nível médio.
- **Exagero vertical ~50** no sombreamento — a planície é plana demais para
  hillshade sem exagero.

## 6. Estado atual

- [x] `01_mapa_elevacao.py` — mosaico FABDEM, recorte, reprojeção, máscara de
      oceano, mapa hipsométrico sombreado, curva hipsométrica, tabela altimétrica.
- [x] `slr_core.py` — cota composta, máscara com conectividade, estatísticas de
      área, matriz de cenários, curva de exposição, export PNG/GeoTIFF/CSV.
- [x] `02_simulador_nmrm.py` — interface Streamlit.
- [x] Ambiente VS Code reproduzível (config.py, requirements.txt, .vscode/).
- [ ] Imagem de satélite de fundo (`contextily`, reprojeção para WebMercator).
- [ ] Solicitação ao BNDO e integração da maré.
- [ ] Parte 2 — resposta ecológica cruzando com MapBiomas.

## 7. Regras de conduta científica (não negociáveis)

1. **Nunca inventar valor de maré, datum ou projeção local.** Se o dado não
   chegou, manter `0.00` com flag `PROVISORIO` e avisar na interface.
   Número inventado em mapa vira citação em relatório.
2. **Não trocar o FABDEM por SRTM, Terrarium ou tiles Terrain-RGB genéricos.**
   Em planície com manguezal o viés de dossel é maior que o próprio sinal
   de NMRM simulado.
3. **Todo produto deve declarar suas limitações** — o rodapé da figura e a
   aba de metadados não são decorativos.
4. Distinguir sempre **NMGM** (média global) de **NMRM** (relativo local).
5. A saída é **exposição potencial**, não previsão de inundação real:
   não resolve hidrodinâmica, atenuação de maré no estuário, ondas, drenagem
   nem resposta morfodinâmica (acresção de manguezal, migração de duna).
