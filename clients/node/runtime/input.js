// User-selected inputs are streams, unlike immutable positioned pack artifacts.
import fs from "node:fs";
const retrySignal = new Int32Array(new SharedArrayBuffer(4));
export function lineReader(fd) {
  let pending = Buffer.alloc(0);
  return () => {
    for (;;) {
      const index = pending.indexOf(10);
      if (index >= 0) {
        const line = pending.subarray(0, index + 1);
        pending = pending.subarray(index + 1);
        return line.toString("utf8");
      }
      const bytes = Buffer.allocUnsafe(65536);
      let count;
      try {
        count = fs.readSync(fd, bytes, 0, bytes.length, null);
      } catch (error) {
        if (error.code === "EINTR") continue;
        if (error.code === "EAGAIN" || error.code === "EWOULDBLOCK") {
          Atomics.wait(retrySignal, 0, 0, 2);
          continue;
        }
        throw error;
      }
      if (!count) {
        const last = pending;
        pending = Buffer.alloc(0);
        return last.toString("utf8");
      }
      pending = Buffer.concat([pending, bytes.subarray(0, count)]);
    }
  };
}
