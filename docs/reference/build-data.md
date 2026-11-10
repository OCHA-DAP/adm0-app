# Build layer data

Build with `uv run python -m pipeline --step build`, one stage with `--stage NN`, or a stage and all after it with `--from NN`. Stage 00 and stage 07 run only by name. Stage 01 skips when its code and sources match the manifest, stage 06 when its code, `units`, `changes.json` and `path.json` do, stage 07 when its code and `units` do, and stage 08 when its inputs do. Stage 08 also skips while stage 07's cells come from older `units`. `COAST_BBOX=xmin,ymin,xmax,ymax` runs stage 08 on one area into `tmp/coast_bbox/`, without the exports or the manifest. Stage 09 tiles only layers whose source changed.

## Curated inputs (`inputs/build/`)

| File | Contents |
|---|---|
| `changes.json` | One record per curated change: `id`, `type`, `title`, `description`, `keys` (pairs of UN `objectid` and `gaul_id`), `relabel` (a `un_error` change without keys: `un_objectid` and `gaul_id` of the units that take the UN entity `to` until a change with keys applies), `values` (per UN and GAUL pair: `un_objectid`, `un`, `un_name`, `gaul`, `gaul_name`, `km2`), `gaul_removed` (the GAUL entity the land leaves) and `removed_parts` (parts not carried over), `largest_patch_bbox` (line updates), `cut` (target `objectid`s and `bndl` line ids), `method`, `source`, `comment` |
| `cut_lines.parquet` | Cut geometry UN Geodata lacks, written by stage 00: `change_id`, `area_id`, `source_layer`, `source_feature` |
| `coast_overrides.csv` | `lon`, `lat` (a point on the OSM land polygon), `unit_id` (the unit it goes to, `drop`, or a new entity's code), `name` (the new entity's name), `change_id`, `reason`. Applies to OSM polygons with land of at most one unit. A new entity gets its own row in both exports, with UN Geodata's disputed status (`stscod` 99) |
| `island_overrides.csv` | `un_objectid`, `un_part`, `face`, `gaul_id`, `change_id`, `reason`. A blank part or face matches all |
| `review_decisions.csv` | `un`, `fieldmaps`, `action`, `reason`. `remove` drops a UN and FieldMaps pair from review, `recode` moves it to the islands step |
| `stages.json` | Plain-language description of each stage |
| `path.json` | The page's steps from GAUL to the build layer, the change types in each, the two tile layers each step compares (previous step's output, then its own), `labels` (the step labels its changes on the map), and the legend label for each |

## Stages (`outputs/build/`)

| Folder | Files |
|---|---|
| `01_source` | `un_polygons`, `un_lines`, `gaul_polygons`, `gaul_voronoi` (their lower-case `x` codes, `xxx` included, as upper-case ISO 3166-1 user-assigned codes, and UN Geodata's `xRI` as `XKI`), `fieldmaps_voronoi`, `gaul_bits` (GAUL polygons in small pieces for fast overlaps), `line_overlaps` (`a_code` GAUL, `b_code` UN, `km2`: land the two polygon sets give different entities) |
| `02_split` | `un_parts`: `un_objectid`, `un_iso3`, `un_part` |
| `03_cut` | `faces`: adds `face` (0 for an uncut part) and `area_id`. `cuts`: each cut line and its source |
| `04_attribute` | `parts`: adds `gaul_id`, `rule` (`overlap`, `cell`, `un_owner`, `override`), `gaul_id_before_override`, `overlap_share`, `change_id`, `reason`. `removed`: GAUL polygons touching no UN land |
| `05_units` | `units`, `crosswalk` (parquet and CSV), `changes` (JSON and CSV), `change_areas`, `line_patches`, `cell_islands` (`change_id`, `km2`), `labels.geojson` (a point inside each polygon of each change: `change`, `km2`, `text`, the UN and GAUL codes, or the UN and GAUL names on the largest polygon only where the code is the same) |
| `06_export` | `un`, `gaul`, `path_errors` and `path_disputed` (units dissolved with the changes up to that page step applied; `key` plus the source attributes of the GAUL or UN entity each row is at that step), `checks.json` |
| `07_extend` | `units_voronoi`: `units` extended into water with `topo-tools edge-extend` |
| `08_coast` | `coast_units` (the `units` columns on OSM land), `un` and `gaul` dissolved from it, `gained` and `lost` (`change_id`, `km2`; `gained` adds `fm_code` and `fm_differs`), `new_islands` (`change_id`, `fid`, `km2`, `straddle`, `fm_code`), `dropped` (UN Geodata parts touching no OSM land), `changes.json`, `checks.json` |
| `09_site` | PMTiles and tables for the build page, and `names.json` (ISO3 to M49 name, with TWN added) for the map border labels |

`manifest.json` records, per stage: build time, git commit, tool versions, input and output SHA-256s, and row and area totals. Each folder's `README.md` is generated from `stages.json` and the manifest.

## Change ids

| Prefix | Meaning | Written in |
|---|---|---|
| `C` | Curated change | `changes.json` |
| `I-<UN iso3>-<gaul_id>` | The sources give islands to different entities | stage 05 |
| `G-<gaul_id>` | GAUL land touching no UN land | stage 05 |
| `E-<UN iso3>-<FieldMaps code>` | UN Geodata polygon parts inside a FieldMaps Voronoi cell with a different code, ignoring case, with `review` set. They stay out of `change_ids`, and ownership is unchanged. Their geometry sits in `cell_islands` | stage 05 |
| `V-<UN iso3>-<GAUL code>` | Islands with no GAUL polygon inside another entity's GAUL Voronoi cell, kept with the UN owner in both exports. They stay out of `change_ids` | stage 05 |
| `L-<code>-<code>` | Land GAUL and UN Geodata polygons give different entities along a border, in patches of 0.01 km² or more | stage 05 |

| `K-<code>` | OSM coastline of one entity in the UN export: `gained_km2`, `lost_km2`, `un_km2`, `kept_km2`, `fieldmaps_differs_km2` (gained land FieldMaps' cell gives to another code) | stage 08 |
| `N-<code>`, `N-<code>-<FieldMaps code>`, `N-<code>-straddle` | OSM islands with no UN Geodata land, given to the unit whose cell holds their inner point. The second form is where FieldMaps' cell differs, the third where a cell line crosses the island; both set `review` | stage 08 |
| `D-<code>` | UN Geodata parts touching no OSM land, dropped from both exports | stage 08 |

`unit_id` is a hash of `un_objectid`, `gaul_id` and `area_id`.
