import assert from "node:assert/strict";
import test from "node:test";
import { cleanAnalyticsEvent, routeLabel, publicReplayAllowed } from "./analytics-privacy.ts";

test("analytics excludes credentials, CAD identifiers, URL queries and free text", () => {
  const event = cleanAnalyticsEvent({ event: "$pageview", properties: {
    $current_url: "https://scalecad.ai/reset-password#token=secret",
    $referrer: "https://example.com/search?q=private", password: "Private1",
    filename: "secret-part.step", $pathname: "/analyses/private-id",
    $browser: "Chrome", $set: { email: "private@example.com" },
  }});
  assert.equal(event?.properties.$current_url, "https://scalecad.ai/reset-password");
  assert.equal(event?.properties.$referrer, "https://example.com/");
  assert.equal(event?.properties.$pathname, "/analyses/:id");
  assert.equal(JSON.stringify(event).includes("secret"), false);
  assert.equal(JSON.stringify(event).includes("private"), false);
  assert.equal(event?.properties.$browser, "Chrome");
});

test("replays are restricted to public pages without query strings or fragments", () => {
  assert.equal(publicReplayAllowed("/pricing", "", ""), true);
  for (const path of ["/login", "/signup", "/forgot-password", "/reset-password", "/verify", "/s/token"]) {
    assert.equal(publicReplayAllowed(path, "", ""), false);
  }
  assert.equal(publicReplayAllowed("/", "?token=secret", ""), false);
  assert.equal(routeLabel("/api/proxy/analyses/customer-part-id/pdf"), "/api/proxy/analyses/:id/:id");
});

test("error telemetry redacts messages and private stack filenames", () => {
  const result = cleanAnalyticsEvent({ event: "$exception", properties: {
    $exception_list: [{ type: "TypeError", value: "private customer-part.step Password1", stacktrace: { frames: [{ filename: "https://scalecad.ai/customer-part.step?token=secret", lineno: 12, colno: 3, function: "privateName" }] } }],
  }});
  assert(!JSON.stringify(result).match(/private|customer-part|Password1|secret/));
  assert(JSON.stringify(result).includes("TypeError"));
});

test("SDK heatmap coordinates survive only for public pages", () => {
  const coordinates = { "https://scalecad.ai/pricing": [{ x: 10, y: 20, type: "click" }] };
  const event = (url: string) => cleanAnalyticsEvent({ event: "$pageleave", properties: { $current_url: url, $heatmap_data: coordinates } });
  assert.deepEqual(event("https://scalecad.ai/pricing")?.properties.$heatmap_data, coordinates);
  assert.equal(event("https://scalecad.ai/verify")?.properties.$heatmap_data, undefined);
});


test("page duration and scroll depth survive without private route identifiers", () => {
  const event = cleanAnalyticsEvent({ event: "$pageleave", properties: {
    $prev_pageview_duration: 12.5, $prev_pageview_max_content_percentage: 0.8,
    $prev_pageview_pathname: "/analyses/customer-id", $prev_pageview_title: "private-part.step",
  }});
  assert.equal(event?.properties.$prev_pageview_duration, 12.5);
  assert.equal(event?.properties.$prev_pageview_max_content_percentage, 0.8);
  assert.equal(event?.properties.$prev_pageview_pathname, "/analyses/:id");
  assert(!JSON.stringify(event).match(/customer-id|private-part/));
});
