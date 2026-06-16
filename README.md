# Congreso Open Data

Crawler de datos abiertos del Congreso de los Diputados.

No usa dependencias externas: los scripts funcionan con Python 3.12 y librería estándar.

## Índice y documentación de la API

El fichero `index.html` de la raíz documenta cómo consumir la API estática del repositorio:

- URLs base para GitHub Pages y `raw.githubusercontent.com`.
- Endpoints disponibles para votaciones, iniciativas, intervenciones y diputados.
- Índices globales, por legislatura y por año.
- Estructura de los JSON generados.
- Ejemplos de uso en JavaScript, PHP y cURL.
- Panel automático que intenta leer los índices reales de `data/congreso` si ya existen.

Si activas GitHub Pages, la documentación quedará disponible en:

```txt
https://jalonsomerchan.github.io/congreso-opendata/
```

También puede abrirse directamente desde el repositorio como `index.html`.

## Endpoints principales

```txt
data/congreso/legislaturas.json
data/congreso/{bloque}/index.json
data/congreso/{bloque}/latest.json
data/congreso/{bloque}/legislaturas/index.json
data/congreso/{bloque}/legislaturas/{legislatura}/index.json
data/congreso/{bloque}/legislaturas/{legislatura}/latest.json
data/congreso/{bloque}/legislaturas/{legislatura}/lastest.json
data/congreso/{bloque}/anios/index.json
data/congreso/{bloque}/anios/{anio}/index.json
data/congreso/{bloque}/anios/{anio}/latest.json
data/congreso/{bloque}/anios/{anio}/lastest.json
```

`latest.json` es la ruta canónica. También se genera `lastest.json` como alias para tolerar la errata.

Bloques disponibles:

```txt
votaciones
iniciativas
intervenciones
diputados
```

## Fuentes cubiertas

### Votaciones

El script `scripts/crawl_congreso_votaciones.py` lee la página oficial de votaciones del Congreso:

```txt
https://www.congreso.es/es/opendata/votaciones
```

Extrae los enlaces JSON oficiales, descarga las votaciones nuevas o actualizadas y genera estos ficheros:

```txt
data/congreso/votaciones/index.json
data/congreso/votaciones/latest.json
data/congreso/votaciones/{legislatura}/{sesion}/{fecha}/{votacion}.json
```

Cada fichero de votación conserva la respuesta oficial dentro de `data` y añade metadatos propios en `metadata`.

### Iniciativas

El script `scripts/crawl_congreso_iniciativas.py` lee la página oficial de iniciativas:

```txt
https://www.congreso.es/es/opendata/iniciativas
```

Extrae los JSON oficiales disponibles para la legislatura actual, como iniciativas legislativas aprobadas, proyectos de ley, propuestas de reforma y proposiciones de ley.

Genera:

```txt
data/congreso/iniciativas/index.json
data/congreso/iniciativas/latest.json
data/congreso/iniciativas/{dataset}/latest.json
data/congreso/iniciativas/{dataset}/{timestamp}.json
```

El nombre oficial de los ficheros puede cambiar porque incluye timestamp. Para evitar commits innecesarios, el crawler compara el hash del contenido antes de guardar una nueva instantánea.

### Intervenciones

El script `scripts/crawl_congreso_intervenciones.py` lee la página pública del buscador de intervenciones:

```txt
https://www.congreso.es/es/busqueda-de-intervenciones
```

La página funciona como buscador y no siempre expone enlaces OpenData estáticos en el HTML inicial. El crawler:

- Descubre enlaces JSON, CSV o XML relacionados con intervenciones si aparecen en la página.
- Los guarda como JSON normalizados con metadatos.
- No rompe el workflow si no hay enlaces estáticos; crea un índice inicial y seguirá comprobándolo en cada ejecución.
- Permite añadir URLs concretas mediante `INTERVENCIONES_EXTRA_URLS` si el Congreso genera enlaces de exportación tras aplicar filtros en el navegador.

Genera:

```txt
data/congreso/intervenciones/index.json
data/congreso/intervenciones/latest.json
data/congreso/intervenciones/{recurso}/latest.json
data/congreso/intervenciones/{recurso}/{timestamp-o-hash}.json
```

### Diputados

El script `scripts/crawl_congreso_diputados.py` lee la página oficial de diputados:

```txt
https://www.congreso.es/es/opendata/diputados
```

Extrae los JSON oficiales disponibles, como diputados activos, diputados por legislatura, diputadas en todas las legislaturas y declaraciones de intereses económicos.

Genera:

```txt
data/congreso/diputados/index.json
data/congreso/diputados/latest.json
data/congreso/diputados/{dataset}/latest.json
data/congreso/diputados/{dataset}/{timestamp}.json
```

## Índices derivados

El script `scripts/build_congreso_indexes.py` no descarga datos. Lee los índices principales y genera vistas por legislatura y por año para cada bloque:

```txt
data/congreso/{bloque}/legislaturas/index.json
data/congreso/{bloque}/legislaturas/{legislatura}/index.json
data/congreso/{bloque}/legislaturas/{legislatura}/latest.json
data/congreso/{bloque}/anios/index.json
data/congreso/{bloque}/anios/{anio}/index.json
data/congreso/{bloque}/anios/{anio}/latest.json
```

También genera:

```txt
data/congreso/legislaturas.json
```

Ese fichero resume las legislaturas disponibles en todos los bloques y enlaza sus índices.

## Ejecución local

```bash
python3 scripts/crawl_congreso_votaciones.py
python3 scripts/crawl_congreso_iniciativas.py
python3 scripts/crawl_congreso_intervenciones.py
python3 scripts/crawl_congreso_diputados.py
python3 scripts/build_congreso_indexes.py
```

Para limitar el número de elementos nuevos descargados en una ejecución:

```bash
MAX_NEW_VOTES=10 python3 scripts/crawl_congreso_votaciones.py
MAX_NEW_INITIATIVES=10 python3 scripts/crawl_congreso_iniciativas.py
MAX_NEW_INTERVENTIONS=10 python3 scripts/crawl_congreso_intervenciones.py
MAX_NEW_DEPUTIES=10 python3 scripts/crawl_congreso_diputados.py
GROUP_LATEST_LIMIT=50 python3 scripts/build_congreso_indexes.py
```

Para pasar URLs concretas al crawler de intervenciones:

```bash
INTERVENCIONES_EXTRA_URLS="https://www.congreso.es/ejemplo/export.json" python3 scripts/crawl_congreso_intervenciones.py
```

## GitHub Actions

El workflow `.github/workflows/crawl-congreso-votaciones.yml` ejecuta todos los crawlers y después construye los índices derivados:

- Manualmente con `workflow_dispatch`.
- Cada 30 minutos con `schedule`.
- En cada `push` que modifique los scripts o el propio workflow.

Si se generan cambios en `data/congreso`, hace commit automático con el usuario `github-actions[bot]`.
