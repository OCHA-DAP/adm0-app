# Build layer data

Build with `uv run python -m pipeline --step build`, one stage with `--stage NN`, or a stage and all after it with `--from NN`. Stage 00 runs only by name. Stage 01 skips when its code and sources match the manifest, stage 06 when its code, `units` and `changes.json` do, stage 07 when its code and `units` do, and stage 08 when its inputs do. Stage 08 also skips while stage 07's cells come from older `units`. `COAST_BBOX=xmin,ymin,xmax,ymax` runs stage 08 on one area into `tmp/coast_bbox/`, without the ADM0 output or the manifest. Stage 09 skips when its inputs match. Stage 10 tiles only layers whose source changed. Stage 11 takes about a second. `uv run python -m pipeline.build.watch` runs stage 11 and links the page files into `catalog/build/`, then does it again on every save under `inputs/build/` or of a `changes.json` from stage 05 or 08, so the dev server shows a text edit on reload.

## Curated inputs (`inputs/build/`)

| File | Contents |
|---|---|
| `changes.json` | One record per curated change: `id`, `type`, `keys` (pairs of UN `objectid` and `gaul_id`), `relabel` (a `un_error` change without keys: `un_objectid` and `gaul_id` of the units that take the UN entity `to` until a change with keys applies), `cut` (target `objectid`s and `bndl` line ids), `areas` (`area_id`s in `cut_lines.parquet`: with `keys`, their faces get the key's GAUL entity; on a `land_area`, its outline), `entity` (`code` and `name` of an entity the change adds, or of the area a `land_area` change shows), `area_codes` (`area_id` to the output code its faces take), `parties` (ISO3 codes on `land_area` changes). Geometry instructions only: the text lives in `descriptions.json` |
| `descriptions.json` | All curated page text, by change id: `title`, `method` and `source` (every `C` change), `text` and `sources` (`title`, `url`; every `C` change, new island entity `N-<code>` and land area `D-<code>`). Only stage 11 reads it |
| `dispute_parties.csv` | `code`, `parties` (comma-separated ISO3): parties to a new island entity that WP's `Map_Disp` lacks |
| `cut_lines.parquet` | Cut geometry UN Geodata lacks, written by stage 00 from GAUL: `change_id`, `area_id`, `source_layer`, `source_feature` |
| `land_areas.parquet` | One outline per `land_area` change, written by stage 00 from its `areas` ring in `cut_lines.parquet`, else from the FieldMaps polygon with its code: `change_id`, `source_layer`, `source_feature` |
| `coast_overrides.csv` | `lon`, `lat` (a point on the OSM land polygon), `unit_id` (the unit it goes to, `drop`, or a new entity's code), `name` (the new entity's name), `change_id`, `reason`. Applies to OSM polygons with land of at most one unit. A new entity gets its own ADM0 row, with UN Geodata's disputed status (`stscod` 99) |
| `island_overrides.csv` | `un_objectid`, `un_part`, `face`, `gaul_id`, `change_id`, `reason`. A blank part or face matches all |
| `review_decisions.csv` | `un`, `fieldmaps`, `action`, `reason`. `remove` drops a UN and FieldMaps pair from review, `recode` moves it to the islands step, `whole` (with the code in `un`) keeps a code FieldMaps splits as one row |
| `name_overrides.csv` | `adm0_id`, `field` (`name`, `map_label` or `status`), `value`, `reason`. Applied last by stage 09 |
| `stages.json` | Plain-language description of each stage |
| `path.json` | The page's steps from GAUL to the build layer, in the order and with the ids of `STEPS` in `pipeline/build/common.py` (which holds each step's change types), the two tile layers each step compares (previous step's output, then its own), `labels` (the step labels its changes on the map), the legend label for each, `title` and `summary`. Only stage 11 reads it |

## Stages (`outputs/build/`)

| Folder | Files |
|---|---|
| `01_source` | `un_polygons`, `un_lines`, `gaul_polygons`, `gaul_voronoi` (their lower-case `x` codes, `xxx` included, as upper-case ISO 3166-1 user-assigned codes, and UN Geodata's `xRI` as `XKI`), `fieldmaps_voronoi`, `gaul_bits` (GAUL polygons in small pieces for fast overlaps), `line_overlaps` (`a_code` GAUL, `b_code` UN, `km2`: land the two polygon sets give different entities) |
| `02_split` | `un_parts`: `un_objectid`, `un_iso3`, `un_part` |
| `03_cut` | `faces`: adds `face` (0 for an uncut part) and `area_id`. `cuts`: each cut line and its source |
| `04_attribute` | `parts`: adds `gaul_id`, `rule` (`link`, `override`, `area`), `change_id`, `reason`, `piece` (for codes FieldMaps splits into several units: the FieldMaps unit of that code whose cell holds the part, else the nearest; only on parts that keep their link or a `split` change) |
| `05_units` | `units` (with `adm0_id` and `iso3`: the output row and code each unit dissolves to), `crosswalk` (parquet and CSV), `land_areas` (each `land_area` outline cut by the UN entities holding at least 5% of it: `change_id`, `code`, `un_objectid`, `un_iso3`, `km2`), `changes.json` (data only: the curated changes and the generated records with `values` per UN and GAUL pair: `un_objectid`, `un`, `un_name`, `gaul`, `gaul_name`, `km2`; `gaul_removed` and `removed_parts`; `largest_patch_bbox`; `codes` on line updates), `change_areas`, `line_patches`, `cell_islands` (`change_id`, `km2`), `labels.geojson` (a point inside each polygon of each change: `change`, `km2`, `text`, the UN and GAUL codes, or the UN and GAUL names on the largest polygon only where the code is the same) |
| `06_export` | `adm0` (units dissolved by `adm0_id`: `iso3`, and `un_iso3`, `un_objectid`, `gaul_id`, `gaul_code`, each `;`-joined where a row spans several), `un` (units dissolved by UN key, for the page), `path_errors` and `path_split` (units dissolved with the changes up to that page step applied; `key` plus the ADM0 or UN attributes each row has at that step), `checks.json` |
| `07_extend` | `units_voronoi`: `units` extended into water with `topo-tools edge-extend` |
| `08_coast` | `coast_units` (the `units` columns on OSM land), `un` and `adm0` dissolved from it, `gained` and `lost` (`change_id`, `km2`; `gained` adds `fm_code` and `fm_differs`), `new_islands` (`change_id`, `fid`, `km2`, `straddle`, `fm_code`), `dropped` (UN Geodata parts touching no OSM land), `changes.json` (data only, as in stage 05), `checks.json` |
| `09_names` | `adm0`: the output (`adm0_id`, `iso3`, `name`, `map_label`, `status`, `un_iso3`, `un_objectid`, `gaul_id`, `gaul_code`). `name` is the M49 name, or for a split row or a code M49 lacks, FieldMaps' name. `map_label` is FieldMaps' `adm0_name`. `status` is UN Geodata's where the row is its UN entity, else FieldMaps'. |
| `10_tiles` | PMTiles for the build page |
| `11_page` | `crosswalk.csv`, `labels.geojson` and `stages.json` copied for the page, `changes.json` and `changes.csv` (stages 05 and 08 with `title`, `description`, `method`, `source` and `sources` from `descriptions.json` and the generated text), `path.json` (with each step's `types`), and `names.json` (ISO3 to M49 name, with TWN added) for the map border labels |

`manifest.json` records, per stage: build time, git commit, tool versions, input and output SHA-256s, and row and area totals. Each folder's `README.md` is generated from `stages.json` and the manifest.

## Change ids

| Prefix | Meaning | Written in |
|---|---|---|
| `C` | Curated change | `changes.json` |
| `S-<adm0_id>` | A unit FieldMaps splits from its code that no curated change splits, other than the code's largest row unless its UN entity is a territory (`stscod` 2, 3 or 4) | stage 05 |
| `I-<UN iso3>-<gaul_id>` | The sources give islands to different entities | stage 05 |
| `G-<gaul_id>` | GAUL land touching no UN land | stage 05 |
| `E-<UN iso3>-<FieldMaps code>` | UN Geodata polygon parts inside a FieldMaps Voronoi cell with a different code, ignoring case, with `review` set. They stay out of `change_ids`, and ownership is unchanged. Their geometry sits in `cell_islands` | stage 05 |
| `V-<UN iso3>-<GAUL code>` | Islands with no GAUL polygon inside another entity's GAUL Voronoi cell, kept with the UN owner. They stay out of `change_ids` | stage 05 |
| `L-<code>-<code>` | Land GAUL and UN Geodata polygons give different entities along a border, in patches of 0.01 km² or more | stage 05 |
| `K-<code>` | OSM coastline of one UN entity: `gained_km2`, `lost_km2`, `un_km2`, `kept_km2`, `fieldmaps_differs_km2` (gained land FieldMaps' cell gives to another code) | stage 08 |
| `N-<code>`, `N-<code>-<FieldMaps code>`, `N-<code>-straddle` | OSM islands with no UN Geodata land, given to the unit whose cell holds their inner point. The second form is where FieldMaps' cell differs, the third where a cell line crosses the island; both set `review` | stage 08 |
| `D-<code>` | `land_area`: a disputed, shared or undetermined area on land, for information only. It cuts no units and stays out of the ADM0 output | `changes.json` |

`unit_id` is a hash of `un_objectid`, `gaul_id` and `area_id`.
