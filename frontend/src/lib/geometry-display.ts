/** Open meshes carry a legacy numeric zero in the API; it is not a measurement. */
export function formatVolumeCm3(
  volume: number | null | undefined,
  watertight: boolean | null | undefined,
  digits = 2,
): string {
  if (watertight !== true || volume == null || !Number.isFinite(volume) || volume <= 0) return "Volume unavailable";
  return Number(volume.toFixed(digits)) === 0
    ? `< ${(10 ** -digits).toFixed(digits)} cm³`
    : `${volume.toFixed(digits)} cm³`;
}
