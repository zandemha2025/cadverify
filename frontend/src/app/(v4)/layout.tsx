import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { v4Sans, v4Disp } from "@/components/v4/fonts";
import { UI_V4 } from "@/lib/ui-v4-flag";
import { verifySession } from "@/lib/dal";
import { AuthProvider } from "@/components/ui/auth-provider";
import { V4Shell } from "@/components/v4/shell";
import "@/components/v4/v4.css";

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
      <div data-private className={`contents ph-no-capture ${v4Sans.variable} ${v4Disp.variable}`}>
        <V4Shell>{children}</V4Shell>
      </div>
    </AuthProvider>
  );
}
