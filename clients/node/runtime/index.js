export { Geocoder } from "./geocoder.js";
export {
  ThereaboutsError,
  DataNotInstalledError,
  IncompatibleDataError,
  CorruptPackError,
  ClosedGeocoderError,
  PackNotFoundError,
  ResourceLimitError,
  InvalidInputError,
  InternalError,
} from "./errors.js";
import { Geocoder } from "./geocoder.js";
let defaultGeocoder;
export async function reverse(options) {
  defaultGeocoder ??= Geocoder.open().catch((error) => {
    defaultGeocoder = undefined;
    throw error;
  });
  return (await defaultGeocoder).reverse(options);
}
