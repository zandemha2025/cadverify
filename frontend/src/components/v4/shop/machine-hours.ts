/**
 * A machine's hours available a year (op-13): shifts × hours a shift × days a
 * year, times how many identical machines. Not set, ScaleCAD assumes 2 shifts
 * × 8 h × 240 days and says so (backend machine_load_service.DEFAULT_SCHEDULE).
 * Capacity, never a fit axis: setting it changes no verdict or price.
 *
 * Pure: no React, no fetch, so `node --test` runs it (machine-hours.test.ts).
 */

export interface Schedule {
  shifts: number;
  hours_per_shift: number;
  days_per_year: number;
}

export const DEFAULT_SCHEDULE: Schedule = { shifts: 2, hours_per_shift: 8, days_per_year: 240 };
const LIMITS: Record<keyof Schedule, [number, number]> = { shifts: [1, 4], hours_per_shift: [0.5, 24], days_per_year: [1, 366] };

export interface ScheduleText {
  shifts: string;
  hours: string;
  days: string;
}

export function scheduleFields(s: Schedule | null | undefined): ScheduleText {
  return s ? { shifts: String(s.shifts), hours: String(s.hours_per_shift), days: String(s.days_per_year) } : { shifts: "", hours: "", days: "" };
}

/** Hours a year for `count` machines on `s` (the default when not set). */
export function hoursAYear(count: number | null | undefined, s: Schedule | null | undefined): number {
  const n = count && count > 0 ? count : 1;
  const u = s ?? DEFAULT_SCHEDULE;
  return n * u.shifts * u.hours_per_shift * u.days_per_year;
}

/** "3 machines × 2 shifts × 8 h × 240 days = 11,520 h a year" (", assumed" when not set). */
export function scheduleText(count: number | null | undefined, s: Schedule | null | undefined): string {
  const n = count && count > 0 ? count : 1;
  const u = s ?? DEFAULT_SCHEDULE;
  const text = `${n > 1 ? `${n} machines × ` : ""}${u.shifts} ${u.shifts === 1 ? "shift" : "shifts"} × ${u.hours_per_shift} h × ${u.days_per_year} days = ${Math.round(hoursAYear(n, u)).toLocaleString("en-US")} h a year`;
  return s ? text : `${text}, assumed`;
}

/**
 * Read the three fields. All blank: not set (null, the default assumed). A blank
 * field among typed ones takes its default. Errors name the field.
 */
export function readSchedule(t: ScheduleText): { value: Schedule | null; errors: Partial<Record<"shifts" | "hours" | "days", string>> } {
  if (!t.shifts.trim() && !t.hours.trim() && !t.days.trim()) return { value: null, errors: {} };
  const errors: Partial<Record<"shifts" | "hours" | "days", string>> = {};
  const one = (raw: string, key: keyof Schedule, field: "shifts" | "hours" | "days", whole: boolean): number => {
    if (!raw.trim()) return DEFAULT_SCHEDULE[key];
    const v = Number(raw.trim());
    const [lo, hi] = LIMITS[key];
    if (!Number.isFinite(v) || v < lo || v > hi || (whole && !Number.isInteger(v))) {
      errors[field] = `${whole ? "Whole number" : "A number"} from ${lo} to ${hi}.`;
    }
    return v;
  };
  const value: Schedule = {
    shifts: one(t.shifts, "shifts", "shifts", true),
    hours_per_shift: one(t.hours, "hours_per_shift", "hours", false),
    days_per_year: one(t.days, "days_per_year", "days", true),
  };
  if (!errors.shifts && !errors.hours && value.shifts * value.hours_per_shift > 24) errors.hours = "Shifts × hours a shift is at most 24 hours a day.";
  return Object.keys(errors).length ? { value: null, errors } : { value, errors };
}
