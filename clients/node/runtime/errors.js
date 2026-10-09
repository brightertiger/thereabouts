export class ThereaboutsError extends Error {
  constructor(message, code, options) {
    super(message, options);
    this.name = new.target.name;
    this.code = code;
  }
}
export class DataNotInstalledError extends ThereaboutsError {
  constructor(family = "core") {
    super(`thereabouts data install ${family}`, "data_not_installed");
    this.family = family;
    this.exitCode = 3;
  }
}
export class IncompatibleDataError extends ThereaboutsError {
  constructor(message, options) {
    super(message, "incompatible_data", options);
    this.exitCode = 4;
  }
}
export class CorruptPackError extends ThereaboutsError {
  constructor(message, options) {
    super(message, "corrupt_pack", options);
    this.exitCode = 4;
  }
}
export class ResourceLimitError extends ThereaboutsError {
  constructor(message, options) {
    super(message, "resource_limit", options);
    this.exitCode = 6;
  }
}
export class ClosedGeocoderError extends ThereaboutsError {
  constructor() {
    super("Geocoder is closed", "closed_geocoder");
  }
}
export class PackNotFoundError extends ThereaboutsError {
  constructor(message, options) {
    super(message, "pack_not_found", options);
    this.exitCode = 4;
  }
}
export function convert(error) {
  if (error instanceof ThereaboutsError) return error;
  const Type =
    {
      incompatible_data: IncompatibleDataError,
      closed_geocoder: ClosedGeocoderError,
      pack_not_found: PackNotFoundError,
      resource_limit: ResourceLimitError,
    }[error.code] ?? CorruptPackError;
  return new Type(error.message, { cause: error });
}
export function usage(message) {
  return Object.assign(new Error(message), { exitCode: 2 });
}
export function integrity(message) {
  return Object.assign(new CorruptPackError(message), { exitCode: 4 });
}
export function atPack(error, filename, family) {
  const converted = convert(error);
  // Descriptor exhaustion is an environment limit; repair advice would mislead.
  if (converted instanceof ResourceLimitError) return converted;
  converted.message = `Unusable ${family} pack at ${filename}: ${converted.message}\nthereabouts data verify --full\nthereabouts data remove ${family} --yes && thereabouts data install ${family}`;
  return converted;
}
