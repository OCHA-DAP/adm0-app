# adm0-site
## Pipeline

`uv run python -m pipeline` runs the default steps, or one with `--step <name>`. `prepare`, `extend`, `differences` and `tiles` skip work whose inputs match `outputs/state.json`. `download --only <source>` (`ungeodata` is downloaded only when named, with `AGS_TOKEN`, a geoportal.un.org token, in `.env`), `prepare --only <source>`, `extend --source <name>` and `tiles --only <id>` always run what they name.

`--step differences` keeps its tables in `tmp/differences.duckdb`, so `--from assign`, `--from overlay` or `--from review` reruns that phase and all after it. Phases read as: `land` (land and lines), `assign` (cells, pieces, polygons), `overlay` (matches, land patches, island gaps), `review` (items, borders, site files, with an island difference listed only where both sources draw islands in the zone their two cells share). `DIFF_BBOX=xmin,ymin,xmax,ymax` limits a run to one area and writes partial results, which `--step differences` replaces on its next run.

## Data catalog

The site's tiles and tables are published as a Portolan catalog in `catalog/`, which the `catalog` step generates (only its `.portolan/` settings are committed). After the `tiles` step, build and push it with:

```sh
uv run python -m pipeline --step catalog --push
```

Pushing runs as a source.coop service account: save its `sck_` API key to a file only your user can read, then set `AWS_ROLE_ARN` (`arn:aws:iam::<service-account-id>:role/FullAccess`), `AWS_WEB_IDENTITY_TOKEN_FILE` (absolute path to the key file) and `PORTOLAN_REMOTE` in `.env`, from `.env.example`. Needs AWS CLI 2.13 or later. `--only <id> ...` stages a subset of layers or tables. `uv run pytest` checks the portolan wrapper against a scratch catalog (about a minute).

## Build layer

`uv run python -m pipeline --step build` builds the build layer in numbered stages under `outputs/build/`. Stage 07 extends it into water. See `docs/reference/build-data.md`.
