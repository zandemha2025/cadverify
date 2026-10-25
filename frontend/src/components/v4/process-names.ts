/**
 * One name per engine process, used by every v4 screen, so a process reads the
 * same on the part page, in records, in the shop and in batch runs. Plain words
 * first, with the acronym engineers search for ("Filament printing (FDM/FFF)").
 * Pure: no imports, so the derivations that use it run under `node --test`.
 * An unknown code reads as its words, never as an invented name.
 */

/** Plain name, without the acronym: "Filament printing", "Turning". */
export const PROCESS_NAME: Record<string, string> = {
  fdm: "Filament printing",
  sla: "Resin printing",
  dlp: "Resin printing",
  sls: "Nylon powder printing",
  mjf: "Nylon powder printing",
  dmls: "Metal powder printing",
  slm: "Metal powder printing",
  ebm: "Electron-beam printing",
  binder_jetting: "Metal binder jetting",
  ded: "Metal deposition",
  waam: "Wire-arc printing",
  cnc_3axis: "3-axis milling",
  cnc_5axis: "5-axis milling",
  cnc_turning: "Turning",
  wire_edm: "Wire EDM",
  sheet_metal: "Sheet metal",
  injection_molding: "Injection molding",
  investment_casting: "Investment casting",
  die_casting: "Die casting",
  sand_casting: "Sand casting",
  forging: "Forging",
};

/** The acronym engineers search for, where a process has one. */
export const PROCESS_ACRONYM: Record<string, string> = {
  fdm: "FDM/FFF",
  sla: "SLA",
  dlp: "DLP",
  sls: "SLS",
  mjf: "MJF",
  dmls: "DMLS",
  slm: "SLM",
  ebm: "EBM",
  ded: "DED",
  waam: "WAAM",
};

function readable(code: string): string {
  const words = code.replace(/[_-]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : code;
}

/** "fdm" → "Filament printing"; an unknown code reads as its words. */
export function processName(code: string | null | undefined): string {
  if (!code) return "";
  return PROCESS_NAME[code] ?? readable(code);
}

/** What makes it, for "you'd need a …" lines: "Lathe", "Filament printer". */
export const MACHINE_KIND: Record<string, string> = {
  cnc_3axis: "3-axis mill",
  cnc_5axis: "5-axis mill",
  cnc_turning: "Lathe",
  wire_edm: "Wire EDM",
  mjf: "Nylon powder printer",
  sls: "Nylon powder printer",
  fdm: "Filament printer",
  sla: "Resin printer",
  dlp: "Resin printer",
  dmls: "Metal powder printer",
  slm: "Metal powder printer",
  ebm: "Electron-beam printer",
  binder_jetting: "Binder-jet printer",
  ded: "Metal deposition cell",
  waam: "Wire-arc cell",
  injection_molding: "Injection molder",
  sheet_metal: "Press brake",
  die_casting: "Die-casting cell",
};

/** "cnc_turning" → "Lathe"; a process without a machine name reads as the process. */
export function machineKind(code: string | null | undefined): string {
  if (!code) return "";
  return MACHINE_KIND[code] ?? processLabel(code);
}

/** "fdm" → "Filament printing (FDM/FFF)", "cnc_3axis" → "3-axis milling": unique per process. */
export function processLabel(code: string | null | undefined): string {
  if (!code) return "";
  const a = PROCESS_ACRONYM[code];
  return a ? `${processName(code)} (${a})` : processName(code);
}
