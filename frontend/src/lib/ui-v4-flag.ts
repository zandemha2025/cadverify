/**
 * Version 4 ("object first") UI gate. OFF by default: the current product stays
 * the default until the new screens pass the control-inventory check on staging.
 * Set `NEXT_PUBLIC_UI_V4=1` (or `true`) to mount the `/app` route group.
 *
 * `NEXT_PUBLIC_*` is inlined at build, so this is a compile-time constant.
 */
export const UI_V4 =
  process.env.NEXT_PUBLIC_UI_V4 === "1" || process.env.NEXT_PUBLIC_UI_V4 === "true";
