/**
 * The signed-out frame for v4 (boards X1, X12): a minimal product bar (brand
 * and Back to the site) over the v4 world, outside the /app shell. Loads the v4
 * fonts the same way the (v4) layout does (without preloading, so pages that
 * don't render this frame fetch nothing) and keeps the auth pages out of
 * analytics recordings (data-private, ph-no-capture), as today's frame does.
 */
import Link from "next/link";
import { Instrument_Sans, Sora } from "next/font/google";
import "../v4.css";
import "./moments.css";

const sans = Instrument_Sans({ variable: "--font-v4-sans", subsets: ["latin"], display: "swap", preload: false });
const disp = Sora({ variable: "--font-v4-disp", subsets: ["latin"], weight: ["500", "600"], display: "swap", preload: false });

export function V4AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div data-private data-ui="v4" className={`ob mo-auth ph-no-capture ${sans.variable} ${disp.variable}`}>
      <header className="bar">
        <Link className="brand" href="/">
          <svg width="20" height="20" viewBox="0 0 26 26" fill="none" aria-hidden="true">
            <path d="M13 2.6 22.4 8v10L13 23.4 3.6 18V8L13 2.6Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
            <path d="M3.6 8 13 13.4 22.4 8M13 13.4v10" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
          </svg>
          ScaleCAD
        </Link>
        <Link className="btn ghost sm" href="/">
          Back to the site
        </Link>
      </header>
      {children}
    </div>
  );
}
