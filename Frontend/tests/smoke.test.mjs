import assert from "node:assert/strict";
import { existsSync } from "node:fs";

assert.equal(existsSync(new URL("../app/page.tsx", import.meta.url)), true);
assert.equal(existsSync(new URL("../components/advisor-dashboard.tsx", import.meta.url)), true);
assert.equal(existsSync(new URL("../lib/api.ts", import.meta.url)), true);

