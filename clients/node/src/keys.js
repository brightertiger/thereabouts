import {
  ContextRequiredError,
  InvalidInputError,
  check,
  fields,
} from "./errors.js";

export const SCHEMES = ["iata", "icao", "ident", "gps", "local"];
const operations = ["strip_ascii", "upper_ascii", "remove_ascii_spaces"];
const strip = (value) =>
  value.replace(/^[\x09-\x0d\x20]+|[\x09-\x0d\x20]+$/g, "");
const upper = (value) => value.replace(/[a-z]/g, (c) => c.toUpperCase());
export function countryCode(value) {
  if (value == null) throw new ContextRequiredError("A country is required");
  if (typeof value !== "string")
    throw new InvalidInputError("Country must be a two-letter code");
  const country = upper(strip(value));
  if (!/^[A-Z]{2}$/.test(country))
    throw new InvalidInputError("Country must be a two-letter code");
  return country;
}
export function normalization(rules) {
  fields(rules, ["default", "countries"]);
  check(
    rules.countries &&
      typeof rules.countries === "object" &&
      !Array.isArray(rules.countries),
    "Invalid country rules",
  );
  for (const country of Object.keys(rules.countries))
    check(/^[A-Z]{2}$/.test(country), "Invalid country rule");
  for (const list of [rules.default, ...Object.values(rules.countries)]) {
    check(
      Array.isArray(list) &&
        list.every((op) => operations.includes(op)) &&
        new Set(list).size === list.length,
      "Invalid normalization",
    );
  }
}
export function normalize(value, rules, country) {
  if (typeof value !== "string" || value.includes("\0"))
    throw new InvalidInputError(
      "Code must be a string without NUL; preserve leading zeros",
    );
  for (const operation of rules.countries[country] ?? rules.default) {
    if (operation === "strip_ascii") value = strip(value);
    if (operation === "upper_ascii") value = upper(value);
    if (operation === "remove_ascii_spaces") value = value.replaceAll(" ", "");
  }
  if (!value) throw new InvalidInputError("Code must not be empty");
  if (!value.isWellFormed())
    throw new InvalidInputError("Code must be valid Unicode");
  return value;
}
export function compound(family, code, country, scheme) {
  if (family === "postal") {
    if (country === null)
      throw new ContextRequiredError("Postal lookup requires a country");
    return `${country}\0${code}`;
  }
  if (scheme === null)
    throw new ContextRequiredError(
      "Airport lookup requires an explicit scheme",
    );
  if (!SCHEMES.includes(scheme))
    throw new InvalidInputError(
      "Airport scheme must be iata, icao, ident, gps or local",
    );
  if (scheme === "local" && country === null)
    throw new ContextRequiredError("Local airport codes require a country");
  return `${scheme}\0${country ?? ""}\0${code}`;
}
