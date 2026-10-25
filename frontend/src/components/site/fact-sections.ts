/**
 * The trust facts (components/v4/trust/facts) as document-page sections, so the
 * public Security, Privacy and Data processing pages say exactly what the
 * in-app Files and data page says.
 */
import { SERVICES, type FactSection } from "@/components/v4/trust/facts";

export type DocSection = { id: string; title: string; body: string; bullets?: string[]; href?: string; link?: string };

const stop = (s: string) => (/[.?]$/.test(s) ? s : `${s}.`);

export function factSection(s: FactSection, over: Partial<DocSection> = {}): DocSection {
  return {
    id: s.id,
    title: s.title,
    body: s.short ?? "",
    bullets: s.rows.map((r) => `${r.k}: ${r.v}`),
    ...(s.link ? { href: s.link.href.startsWith("/app/") ? undefined : s.link.href, link: s.link.href.startsWith("/app/") ? undefined : s.link.label } : {}),
    ...over,
  };
}

export function servicesSection(over: Partial<DocSection> = {}): DocSection {
  return {
    id: "services",
    title: "Services that receive data",
    body: "Every outside service ScaleCAD’s code sends data to, what it gets and when. Nothing else receives your data.",
    bullets: SERVICES.map((x) => `${x.name}: ${stop(x.gets)} ${stop(x.when)}`),
    ...over,
  };
}
