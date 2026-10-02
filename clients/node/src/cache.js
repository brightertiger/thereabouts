// Charge buffers by bytes and decoded objects conservatively by their retained
// graph. Entries sharing strings are charged independently, never discounted.
function weight(value, seen = new Set()) {
  if (value === null || value === undefined) return 8;
  if (typeof value === "string") return 48 + 2 * value.length;
  if (typeof value !== "object") return 16;
  if (seen.has(value)) return 0;
  seen.add(value);
  if (Buffer.isBuffer(value)) return 96 + value.byteLength;
  return (
    64 +
    Object.entries(value).reduce(
      (n, [key, child]) => n + 24 + weight(key, seen) + weight(child, seen),
      0,
    )
  );
}
export class Cache {
  constructor(budget) {
    this.budget = budget;
    this.entries = new Map();
    this.bytes = this.hits = this.misses = this.evictions = 0;
  }
  get(key) {
    const entry = this.entries.get(key);
    if (!entry) {
      this.misses++;
      return undefined;
    }
    this.hits++;
    this.entries.delete(key);
    this.entries.set(key, entry);
    return entry.value;
  }
  put(key, value) {
    if (!this.budget) return value;
    const size = 96 + weight(key) + weight(value);
    if (size > this.budget) return value;
    const previous = this.entries.get(key);
    if (previous) {
      this.bytes -= previous.size;
      this.entries.delete(key);
    }
    while (this.bytes + size > this.budget) {
      const oldest = this.entries.keys().next().value;
      this.bytes -= this.entries.get(oldest).size;
      this.entries.delete(oldest);
      this.evictions++;
    }
    this.entries.set(key, { value, size });
    this.bytes += size;
    return value;
  }
  clear() {
    this.entries.clear();
    this.bytes = 0;
  }
  info() {
    return {
      budget_bytes: this.budget,
      retained_bytes: this.bytes,
      entries: this.entries.size,
      hits: this.hits,
      misses: this.misses,
      evictions: this.evictions,
    };
  }
}
