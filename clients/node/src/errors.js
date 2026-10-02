export class ThereaboutsError extends Error {
  constructor(message, options) {
    super(message, options);
    this.name = new.target.name;
  }
}
export class InvalidInputError extends ThereaboutsError {}
export class ContextRequiredError extends InvalidInputError {}
export class CorruptPackError extends ThereaboutsError {}
export class UnsupportedPackError extends ThereaboutsError {}
export class IncompatibleDataError extends ThereaboutsError {}
export class ClosedReaderError extends ThereaboutsError {}
export class AmbiguousResultError extends ThereaboutsError {}

export function check(condition, message) {
  if (!condition) throw new CorruptPackError(message);
}
export function integer(value, minimum = 0) {
  check(Number.isSafeInteger(value) && value >= minimum, "Invalid integer");
  return value;
}
export function string(value) {
  check(
    typeof value === "string" && value.length > 0 && value.isWellFormed(),
    "Invalid string",
  );
  return value;
}
export function fields(value, names) {
  check(
    value !== null && typeof value === "object" && !Array.isArray(value),
    "Expected object",
  );
  check(
    JSON.stringify(Object.keys(value).sort()) ===
      JSON.stringify([...names].sort()),
    "Unexpected fields",
  );
}
export class DataNotInstalledError extends ThereaboutsError {}
