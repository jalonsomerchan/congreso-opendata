# Congreso Open Data

Crawler de datos abiertos del Congreso de los Diputados.

## Votaciones

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

## Ejecución local

```bash
python3 scripts/crawl_congreso_votaciones.py
```

Para limitar el número de nuevas votaciones descargadas en una ejecución:

```bash
MAX_NEW_VOTES=10 python3 scripts/crawl_congreso_votaciones.py
```

## GitHub Actions

El workflow recomendado para ejecutarlo cada 30 minutos es:

```yaml
name: Crawl Congreso votaciones

on:
  workflow_dispatch:
    inputs:
      max_new_votes:
        description: "Máximo de votaciones nuevas a descargar (0 = sin límite)"
        required: false
        default: "0"
  schedule:
    - cron: "*/30 * * * *"

permissions:
  contents: write

concurrency:
  group: crawl-congreso-votaciones
  cancel-in-progress: true

jobs:
  crawl:
    runs-on: ubuntu-latest

    env:
      MAX_NEW_VOTES: ${{ github.event.inputs.max_new_votes || '0' }}

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Crawl Congreso votaciones
        run: python scripts/crawl_congreso_votaciones.py

      - name: Commit generated data
        run: |
          if [ -z "$(git status --porcelain -- data/congreso/votaciones)" ]; then
            echo "No hay nuevas votaciones"
            exit 0
          fi

          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

          git add data/congreso/votaciones
          git commit -m "Actualizar votaciones del Congreso"
          git push
```
