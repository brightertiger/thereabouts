// WASM calls synchronous sinks. Pipes can be nonblocking (notably on macOS).
import fs from "node:fs";
const retrySignal = new Int32Array(new SharedArrayBuffer(4));
const RETRY_MILLISECONDS = 2;
export function writeAll(fd, value, write = fs.writeSync) {
  const bytes = Buffer.from(value, "utf8");
  let offset = 0;
  while (offset < bytes.length) {
    try {
      const count = write(fd, bytes, offset, bytes.length - offset, null);
      if (!count)
        throw Object.assign(new Error("Output made no progress"), {
          code: "EIO",
        });
      offset += count;
    } catch (error) {
      if (error.code === "EINTR") continue;
      if (error.code === "EAGAIN" || error.code === "EWOULDBLOCK") {
        Atomics.wait(retrySignal, 0, 0, RETRY_MILLISECONDS);
        continue;
      }
      error.exitCode = error.code === "EPIPE" ? 0 : 2;
      throw error;
    }
  }
}
