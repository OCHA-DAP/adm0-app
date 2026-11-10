# 2. Apply the OSM coastline to the extended units

## Status

Accepted

## Context

The build layer keeps UN Geodata 2023's coastline. OSM land polygons are more detailed and include islands UN Geodata never drew. UN Geodata also has land OSM draws as water: reefs such as Minerva and Scarborough, and the Caspian, which it divides into national sectors. The change must be repeatable and listable per entity for FAO, and FieldMaps already places UN Geodata attributes on OSM land.

## Decision

Extend the reviewed units with `edge-extend` (stage 07), then clip OSM land to the cells per OSM polygon (stage 08): whole to its only unit, cut by cells where several units have land in it, and by inner point for islands with no UN Geodata land. Use pure OSM: UN Geodata land touching no OSM land is dropped. FieldMaps' cells check new islands and gained land, without deciding ownership.

## Consequences

Both exports take the OSM coastline from the same units. No UN Geodata land changes owner, which `checks.json` measures. The Caspian sectors and reefs OSM lacks leave both exports and are listed as `D-` changes. Islands where FieldMaps disagrees, or that a cell line crosses, need partner review and are corrected through `coast_overrides.csv`.
