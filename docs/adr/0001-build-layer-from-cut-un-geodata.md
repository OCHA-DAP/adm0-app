# 1. Build the build layer from cut UN Geodata polygons

## Status

Accepted

## Context

FAO GAUL keeps 272 entities on lines from the 2018 UN Geodata. UN Geodata 2023 has better lines but draws several GAUL entities inside neighbours. Every change must be clear to FAO, and no dissolve decision may be irreversible.

Cutting the existing UN Voronoi cells was tested first. UN lines stop at the coast, so the Hala'ib line left the Sudan cell uncut, and water boundaries would have to be supplied from GAUL's cells.

## Decision

Cut the UN polygons with UN's own lines, using GAUL's lines only where UN has none. Attribute islands to GAUL entities as whole polygons after the cut. Extend the reviewed units into water with `edge-extend` as the last step. Store each unit with a UN key and a GAUL key, and produce both exports from a crosswalk.

## Consequences

Water boundaries come from `edge-extend`, so no water cuts are needed. Land exports are exact. Extended cells dissolved by UN key can differ slightly in water from the accepted UN Voronoi. Ownership differences between the sources become units, which adds to the layer but keeps both exports possible.
