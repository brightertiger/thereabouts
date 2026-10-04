/// <reference lib="esnext.disposable" />
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
/** Explicit input labels; omitted frame means WGS84 geodetic only. */
export type Frame =
  | "geodetic"
  | "latlon"
  | "lla"
  | "llh"
  | "ecef"
  | "enu"
  | "ned"
  | "utm"
  | "mgrs"
  | "geohash"
  | "pluscode"
  | "h3"
  | "s2"
  | "dms"
  | "nmea"
  | "geojson"
  | "wkt";
export interface GeodeticComponents {
  lat: number;
  lon: number;
  height?: number | null;
  height_datum?: string | null;
  geoid_separation?: number | null;
}
// Forbid components from other members, including when the default frame is omitted.
type UnionKeys<T> = T extends unknown ? keyof T : never;
type ExclusiveMember<T, All> = T extends unknown
  ? T & Partial<Record<Exclude<UnionKeys<All>, keyof T>, never>>
  : never;
type Exclusive<T> = ExclusiveMember<T, T>;
type OriginShape =
  | (GeodeticComponents & { frame?: "geodetic" | "latlon" | "lla" | "llh" })
  | { frame: "ecef"; x: number; y: number; z: number };
export type Origin = Exclusive<OriginShape>;
export interface CoordinateUncertainty {
  accuracy_m?: number | null;
  hdop?: number | null;
  vdop?: number | null;
}
type CoordinateFrames =
  | OriginShape
  | { frame: "enu"; e: number; n: number; u: number; origin: Origin }
  | { frame: "ned"; n: number; e: number; d: number; origin: Origin }
  | {
      frame: "utm";
      zone: number;
      hemisphere?: "N" | "S" | null;
      band?: string | null;
      easting: number;
      northing: number;
    }
  | { frame: "mgrs" | "geohash" | "dms" | "nmea" | "wkt"; value: string }
  | { frame: "pluscode"; value: string; reference?: GeodeticComponents | null }
  | { frame: "h3" | "s2"; cell: string | bigint }
  | {
      frame: "geojson";
      type?: "Point";
      coordinates: readonly [number, number, number?];
    };
export type CoordinatePoint = Exclusive<CoordinateFrames> & {
  uncertainty?: CoordinateUncertainty | null;
};
export interface Geodetic {
  readonly lat: number;
  readonly lon: number;
  readonly height: number | null;
  readonly height_datum: string | null;
  readonly geoid_separation: number | null;
}
export type QueryOrigin =
  | (Geodetic & { readonly frame: "geodetic" })
  | {
      readonly frame: "ecef";
      readonly x: number;
      readonly y: number;
      readonly z: number;
    };
export interface Height {
  readonly value_m: number;
  readonly datum: string;
  readonly geoid_separation_m: number | null;
}
export interface Uncertainty {
  readonly accuracy_m: number | null;
  readonly hdop: number | null;
  readonly vdop: number | null;
}
export interface CellExtent {
  readonly boundary: readonly Point[];
  readonly half_lat_deg: number | null;
  readonly half_lon_deg: number | null;
  readonly grid_size_m: number | null;
  /** Spherical centre-to-vertex summary, not a confidence radius. */
  readonly radius_m: number;
}
export interface NmeaFix {
  readonly talker: string;
  readonly sentence: string;
  readonly utc: string | null;
  readonly quality: number | null;
  readonly satellites: number | null;
}
export interface CoordIssue {
  readonly code: string;
  readonly message: string;
}
export interface QueryMetadata {
  readonly input_frame: string;
  readonly declared_frame: string | null;
  readonly normalized: Geodetic | null;
  readonly origin: QueryOrigin | null;
  readonly conversion: readonly string[];
  readonly source_height: Height | null;
  readonly uncertainty: Uncertainty;
  readonly cell_extent: CellExtent | null;
  readonly nmea: NmeaFix | null;
  readonly error: CoordIssue | null;
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
  readonly query?: QueryMetadata;
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
  reversePoint(point: CoordinatePoint, options?: Options): Promise<Result>;
  reversePoints(
    points: Iterable<CoordinatePoint> | AsyncIterable<CoordinatePoint>,
    options?: Options,
  ): AsyncIterable<Result>;
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
  [Symbol.asyncDispose](): Promise<void>;
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
