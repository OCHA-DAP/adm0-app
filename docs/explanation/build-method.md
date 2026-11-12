# Why the build layer is built this way

The build layer is one set of polygons that carries a UN key and a GAUL key on every unit. Dissolved by UN key, it returns UN Geodata 2023 for the checks and the page. Dissolved by ADM0 row, it gives the one output.

## UN Geodata is the base

GAUL's lines come from the 2018 UN Geodata, and the 2023 lines improve on them. Starting from UN keeps those improvements, and every step away from UN is listed as a change.

## Units and a crosswalk

A unit is land with one UN entity and one GAUL entity. Keeping both keys on each unit means no choice is final: an area such as Bir Tawil stays separate until someone decides to dissolve it, and that decision is a change to the crosswalk, not to the geometry.

## Cuts and islands

UN's own lines make the cuts wherever they exist. UN lines stop at the coast, so a cut divides a mainland and leaves its islands untouched. Islands are attributed afterwards as whole polygons: the GAUL entity with the largest overlap, then any listed override. An island with no GAUL overlap takes its GAUL cell only when GAUL already links its UN entity to that cell's entity, or that entity has no other land (as with Hong Kong and Macao). Otherwise it stays with the main GAUL entity of its UN entity, because the nearest cell says nothing about ownership.

The India-China areas have no UN lines, so GAUL's outlines and line are used. The cut lines are stored with their source so each can be reviewed.

## Extending last, then the OSM coastline

The units are extended into the water only after they have been reviewed. The resulting cells separate political divisions from the coastline, so OSM land becomes a final clip that decides where land is, while the cells decide who holds it.

The clip works per OSM polygon, so an island is never divided. A polygon with land of one unit goes to that unit whole. A polygon with land of several units (a mainland, or an island such as Hispaniola) is cut by their cells, whose lines on land are UN's own, so no UN Geodata land changes owner. A polygon with no UN Geodata land goes to the cell holding its inner point. UN Geodata land that touches no OSM land, such as reefs and the Caspian sectors, is dropped, and both are listed per entity.

The cell of the reviewed units decides new islands, and FieldMaps' cells only check them. FieldMaps knows neither the curated changes nor the entities GAUL keeps, so following it would reopen settled ownership. Islands where the two agree need no review.
