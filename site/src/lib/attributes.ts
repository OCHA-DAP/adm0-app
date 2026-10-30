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

// Status, region and map name follow different conventions per source, so only a source pair compares them.
export const GROUPS: AttributeGroup[] = [
  { key: "name", label: "Name", sources: ["gaul", "ungeodata", "fieldmaps", "wp", "unterm", "m49"], compare: true },
  { key: "mapname", label: "Map name", sources: ["ungeodata", "fieldmaps", "wp"], compare: false },
  { key: "mapcode", label: "Map code", sources: ["gaul"], compare: false },
  { key: "count", label: "Features", sources: ["gaul", "ungeodata", "fieldmaps", "wp"], compare: true },
  { key: "sovereign", label: "Sovereign", sources: ["ungeodata", "fieldmaps"], compare: true },
  { key: "status", label: "Status", sources: ["ungeodata", "fieldmaps", "wp", "unterm"], compare: false },
  { key: "region", label: "Region", sources: ["gaul", "ungeodata", "fieldmaps", "m49"], compare: false },
];

export const BASELINE = "gaul";

// Sources that publish their own entity list, as opposed to M49 which shares the ref table with UNTERM.
const ENTITY_SOURCES = Object.keys(SOURCES).filter((s) => s !== "m49");

export const DIFF_TYPES = {
  any: "Any difference",
  differs: "Value differs",
  missing: "Missing from a source",
  several: "Several features under one code",
  only: "Code in only one source",
  none: "No differences",
  all: "All rows",
} as const;
export type DiffType = keyof typeof DIFF_TYPES;
type DiffKind = "differs" | "missing" | "several" | "only";

export type AttributeRow = Record<string, string | number | null>;

export function value(row: AttributeRow, group: string, source: string): string {
  return String(row[`${group}_${source}`] ?? "").trim();
}

// Facets take the UN view first and fall back to fieldmaps, which follows it.
const facet = (group: string, source: string) => ({
  label: `${GROUPS.find((g) => g.key === group)!.label} (${SOURCES[source]})`,
  get: (r: AttributeRow) => value(r, group, source) || value(r, group, "fieldmaps"),
});
export const FACETS = {
  status: facet("status", "ungeodata"),
  region: facet("region", "m49"),
  sovereign: facet("sovereign", "ungeodata"),
};
export type Facet = keyof typeof FACETS;
const NONE = "(none)";

export type Filter = { group: string; diff: DiffType; pair: string; query: string } & Record<Facet, string>;
export const DEFAULT_FILTER: Filter = {
  group: "name",
  diff: "any",
  pair: "",
  query: "",
  ...(Object.fromEntries(Object.keys(FACETS).map((f) => [f, ""])) as Record<Facet, string>),
};

export function groupsInScope(filter: Filter): AttributeGroup[] {
  return filter.group ? GROUPS.filter((g) => g.key === filter.group) : GROUPS;
}

export function sourcesFor(group: AttributeGroup, filter: Filter): string[] {
  return filter.pair ? group.sources.filter((s) => s === BASELINE || s === filter.pair) : group.sources;
}

// Whether values in a group are compared at all; status and region only within a source pair.
export function compares(group: AttributeGroup, filter: Filter): boolean {
  return !!filter.pair || group.compare;
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
  const scoped = new Set<string>();
  for (const group of groupsInScope(filter)) {
    const sources = sourcesFor(group, filter);
    sources.forEach((s) => scoped.add(s));
    if (sources.length < 2) continue;
    const present = sources.map((s) => value(row, group.key, s)).filter(Boolean);
    if (present.length > 0 && present.length < sources.length) kinds.add("missing");
    if (compares(group, filter) && new Set(present).size > 1) kinds.add("differs");
  }
  if ([...scoped].some((s) => Number(row[`count_${s}`] ?? 0) > 1)) kinds.add("several");
  const entities = ENTITY_SOURCES.filter((s) => scoped.has(s));
  if (entities.length > 1 && entities.filter((s) => Number(row[`count_${s}`] ?? 0) > 0).length === 1) {
    kinds.add("only");
  }
  return kinds;
}

// Rows are loaded once and never mutated, so per-row derived values are cached for the option counts.
interface RowCache {
  haystack: string;
  facets: Record<Facet, string>;
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
      facets: Object.fromEntries(
        (Object.keys(FACETS) as Facet[]).map((f) => [f, FACETS[f].get(row) || NONE]),
      ) as Record<Facet, string>,
      kinds: new Map(),
    };
    cache.set(row, c);
  }
  return c;
}

export function facetValue(row: AttributeRow, facet: Facet): string {
  return cached(row).facets[facet];
}

export function matches(row: AttributeRow, filter: Filter): boolean {
  const c = cached(row);
  for (const facet of Object.keys(FACETS) as Facet[]) {
    if (filter[facet] && c.facets[facet] !== filter[facet]) return false;
  }
  if (filter.diff !== "all") {
    const key = `${filter.group}|${filter.pair}`;
    let kinds = c.kinds.get(key);
    if (!kinds) c.kinds.set(key, (kinds = diffKinds(row, filter)));
    if (filter.diff === "any" ? kinds.size === 0 : filter.diff === "none" ? kinds.size > 0 : !kinds.has(filter.diff)) {
      return false;
    }
  }
  const q = filter.query.trim().toLowerCase();
  return !q || c.haystack.includes(q);
}
