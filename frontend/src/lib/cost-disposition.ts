export const COST_DISPOSITIONS = [
  { key: "inhouse", label: "Make in-house" },
  { key: "outside", label: "Make outside" },
  { key: "acquire", label: "Acquire capability" },
  { key: "redesign", label: "Redesign" },
] as const;

export type CostDisposition = (typeof COST_DISPOSITIONS)[number]["key"];

export const COST_DISPOSITION_NOTE_MAX_LENGTH = 1000;

export function costDispositionLabel(
  disposition: CostDisposition | null | undefined
): string | null {
  return (
    COST_DISPOSITIONS.find((option) => option.key === disposition)?.label ?? null
  );
}

export function isCostDisposition(value: unknown): value is CostDisposition {
  return COST_DISPOSITIONS.some((option) => option.key === value);
}
