"""Gera um MDE sintético estilo planície de Caravelas e testa slr_core."""
import numpy as np
import rasterio
from rasterio.transform import from_origin
import matplotlib
matplotlib.use("Agg")

import config
import src.slr_core as core

config.criar_estrutura()
# Em saidas/, NUNCA em processado/: aquela pasta é do dado real que vira mapa,
# e um MDE sintético ao lado do FABDEM recortado é convite a confundir os dois.
DEM_TESTE = config.DIR_SAIDAS / "dem_teste_sintetico.tif"

ny, nx, res = 500, 600, 30.0
y, x = np.mgrid[0:ny, 0:nx]

# rampa suave subindo para oeste (planície costeira muito plana)
dem = 0.0035 * (nx - x) * res * 0.1
# tabuleiro/terraço a oeste
dem += np.where(x < 120, 8.0 * (120 - x) / 120.0, 0.0)
# ruído baixo (cordões litorâneos)
dem += 0.25 * np.sin(x / 7.0) * np.exp(-((x - 420) ** 2) / (2 * 90 ** 2))
# canal estuarino entrando desde o mar
canal = np.abs(y - (250 + 60 * np.sin(x / 90.0))) < 4
dem[canal & (x > 180)] = 0.15
# depressão fechada interior (deve ser classificada como isolada)
dep = ((x - 200) ** 2 / 30 ** 2 + (y - 110) ** 2 / 22 ** 2) < 1
dem[dep] = 0.3
# oceano a leste = exatamente 0.0 (regra FABDEM)
dem[x > 545] = 0.0
dem = dem.astype("float32")

transform = from_origin(300000, 8050000, res, res)
perfil = dict(driver="GTiff", height=ny, width=nx, count=1, dtype="float32",
              crs="EPSG:31984", transform=transform, nodata=-9999.0)
with rasterio.open(DEM_TESTE, "w", **perfil) as dst:
    dst.write(dem, 1)

print("=" * 70)
d = core.carregar_dem(str(DEM_TESTE))

print("=" * 70)
c = core.cota_limiar(1.0, mare_m=0.0)
m_con = core.mascara_inundacao(d["dem"], d["mask_oceano"], c["cota_m"],
                               conectividade=True, area_pixel_m2=d["area_pixel_m2"])
e_con = core.estatisticas_area(m_con, d["dem"], d["area_pixel_m2"])

print("-" * 70)
m_bath = core.mascara_inundacao(d["dem"], d["mask_oceano"], c["cota_m"],
                                conectividade=False, area_pixel_m2=d["area_pixel_m2"])
core.estatisticas_area(m_bath, d["dem"], d["area_pixel_m2"])

print("=" * 70)
df = core.tabela_cenarios(d, cenarios=["SSP1-2.6", "SSP5-8.5"], horizontes=[2100],
                          percentis=["mediana"])
print(df.to_string(index=False))

print("=" * 70)
cv = core.curva_exposicao(d, cotas=np.arange(0, 2.51, 0.5))
print(cv.to_string(index=False))

print("=" * 70)
fig, ax = core.figura_mapa(d, m_con, c,
                           subtitulo="TESTE SINTÉTICO — SSP5-8.5 mediana 2100")
core.salvar_figura(fig, "teste_mapa", pasta=str(config.DIR_SAIDAS), dpi=110)
core.exportar_geotiff(m_con, d,
                      str(config.DIR_SAIDAS / "teste_classes.tif"), c["cota_m"])
core.exportar_tabela(df, "teste_tabela", pasta=str(config.DIR_SAIDAS))
print("OK")
