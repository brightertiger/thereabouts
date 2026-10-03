export type Status =
  | "matched"
  | "ambiguous"
  | "not_found"
  | "invalid_input"
  | "unsupported_granularity";
export type Kind =
  | "cell"
  | "city"
  | "postal"
  | "airport"
  | "trade_location"
  | "ip_range"
  | "phone_prefix"
  | "plate";
export type Match =
  | "exact"
  | "alternate_name"
  | "fuzzy"
  | "contained"
  | "nearest"
  | "nearest_distant";
export type Family =
  | "core"
  | "postal"
  | "airports"
  | "locode"
  | "phone"
  | "ip"
  | "plates";
export interface Point {
  readonly lat: number;
  readonly lon: number;
}
export interface Country {
  readonly code: string;
  readonly code3: string | null;
  readonly name: string;
}
export interface State {
  readonly code: string | null;
  readonly name: string;
}
export interface City {
  readonly id: string;
  readonly name: string;
  readonly name_en: string | null;
  readonly kind: string;
  readonly population: number | null;
  readonly point: Point | null;
}
export type Json =
  | null
  | boolean
  | number
  | string
  | readonly Json[]
  | { readonly [key: string]: Json };
export interface Evidence {
  readonly stored_cell: string | null;
  readonly country_id: string | null;
  readonly state_id: string | null;
  readonly city_id: string | null;
  readonly city_method: string | null;
  readonly land_method: string | null;
  readonly reason: string | null;
  readonly timezones: readonly string[];
  readonly source_ids: Json;
}
export interface Result {
  readonly status: Status;
  readonly kind: Kind;
  readonly match: Match | null;
  readonly country: Country | null;
  readonly state: State | null;
  readonly city: City | null;
  readonly timezone: string | null;
  readonly point: Point | null;
  readonly cell: string | null;
  readonly distance_band: {
    readonly greater_than_km: number;
    readonly at_most_km: number;
  } | null;
  readonly candidates: readonly Result[];
  readonly rank_basis: string | null;
  readonly hint?: string;
  readonly evidence?: Evidence;
}
export interface Options {
  evidence?: boolean;
}
export interface CountryOptions extends Options {
  country?: string;
}
export interface OpenOptions {
  dataDir?: string;
  pack?: string;
  packs?: Partial<Record<Family, string>>;
  verify?: boolean;
}
export class Geocoder {
  private constructor();
  static open(options?: OpenOptions): Promise<Geocoder>;
  reverse(point: Point & Options): Promise<Result>;
  fromH3(cell: string, options?: Options): Promise<Result>;
  postal(code: string, options?: CountryOptions): Promise<Result>;
  airport(
    code: string,
    options?: CountryOptions & {
      scheme?: "iata" | "icao" | "gps" | "local" | "ident";
    },
  ): Promise<Result>;
  locode(code: string, options?: CountryOptions): Promise<Result>;
  phone(number: string, options?: CountryOptions): Promise<Result>;
  ip(address: string, options?: Options): Promise<Result>;
  plate(
    text: string,
    options?: CountryOptions & { series?: string },
  ): Promise<Result>;
  /** Finds towns and cities by name. Street addresses are not supported. */
  geocode(
    text: string,
    options?: CountryOptions & {
      subdivision?: string;
      limit?: number;
      prefer?: "population";
      scope?: "cities";
    },
  ): Promise<Result>;
  reverseMany(
    points: Iterable<Point> | AsyncIterable<Point>,
    options?: Options,
  ): AsyncIterable<Result>;
  close(): Promise<void>;
}
export function reverse(point: Point & Options): Promise<Result>;
export class ThereaboutsError extends Error {
  readonly code: string;
}
export class DataNotInstalledError extends ThereaboutsError {
  readonly family: Family;
}
export class IncompatibleDataError extends ThereaboutsError {}
export class CorruptPackError extends ThereaboutsError {}
export class ClosedGeocoderError extends ThereaboutsError {}
export class PackNotFoundError extends ThereaboutsError {}
