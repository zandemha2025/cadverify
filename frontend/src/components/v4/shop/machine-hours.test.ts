import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_SCHEDULE, hoursAYear, readSchedule, scheduleFields, scheduleText } from "./machine-hours.ts";

test("hours a year: shifts × hours × days × machines, the default said as assumed (op-13)", () => {
  assert.equal(hoursAYear(3, null), 11520);
  assert.equal(scheduleText(3, null), "3 machines × 2 shifts × 8 h × 240 days = 11,520 h a year, assumed");
  assert.equal(scheduleText(1, { shifts: 1, hours_per_shift: 10, days_per_year: 250 }), "1 shift × 10 h × 250 days = 2,500 h a year");
  assert.deepEqual(scheduleFields(null), { shifts: "", hours: "", days: "" });
});

test("the three fields read whole, blank ones take the default, errors name the field", () => {
  assert.deepEqual(readSchedule({ shifts: "", hours: "", days: "" }), { value: null, errors: {} });
  assert.deepEqual(readSchedule({ shifts: "3", hours: "", days: "" }).value, { ...DEFAULT_SCHEDULE, shifts: 3 });
  assert.deepEqual(readSchedule({ shifts: "2", hours: "7.5", days: "250" }).value, { shifts: 2, hours_per_shift: 7.5, days_per_year: 250 });
  assert.match(readSchedule({ shifts: "1.5", hours: "", days: "" }).errors.shifts ?? "", /Whole number from 1 to 4/);
  assert.match(readSchedule({ shifts: "3", hours: "10", days: "" }).errors.hours ?? "", /at most 24 hours a day/);
  assert.match(readSchedule({ shifts: "", hours: "", days: "400" }).errors.days ?? "", /from 1 to 366/);
});
