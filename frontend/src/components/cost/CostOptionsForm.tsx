"use client";

import type { CostOptions } from "@/lib/api";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";

// "auto" lets a bound shop's own region win (else the backend defaults to US).
export const REGIONS = ["auto", "US", "EU", "MX", "CN", "IN", "SA"];

const REGION_LABEL: Record<string, string> = {
  auto: "Auto (shop region, else US)",
};
export const COMPLEXITIES = ["simple", "moderate", "complex", "very_complex"];
export const MATERIAL_CLASSES = [
  "polymer",
  "aluminum",
  "steel",
  "stainless",
  "titanium",
];

export const DEFAULT_COST_OPTIONS: CostOptions = {
  qty: "50,5000",
  region: "auto",
  cavities: 1,
  complexity: "moderate",
  material_class: "polymer",
  shop: null,
  overrides: {},
};

/**
 * Client-side mirror of the backend qty validation so the user never
 * round-trips a 400 for a bad option. Returns an error string or null.
 */
export function validateQty(qty: string): string | null {
  const toks = qty
    .split(",")
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
  if (toks.length === 0) return "Enter at least one quantity (e.g. 50,5000).";
  if (toks.length > 6) return "At most 6 quantities.";
  for (const t of toks) {
    if (!/^\d+$/.test(t)) return `"${t}" is not a whole number.`;
    const n = parseInt(t, 10);
    if (n < 1 || n > 10_000_000)
      return `Quantities must be between 1 and 10,000,000 (got ${t}).`;
  }
  return null;
}

export type SetOpt = <K extends keyof CostOptions>(
  key: K,
  value: CostOptions[K]
) => void;

export function CostOptionsForm({
  opts,
  setOpt,
  qtyError,
  disabled,
}: {
  opts: CostOptions;
  setOpt: SetOpt;
  qtyError: string | null;
  disabled: boolean;
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <Field
        className="col-span-2"
        label="Quantities (comma list, up to 6)"
        htmlFor="cost-qty"
        error={qtyError}
        hint={qtyError ? undefined : "Costed at each quantity; the slider interpolates between them."}
      >
        <Input
          id="cost-qty"
          value={opts.qty}
          disabled={disabled}
          error={!!qtyError}
          onChange={(e) => setOpt("qty", e.target.value)}
          placeholder="50,5000"
          className="num"
        />
      </Field>

      <Field label="Material class">
        <Select
          value={opts.material_class}
          disabled={disabled}
          onValueChange={(v) => setOpt("material_class", v)}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MATERIAL_CLASSES.map((m) => (
              <SelectItem key={m} value={m}>
                {m}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label="Region">
        <Select
          value={opts.region}
          disabled={disabled}
          onValueChange={(v) => setOpt("region", v)}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {REGIONS.map((r) => (
              <SelectItem key={r} value={r}>
                {REGION_LABEL[r] ?? r}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label="Complexity">
        <Select
          value={opts.complexity}
          disabled={disabled}
          onValueChange={(v) => setOpt("complexity", v)}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {COMPLEXITIES.map((c) => (
              <SelectItem key={c} value={c}>
                {c.replace("_", " ")}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label="Cavities (tooling)">
        <Input
          type="number"
          min={1}
          value={opts.cavities}
          disabled={disabled}
          className="num"
          onChange={(e) =>
            setOpt("cavities", Math.max(1, parseInt(e.target.value, 10) || 1))
          }
        />
      </Field>
    </div>
  );
}
