import h3 from "h3-js";
import { InvalidInputError, check } from "./errors.js";
export const OFFSETS = [0, 1, 8, 57, 400, 2801];
export const METHODS = [
  null,
  "city_polygon",
  "policy_polygon",
  "urban_allocation",
  "town_radius",
  "rural_polygon",
  "rural_nearest",
  "rural_nearest_distant",
];
export function query(kind, values = {}) {
  return {
    kind,
    latitude: null,
    longitude: null,
    h3: null,
    value: null,
    country: null,
    scheme: null,
    ...values,
  };
}
export function coordinates(latitude, longitude) {
  for (const [name, number, bound] of [
    ["latitude", latitude, 90],
    ["longitude", longitude, 180],
  ]) {
    if (typeof number !== "number")
      throw new InvalidInputError(`${name} must be a finite real number`);
    if (!Number.isFinite(number) || Math.abs(number) > bound)
      throw new InvalidInputError(
        `${name} must be finite and within ±${bound}`,
      );
  }
  if (longitude === 180) longitude = -180;
  return {
    cell: h3.latLngToCell(latitude, longitude, 8),
    query: query("coordinates", { latitude, longitude }),
  };
}
export function h3Input(value) {
  if (typeof value !== "string" || !/^[0-9a-fA-F]{15}$/.test(value))
    throw new InvalidInputError(
      "Expected a resolution-8 H3 hexadecimal string",
    );
  if (!h3.isValidCell(value) || h3.getResolution(value) !== 8)
    throw new InvalidInputError(
      "Only valid resolution-8 H3 cells are supported",
    );
  const cell = value.toLowerCase();
  return { cell, query: query("h3", { h3: cell }) };
}
export function address(cell) {
  const number = BigInt(`0x${cell}`);
  let block = Number((number >> 45n) & 127n),
    suffix = 0;
  for (let level = 1; level <= 8; level++) {
    const digit = Number((number >> BigInt(3 * (15 - level))) & 7n);
    if (level <= 3) block = block * 7 + digit;
    else suffix = suffix * 7 + digit;
  }
  return { block, suffix };
}
export function storedCell(block, key) {
  let depth = 5;
  while (key < OFFSETS[depth]) depth--;
  let digits = block * 7 ** depth + key - OFFSETS[depth];
  let number = 0x800000000000000n | (BigInt(depth + 3) << 52n);
  number |= (1n << BigInt(3 * (12 - depth))) - 1n;
  for (let level = depth + 3; level >= 1; level--) {
    number |= BigInt(digits % 7) << BigInt(3 * (15 - level));
    digits = Math.floor(digits / 7);
  }
  number |= BigInt(digits) << 45n;
  return number.toString(16);
}
export function labelCheck(label, count) {
  const [country, state, city, flags] = label;
  check(
    label.every((n) => Number.isSafeInteger(n) && n >= 0) &&
      country <= count &&
      state <= count &&
      city <= count &&
      flags < 64,
    "Invalid spatial label",
  );
  check(
    Boolean(country) === Boolean(flags & 8) &&
      Boolean(state) === Boolean(flags & 16) &&
      Boolean(city) === Boolean(flags & 7),
    "Method/null mismatch",
  );
}
export function methods(flags, known = true) {
  return {
    city: METHODS[flags & 7],
    state: flags & 16 ? "area" : null,
    country: flags & 8 ? "area" : null,
    land: known ? (flags & 32 ? "offshore" : "land") : "unknown",
  };
}
export function reference(cell, stored) {
  return {
    h3: cell,
    resolution: 8,
    stored_h3: stored,
    stored_resolution: stored === null ? null : h3.getResolution(stored),
    quantization: "r8-centre-logical-ancestors",
  };
}
