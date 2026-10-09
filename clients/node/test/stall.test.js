import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { archive } from "../runtime/transport.js";

test("per-read stall interrupts with resume advice; steady bodies outlive the budget", async (t) => {
  for (const stalled of [true, false]) {
    const timers = [];
    const server = http.createServer((_request, response) => {
      response.writeHead(200, { "Content-Length": 8 });
      response.write("x");
      if (!stalled) {
        let sent = 1;
        const timer = setInterval(() => {
          response.write("x");
          if (++sent === 8) {
            clearInterval(timer);
            response.end();
          }
        }, 25);
        timers.push(timer);
      }
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    t.after(() => {
      timers.forEach(clearInterval);
      server.closeAllConnections();
      server.close();
    });
    let bytes = 0;
    const read = async () => {
      for await (const chunk of archive(
        new URL(`http://127.0.0.1:${server.address().port}/`),
        { url: "pack.tar.zst", size: 8 },
        0,
        100,
      ))
        bytes += chunk.length;
    };
    if (stalled) {
      await assert.rejects(read(), {
        exitCode: 2,
        message:
          /Download interrupted; run the same data install again to resume/,
      });
      assert.equal(bytes, 1);
    } else {
      await read();
      assert.equal(bytes, 8);
    }
  }
});
