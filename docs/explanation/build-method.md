# Why the build layer is built this way

The build layer lets one set of polygons serve two views of the world. Dissolved by UN key, it returns UN Geodata 2023. Dissolved by GAUL key, it returns the GAUL entities and codes on UN 2023 lines.

## UN Geodata is the base

GAUL's lines come from the 2018 UN Geodata, and the 2023 lines improve on them. Starting from UN keeps those improvements, and every step away from UN is listed as a change.

## Units and a crosswalk

A unit is land with one UN entity and one GAUL entity. Keeping both keys on each unit means no choice is final: an area such as Bir Tawil stays separate until someone decides to dissolve it, and that decision is a change to the crosswalk, not to the geometry.

## Cuts and islands

UN's own lines make the cuts wherever they exist. UN lines stop at the coast, so a cut divides a mainland and leaves its islands untouched. Islands are attributed afterwards as whole polygons: the GAUL entity with the largest overlap, then any listed override. An island with no GAUL overlap takes its GAUL cell only when GAUL already links its UN entity to that cell's entity, or that entity has no other land (as with Hong Kong and Macao). Otherwise it stays with the main GAUL entity of its UN entity, because the nearest cell says nothing about ownership.

The India-China areas have no UN lines, so GAUL's outlines and line are used. The cut lines are stored with their source so each can be reviewed.

## Extending last

The units are extended into the water only after they have been reviewed. The resulting cells separate political divisions from the coastline, so a coastline becomes a final clip that can be swapped.
