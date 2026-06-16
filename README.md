# Congreso Open Data

Crawler de datos abiertos del Congreso de los Diputados.

No usa dependencias externas: los scripts funcionan con Python 3.12 y librería estándar.

## Índice y documentación de la API

El fichero `index.html` de la raíz documenta cómo consumir la API estática del repositorio:

- URLs base para GitHub Pages y `raw.githubusercontent.com`.
- Endpoints disponibles para votaciones, iniciativas e intervenciones.
- Estructura de los JSON generados.
- Ejemplos de uso en JavaScript, PHP y cURL.
- Panel automático que intenta leer los índices reales de `data/congreso` si ya existen.

Si activas GitHub Pages, la documentación quedará disponible en:

```txt
https://jalonsomerchan.github.io/congreso-opendata/
```

También puede abrirse directamente desde el repositorio como `index.html`.

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

## Ejecución local

```bash
python3 scripts/crawl_congreso_votaciones.py
python3 scripts/crawl_congreso_iniciativas.py
python3 scripts/crawl_congreso_intervenciones.py
```

Para limitar el número de elementos nuevos descargados en una ejecución:

```bash
MAX_NEW_VOTES=10 python3 scripts/crawl_congreso_votaciones.py
MAX_NEW_INITIATIVES=10 python3 scripts/crawl_congreso_iniciativas.py
MAX_NEW_INTERVENTIONS=10 python3 scripts/crawl_congreso_intervenciones.py
```

Para pasar URLs concretas al crawler de intervenciones:

```bash
INTERVENCIONES_EXTRA_URLS="https://www.congreso.es/ejemplo/export.json" python3 scripts/crawl_congreso_intervenciones.py
```

## GitHub Actions

El workflow `.github/workflows/crawl-congreso-votaciones.yml` ejecuta los tres crawlers:

- Manualmente con `workflow_dispatch`.
- Cada 30 minutos con `schedule`.
- En cada `push` que modifique los scripts o el propio workflow.

Si se generan cambios en `data/congreso`, hace commit automático con el usuario `github-actions[bot]`.
