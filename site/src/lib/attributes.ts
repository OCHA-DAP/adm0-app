import { LAYERS } from "$lib/layers";

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
export interface AttributeRow {
  iso3: string;
  bbox: number[] | null;
  parts: Part[] | null;
  [column: string]: unknown;
}

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

function diffKinds(row: AttributeRow, groups: AttributeGroup[], filter: Filter): Set<DiffKind> {
  const kinds = new Set<DiffKind>();
  for (const group of groupsInScope(groups, filter)) {
    const sources = sourcesFor(group, filter);
    if (sources.length < 2) continue;
    const present = sources.map((s) => value(row, group.key, s)).filter(Boolean);
    if (present.length > 0 && present.length < sources.length) kinds.add("missing");
    if (new Set(present).size > 1) kinds.add("differs");
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

export function matches(row: AttributeRow, groups: AttributeGroup[], filter: Filter): boolean {
  const c = cached(row);
  if (filter.diff !== "all") {
    const key = `${filter.group}|${filter.sources.join()}`;
    let kinds = c.kinds.get(key);
    if (!kinds) c.kinds.set(key, (kinds = diffKinds(row, groups, filter)));
    if (!kinds.has(filter.diff)) return false;
  }
  const q = filter.query.trim().toLowerCase();
  return !q || c.haystack.includes(q);
}
