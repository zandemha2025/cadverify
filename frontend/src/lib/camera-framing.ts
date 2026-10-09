/** Fit the normalized part's enclosing sphere in either camera dimension. */
export function perspectiveFramingDistance(
  radius: number,
  aspect: number,
  verticalFovDegrees: number,
  preferredDistance: number,
): number {
  if (!Number.isFinite(radius) || radius <= 0 || !Number.isFinite(aspect) || aspect <= 0 ||
      !Number.isFinite(verticalFovDegrees) || verticalFovDegrees <= 0 || verticalFovDegrees >= 180) {
    return preferredDistance;
  }
  const halfAngle = Math.atan(Math.tan(verticalFovDegrees * Math.PI / 360) * Math.min(1, aspect));
  return Math.max(preferredDistance, radius * 1.08 / Math.sin(halfAngle));
}
