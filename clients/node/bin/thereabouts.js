#!/usr/bin/env node
import { run } from "../runtime/cli.js";
process.exitCode = await run(process.argv.slice(2));
