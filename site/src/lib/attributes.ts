import { LAYERS, SOURCES as MAP_SOURCES } from "$lib/layers";

// Columns in attributes.json from pipeline/attributes.py are `${group}_${source}`; map sources keep their map label.
export const SOURCES: Record<string, string> = {
  ...Object.fromEntries(LAYERS.map((l) => [l.source, l.label])),
  m49: "M49",
  unterm: "UNTERM",
};

export interface AttributeGroup {
  key: string;
  label: string;
  sources: string[];
}

const GROUP_LABELS = [
  { key: "name", label: "Name" },
  { key: "mapname", label: "Label" },
  { key: "count", label: "Features" },
  { key: "sovereign", label: "Sovereign" },
  { key: "status", label: "Status" },
  { key: "region", label: "Region" },
];

// Each group covers the sources the pipeline wrote a column for.
export function attributeGroups(row: AttributeRow | undefined): AttributeGroup[] {
  return GROUP_LABELS.map((g) => ({ ...g, sources: row ? Object.keys(SOURCES).filter((s) => `${g.key}_${s}` in row) : [] }));
}

export type DiffType = "differs" | "all";

// One feature of a code in one source; s is the attributes source, layer its polygon tile layer,
// name the map label tiles match on, label the map label or else the source's name.
export interface Part {
  s: string;
  id: string;
  layer: string;
  name: string;
  label: string | null;
  bbox: number[];
}

// bbox is [west, south, east, north]; east can pass 180 for codes across the antimeridian.
export interface AttributeRow {
  iso3: string;
  bbox: number[] | null;
  parts: Part[] | null;
  [column: string]: unknown;
}

export function value(row: AttributeRow | ItemRow, group: string, source: string): string {
  return String(row[`${group}_${source}`] ?? "").trim();
}

// sources limits the table to those sources; empty means all. ref is the source cells are compared
// against, or unset for the majority.
export type Filter = { group: string; diff: DiffType; sources: string[]; query: string; ref?: string };
export const DEFAULT_FILTER: Filter = {
  group: "name",
  diff: "differs",
  sources: [],
  query: "",
};

export type ItemType = "island" | "land" | "no_land";

// The Geometry pane's lists: differences split by kind.
export type GeometryList = "islands" | "land";
export const listOf = (type: ItemType | undefined): GeometryList => (type === "island" ? "islands" : "land");

// A geometry difference from items.json; title is its smallest entity's name, and pairs are the
// map's source pairs it has patches in. items lists the differences merged into this row.
export interface ItemRow {
  item: string;
  items?: string[];
  title: string | null;
  type: ItemType;
  same_code: boolean;
  missing: string[] | null;
  islands: number | null;
  km2: number | null;
  bbox: number[] | null;
  pairs: string[] | null;
  [column: string]: unknown;
}

// Item tables compare each source's entity as "CODE name".
export const ENTITY: AttributeGroup = { key: "entity", label: "Entity", sources: MAP_SOURCES };

export function prepareItems(items: ItemRow[]): ItemRow[] {
  for (const row of items) {
    for (const s of MAP_SOURCES) row[`entity_${s}`] = [row[`code_${s}`], row[`name_${s}`]].filter(Boolean).join(" ");
  }
  return items;
}

// A source's own text: the title, else the first code for items no source names.
export function itemTitle(row: ItemRow): string {
  const code = MAP_SOURCES.map((s) => row[`code_${s}`]).find(Boolean);
  return row.title?.trim() || String(code ?? row.item);
}

// One box around all boxes; across the antimeridian, western boxes move east by 360 when that is narrower.
export function unionBox(boxes: number[][]): number[] {
  const union = (bs: number[][]) => [Math.min(...bs.map((b) => b[0])), Math.min(...bs.map((b) => b[1])), Math.max(...bs.map((b) => b[2])), Math.max(...bs.map((b) => b[3]))];
  const plain = union(boxes);
  const east = union(boxes.map((b) => (b[2] <= 0 ? [b[0] + 360, b[1], b[2] + 360, b[3]] : b)));
  return plain[2] - plain[0] <= Math.max(180, east[2] - east[0]) ? plain : east;
}

// Differences of one type that a and b assign to the same two entities read as one, so they merge
// into one row, led by the first (largest) of them.
export function mergeItems(items: ItemRow[], a: string, b: string): ItemRow[] {
  const rows = new Map<string, ItemRow>();
  for (const it of items) {
    const key = [it.type, it[`code_${a}`], it[`name_${a}`], it[`code_${b}`], it[`name_${b}`]].join("|");
    const row = rows.get(key);
    if (!row) {
      rows.set(key, { ...it, items: [it.item] });
      continue;
    }
    row.items!.push(it.item);
    const boxes = [row.bbox, it.bbox].filter((x): x is number[] => !!x);
    row.bbox = boxes.length ? unionBox(boxes) : null;
    row.pairs = [...new Set([...(row.pairs ?? []), ...(it.pairs ?? [])])];
  }
  return [...rows.values()];
}

export function groupsInScope(groups: AttributeGroup[], filter: Filter): AttributeGroup[] {
  return filter.group ? groups.filter((g) => g.key === filter.group) : groups;
}

export function sourcesFor(group: AttributeGroup, filter: Filter): string[] {
  return filter.sources.length ? group.sources.filter((s) => filter.sources.includes(s)) : group.sources;
}

export const TIE = Symbol("tie");

// The most common non-empty value in a group, TIE when the top values are level, or null when all agree.
export function majority(
  row: AttributeRow,
  group: AttributeGroup,
  sources = group.sources,
): string | typeof TIE | null {
  const counts = new Map<string, number>();
  for (const s of sources) {
    const v = value(row, group.key, s);
    if (v) counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  if (counts.size < 2) return null;
  const [first, second] = [...counts].sort((a, b) => b[1] - a[1]);
  return first[1] === second[1] ? TIE : first[0];
}

// Sources whose value is marked as differing: from ref's value when ref is in scope, else from the majority.
export function marked(row: AttributeRow | ItemRow, group: AttributeGroup, sources: string[], ref = ""): Set<string> {
  const out = new Set<string>();
  if (ref && sources.includes(ref)) {
    const base = value(row as AttributeRow, group.key, ref);
    for (const s of sources) {
      const v = value(row as AttributeRow, group.key, s);
      if (s !== ref && v && base && v !== base) out.add(s);
    }
    return out;
  }
  const top = majority(row as AttributeRow, group, sources);
  if (top === null) return out;
  for (const s of sources) {
    const v = value(row as AttributeRow, group.key, s);
    if (v && (sources.length === 2 || top === TIE || v !== top)) out.add(s);
  }
  return out;
}

function differs(row: AttributeRow, groups: AttributeGroup[], filter: Filter): boolean {
  return groupsInScope(groups, filter).some((group) => {
    const sources = sourcesFor(group, filter);
    return sources.length >= 2 && marked(row, group, sources, filter.ref).size > 0;
  });
}

// Rows are loaded once and never mutated, so per-row derived values are cached.
interface RowCache {
  haystack: string;
  differs: Map<string, boolean>;
}
const cache = new WeakMap<AttributeRow, RowCache>();

function cached(row: AttributeRow): RowCache {
  let c = cache.get(row);
  if (!c) {
    c = {
      haystack: Object.values(row)
        .map((v) => String(v ?? "").toLowerCase())
        .join("\n"),
      differs: new Map(),
    };
    cache.set(row, c);
  }
  return c;
}

export function matches(row: AttributeRow | ItemRow, groups: AttributeGroup[], filter: Filter): boolean {
  const c = cached(row as AttributeRow);
  if (filter.diff !== "all") {
    const key = `${filter.group}|${filter.sources.join()}|${filter.ref ?? ""}`;
    let hit = c.differs.get(key);
    if (hit === undefined) c.differs.set(key, (hit = differs(row as AttributeRow, groups, filter)));
    if (!hit) return false;
  }
  const q = filter.query.trim().toLowerCase();
  return !q || c.haystack.includes(q);
}
