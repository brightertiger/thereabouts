export type Json =
  | null
  | boolean
  | number
  | string
  | readonly Json[]
  | { readonly [key: string]: Json };
export type Family = "reverse" | "postal" | "airports";
export type AirportScheme = "iata" | "icao" | "ident" | "gps" | "local";
export interface Evidence {
  readonly golden_table: string;
  readonly source_ids: Json;
  readonly name_provenance: Json;
}
export interface Place {
  readonly id: string;
  readonly name: string;
  readonly name_en: string | null;
  readonly local_name: string | null;
  readonly role: string;
  readonly settlement_kind: string;
  readonly country_code: string;
  readonly code: string | null;
  readonly code_status: string | null;
  readonly code_system: null;
  readonly country_id: string | null;
  readonly parent_id: string | null;
  readonly sovereign_id: string | null;
  readonly normalized_city_id: string | null;
  readonly parent_method: string | null;
  readonly normalization_method: string | null;
  readonly evidence: Evidence;
}
export interface SourcePlace {
  readonly id: string;
  readonly name: string | null;
  readonly role: "airport";
  readonly country_code: string | null;
  readonly codes: Readonly<Record<AirportScheme, string | null>>;
  readonly type: string | null;
}
export interface Methods {
  readonly city:
    | null
    | "city_polygon"
    | "policy_polygon"
    | "urban_allocation"
    | "town_radius"
    | "rural_polygon"
    | "rural_nearest"
    | "rural_nearest_distant";
  readonly state: "area" | null;
  readonly country: "area" | null;
  readonly land: "land" | "offshore" | "unknown";
}
export interface Reference {
  readonly h3: string;
  readonly resolution: 8;
  readonly stored_h3: string | null;
  readonly stored_resolution: number | null;
  readonly quantization: "r8-centre-logical-ancestors";
}
export interface Observation {
  readonly source: string;
  readonly source_id: string;
  readonly source_release: string;
  readonly license: string;
  readonly golden_table: string;
  readonly fields: Readonly<Record<string, Json>>;
  readonly reference: Reference | null;
  readonly country_id: string | null;
  readonly state_id: string | null;
  readonly city_id: string | null;
  readonly methods: Methods;
  readonly cell_status: "matched" | "unassigned" | "ineligible" | "unlocated";
  readonly country_disagrees: boolean | null;
}
export interface Candidate {
  readonly id: string;
  readonly place: SourcePlace | null;
  readonly city: Place | null;
  readonly state: Place | null;
  readonly country: Place | null;
  readonly sovereign: Place | null;
  readonly relationship: "spatial_context" | "source_association";
  readonly methods: Methods;
  readonly confidence: {
    readonly basis: string;
    readonly calibrated_probability: null;
  };
  readonly distance: null | {
    readonly greater_than_m: number | null;
    readonly at_most_m: number;
    readonly cutoff_m: number;
    readonly exact_m: null;
  };
  readonly accuracy_m: null;
  readonly observations: readonly Observation[];
}
export interface Query {
  readonly kind: "coordinates" | "h3" | "postal" | "airport";
  readonly latitude: number | null;
  readonly longitude: number | null;
  readonly h3: string | null;
  readonly value: string | null;
  readonly country: string | null;
  readonly scheme: AirportScheme | null;
}
export interface Source {
  readonly source: string;
  readonly release: string;
  readonly license: string;
  readonly attribution: string;
  readonly source_url: string;
  readonly license_url: string;
}
export interface Data {
  readonly family: Family;
  readonly version: string;
  readonly catalogue_epoch: string;
  readonly manifest_sha256: string;
  readonly golden_sha256: string;
  readonly policy_sha256: string;
  readonly h3_version: string;
  readonly sources: readonly Source[];
}
export interface Resolution {
  readonly status:
    | "matched"
    | "ambiguous"
    | "not_found"
    | "unassigned"
    | "ineligible"
    | "outside_coverage"
    | "invalid_input";
  readonly selected: Candidate | null;
  readonly candidates: readonly Candidate[];
  readonly query: Query;
  readonly reference: Reference | null;
  readonly data: Data;
  readonly warnings: readonly { readonly code: string }[];
  readonly error: {
    readonly code: "invalid_input";
    readonly message: string;
  } | null;
}
export interface OpenOptions {
  pack?: string;
  packs?: Partial<Record<Family, string>> | readonly Family[];
  dataDir?: string;
  verify?: boolean;
  cacheBytes?: number;
}
export interface BatchOptions {
  errors?: "raise" | "collect";
  chunkSize?: number;
}
export interface CacheInfo {
  budget_bytes: number;
  retained_bytes: number;
  entries: number;
  hits: number;
  misses: number;
  evictions: number;
}
export interface Info {
  backend: "javascript";
  packs: Partial<Record<Family, Record<string, Json>>>;
  cache: Partial<Record<Family, { raw: CacheInfo; decoded: CacheInfo }>>;
}
export class Geocoder {
  private constructor();
  static open(options?: OpenOptions): Promise<Geocoder>;
  reverse(latitude: number, longitude: number): Promise<Resolution>;
  fromH3(cell: string): Promise<Resolution>;
  postal(value: string, options: { country: string }): Promise<Resolution>;
  airport(
    value: string,
    options: { scheme: AirportScheme; country?: string },
  ): Promise<Resolution>;
  reverseMany(
    points:
      | Iterable<readonly [number, number]>
      | AsyncIterable<readonly [number, number]>,
    options?: BatchOptions,
  ): AsyncIterableIterator<Resolution>;
  fromH3Many(
    cells: Iterable<string> | AsyncIterable<string>,
    options?: BatchOptions,
  ): AsyncIterableIterator<Resolution>;
  info(): Info;
  explain(result: Resolution): {
    result: Resolution;
    raw_evidence_installed: false;
  };
  close(): Promise<void>;
}
export function requireOne(result: Resolution): Candidate | null;
export function dataDirectory(explicit?: string): string;
export function importPack(
  source: string,
  options: { dataDir?: string; manifestSha256: string },
): Promise<string>;
export function verifyPack(path: string): Promise<Record<string, Json>>;
export class ThereaboutsError extends Error {}
export class InvalidInputError extends ThereaboutsError {}
export class ContextRequiredError extends InvalidInputError {}
export class CorruptPackError extends ThereaboutsError {}
export class UnsupportedPackError extends ThereaboutsError {}
export class IncompatibleDataError extends ThereaboutsError {}
export class ClosedReaderError extends ThereaboutsError {}
export class AmbiguousResultError extends ThereaboutsError {}
export class DataNotInstalledError extends ThereaboutsError {}
