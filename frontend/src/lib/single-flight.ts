export type SingleFlightLock = { current: boolean };

/**
 * Acquire a synchronous UI submission lock before React has time to render a
 * disabled state. This closes the same-tick double-click / double-tap window
 * without changing the visible loading state used by buttons.
 */
export function tryAcquireSingleFlight(lock: SingleFlightLock): boolean {
  if (lock.current) return false;
  lock.current = true;
  return true;
}

export function releaseSingleFlight(lock: SingleFlightLock): void {
  lock.current = false;
}
