import { test } from "node:test";
import assert from "node:assert/strict";
import { publicSharePath } from "./public-share-paths.ts";

const ID = "Ab3dEf6hIj9K";

test("the public share proxy reaches a link's page, its CAD and a package's ZIP, nothing else", () => {
  for (const ok of [["s", ID], ["s", "cost", ID], ["s", "cost", ID, "cad"], ["s", "pkg", ID], ["s", "pkg", ID, "download.zip"], ["s", "pkg", ID, "cad", "2"]])
    assert.equal(publicSharePath(ok), true, ok.join("/"));
  for (const bad of [["s", "short"], ["s", "cost", ID, "estimates"], ["s", "pkg", ID, "cad", "0"], ["s", "pkg", ID, "cad", "../x"], ["api", ID], ["s", "pkg", ID, "download.zip", "x"], ["s", "cost", "../../x"]])
    assert.equal(publicSharePath(bad), false, bad.join("/"));
});
