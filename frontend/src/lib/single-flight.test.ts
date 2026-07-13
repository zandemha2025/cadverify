import { test } from "node:test";
import assert from "node:assert/strict";

import {
  releaseSingleFlight,
  tryAcquireSingleFlight,
} from "./single-flight.ts";

test("single-flight lock rejects a same-tick duplicate and can be retried after release", () => {
  const lock = { current: false };

  assert.equal(tryAcquireSingleFlight(lock), true);
  assert.equal(tryAcquireSingleFlight(lock), false);

  releaseSingleFlight(lock);
  assert.equal(tryAcquireSingleFlight(lock), true);
});
