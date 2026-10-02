import { createHash } from "node:crypto";
import { CorruptPackError, check } from "./errors.js";

const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
export function utf8(bytes) {
  try {
    return decoder.decode(bytes);
  } catch (error) {
    throw new CorruptPackError("Invalid UTF-8", { cause: error });
  }
}
export function compare(a, b) {
  return Buffer.compare(Buffer.from(a), Buffer.from(b));
}
export function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}
export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value)
      .sort(compare)
      .map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}
export function freeze(value) {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}

// JSON.parse alone silently accepts duplicate keys. This parser also rejects
// unsafe integer identities and malformed Unicode before data enters the reader.
export function parse(bytes) {
  const text = utf8(bytes);
  let position = 0;
  function space() {
    while (/[\x20\t\r\n]/.test(text[position] ?? "\0")) position++;
  }
  function quoted() {
    const start = position++;
    while (position < text.length) {
      const char = text[position++];
      if (char === "\\") position++;
      else if (char === '"') {
        const value = JSON.parse(text.slice(start, position));
        check(value.isWellFormed(), "Invalid Unicode");
        return value;
      }
    }
    throw new CorruptPackError("Unterminated string");
  }
  function value() {
    space();
    if (text[position] === '"') return quoted();
    const start = text[position];
    if (start === "{" || start === "[") {
      position++;
      const object = start === "{";
      const end = object ? "}" : "]";
      const result = object ? {} : [];
      const seen = new Set();
      space();
      if (text[position] === end) {
        position++;
        return result;
      }
      while (true) {
        space();
        if (object) {
          check(text[position] === '"', "Expected JSON key");
          const key = quoted();
          check(!seen.has(key), "Duplicate JSON key");
          seen.add(key);
          space();
          check(text[position++] === ":", "Expected colon");
          Object.defineProperty(result, key, {
            value: value(),
            enumerable: true,
            writable: true,
          });
        } else result.push(value());
        space();
        const separator = text[position++];
        if (separator === end) return result;
        check(separator === ",", "Expected JSON separator");
      }
    }
    const token =
      /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(
        text.slice(position),
      );
    check(token !== null, "Invalid JSON value");
    position += token[0].length;
    const result = JSON.parse(token[0]);
    if (typeof result === "number") {
      check(Number.isFinite(result), "Nonfinite JSON number");
      check(
        !Number.isInteger(result) || Number.isSafeInteger(result),
        "Unsafe JSON integer",
      );
    }
    return result;
  }
  try {
    const result = value();
    space();
    check(position === text.length, "Trailing JSON bytes");
    return result;
  } catch (error) {
    if (error instanceof CorruptPackError) throw error;
    if (error instanceof SyntaxError || error instanceof RangeError) {
      throw new CorruptPackError("Invalid JSON", { cause: error });
    }
    throw error;
  }
}
