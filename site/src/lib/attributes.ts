// Column groups for attributes.json from pipeline/attributes.py; each column is `${group}_${source}`.
export const SOURCES: Record<string, string> = {
  gaul: "GAUL",
  ungeodata: "UN Geodata",
  fieldmaps: "FieldMaps",
  wp: "World Polygons",
  m49: "M49",
  unterm: "UNTERM",
};

export interface AttributeGroup {
  key: string;
  label: string;
  sources: string[];
  compare: boolean;
}

// Status, region and map name follow different conventions per source, so only two sources at a time compare them.
export const GROUPS: AttributeGroup[] = [
  { key: "name", label: "Name", sources: ["gaul", "ungeodata", "fieldmaps", "wp", "unterm", "m49"], compare: true },
  { key: "mapname", label: "Map name", sources: ["ungeodata", "fieldmaps", "wp"], compare: false },
  { key: "count", label: "Features", sources: ["gaul", "ungeodata", "fieldmaps", "wp"], compare: true },
  { key: "sovereign", label: "Sovereign", sources: ["ungeodata", "fieldmaps"], compare: true },
  { key: "status", label: "Status", sources: ["ungeodata", "fieldmaps", "wp", "unterm"], compare: false },
  { key: "region", label: "Region", sources: ["gaul", "ungeodata", "fieldmaps", "m49"], compare: false },
];

// Map sources (layers.json) to their attributes.json source.
export const ATTRIBUTE_SOURCE: Record<string, string> = { gaul: "gaul", ungeodata: "ungeodata", fieldmaps: "fieldmaps", state_dept: "wp" };

type DiffKind = "differs" | "missing";
export type DiffType = DiffKind | "all";

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
export type AttributeRow = Record<string, string | number | number[] | Part[] | null>;

export function value(row: AttributeRow, group: string, source: string): string {
  return String(row[`${group}_${source}`] ?? "").trim();
}

// sources limits the table to those sources; empty means all.
export type Filter = { group: string; diff: DiffType; sources: string[]; query: string };
export const DEFAULT_FILTER: Filter = {
  group: "name",
  diff: "differs",
  sources: [],
  query: "",
};

export function groupsInScope(filter: Filter): AttributeGroup[] {
  return filter.group ? GROUPS.filter((g) => g.key === filter.group) : GROUPS;
}

export function sourcesFor(group: AttributeGroup, filter: Filter): string[] {
  return filter.sources.length ? group.sources.filter((s) => filter.sources.includes(s)) : group.sources;
}

// Whether values in a group are compared at all; status and region only between two sources.
export function compares(group: AttributeGroup, filter: Filter): boolean {
  return filter.sources.length === 2 || group.compare;
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

function diffKinds(row: AttributeRow, filter: Filter): Set<DiffKind> {
  const kinds = new Set<DiffKind>();
  for (const group of groupsInScope(filter)) {
    const sources = sourcesFor(group, filter);
    if (sources.length < 2) continue;
    const present = sources.map((s) => value(row, group.key, s)).filter(Boolean);
    if (present.length > 0 && present.length < sources.length) kinds.add("missing");
    if (compares(group, filter) && new Set(present).size > 1) kinds.add("differs");
  }
  return kinds;
}

// Rows are loaded once and never mutated, so per-row derived values are cached.
interface RowCache {
  haystack: string;
  kinds: Map<string, Set<DiffKind>>;
}
const cache = new WeakMap<AttributeRow, RowCache>();

function cached(row: AttributeRow): RowCache {
  let c = cache.get(row);
  if (!c) {
    c = {
      haystack: Object.values(row)
        .map((v) => String(v ?? "").toLowerCase())
        .join("\n"),
      kinds: new Map(),
    };
    cache.set(row, c);
  }
  return c;
}

export function matches(row: AttributeRow, filter: Filter): boolean {
  const c = cached(row);
  if (filter.diff !== "all") {
    const key = `${filter.group}|${filter.sources.join()}`;
    let kinds = c.kinds.get(key);
    if (!kinds) c.kinds.set(key, (kinds = diffKinds(row, filter)));
    if (!kinds.has(filter.diff)) return false;
  }
  const q = filter.query.trim().toLowerCase();
  return !q || c.haystack.includes(q);
}
