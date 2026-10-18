import type { Metadata } from "next";
import { MagicVerifyClient } from "./magic-verify-client";
import { UI_V4 } from "@/lib/ui-v4-flag";
import { V4MagicVerify } from "@/components/v4/moments/magic";

export const metadata: Metadata = {
  title: "Finish signing in - ScaleCad",
  robots: { index: false, follow: false },
};

export default function MagicVerifyPage() {
  if (UI_V4) return <V4MagicVerify />;
  return <MagicVerifyClient />;
}
