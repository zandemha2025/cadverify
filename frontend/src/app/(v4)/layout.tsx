import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Instrument_Sans, Sora } from "next/font/google";
import { UI_V4 } from "@/lib/ui-v4-flag";
import { verifySession } from "@/lib/dal";
import { AuthProvider } from "@/components/ui/auth-provider";
import { V4Shell } from "@/components/v4/shell";
import "@/components/v4/v4.css";

const sans = Instrument_Sans({ variable: "--font-v4-sans", subsets: ["latin"], display: "swap" });
const disp = Sora({ variable: "--font-v4-disp", subsets: ["latin"], weight: ["500", "600"], display: "swap" });

export const metadata: Metadata = {
  title: "ScaleCAD",
  robots: { index: false, follow: false },
};

/**
 * Version 4 ("object first") product shell. Behind `NEXT_PUBLIC_UI_V4`, off by
 * default; the current product under /verify and the (app) routes is unchanged.
 * Same session gate as every authed surface.
 */
export default async function V4Layout({ children }: { children: React.ReactNode }) {
  if (!UI_V4) notFound();
  const user = await verifySession();
  return (
    <AuthProvider user={user}>
      <div data-private className={`contents ph-no-capture ${sans.variable} ${disp.variable}`}>
        <V4Shell>{children}</V4Shell>
      </div>
    </AuthProvider>
  );
}
