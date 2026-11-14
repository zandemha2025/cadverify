export function formatDurationMs(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value} ms`
    : "—";
}

export function formatRateLimitReset(
  resetAtSeconds: number,
  nowMs = Date.now(),
): string | null {
  if (!Number.isFinite(resetAtSeconds) || resetAtSeconds <= 0) return null;
  const secondsRemaining = resetAtSeconds - Math.floor(nowMs / 1000);
  if (secondsRemaining <= 0) return "Resets now";
  return `Resets in ${Math.ceil(secondsRemaining / 60)} min`;
}
