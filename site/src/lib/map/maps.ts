import * as maplibregl from "maplibre-gl";
import { applyDraws, buildStyle, type Draw } from "$lib/map/style";

export interface DrawMap {
  map: maplibregl.Map;
  setDraws(draws: Draw[]): void;
  destroy(): void;
}

// A map whose source layers follow `setDraws`, queued until the style loads.
export function createDrawMap(
  container: HTMLElement,
  tilesBase: string,
  draws: Draw[],
  options: Partial<maplibregl.MapOptions> = {},
): DrawMap {
  const map = new maplibregl.Map({ container, style: buildStyle(tilesBase, draws), ...options });
  let current = draws;
  let ready = false;
  map.once("load", () => {
    ready = true;
    applyDraws(map, current);
  });
  return {
    map,
    setDraws(next) {
      current = next;
      if (ready) applyDraws(map, next);
    },
    destroy: () => map.remove(),
  };
}

export interface Overlay extends DrawMap {
  setActive(active: boolean): void;
}

// A passive map stacked over `main` that mirrors its camera while active, for CSS clip-path reveals.
export function createOverlay(main: maplibregl.Map, container: HTMLElement, tilesBase: string, draws: Draw[]): Overlay {
  const camera = () => ({
    center: main.getCenter(),
    zoom: main.getZoom(),
    bearing: main.getBearing(),
    pitch: main.getPitch(),
  });
  const top = createDrawMap(container, tilesBase, draws, { interactive: false, attributionControl: false, ...camera() });
  const sync = () => top.map.jumpTo(camera());
  let active = false;
  return {
    ...top,
    setActive(next) {
      if (next === active) return;
      active = next;
      if (next) {
        sync();
        main.on("move", sync);
      } else {
        main.off("move", sync);
      }
    },
    destroy() {
      main.off("move", sync);
      top.destroy();
    },
  };
}
