# adm0-site
## Data catalog

The site's tiles and tables are published as a Portolan catalog in `catalog/`, which the `catalog` step generates (only its `.portolan/` settings are committed). After the `tiles` step, build and push it with:

```sh
uv run python -m pipeline --step catalog --push
```

Pushing needs `PORTOLAN_REMOTE` and the source.coop keys in `.env` (see `.env.example`). `--only <id> ...` stages a subset of layers or tables. `uv run pytest` checks the portolan wrapper against a scratch catalog (about a minute).
