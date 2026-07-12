import type { Metadata } from "next";
import { MagicVerifyClient } from "./magic-verify-client";

export const metadata: Metadata = {
  title: "Finish signing in - CadVerify",
  robots: { index: false, follow: false },
};

export default function MagicVerifyPage() {
  return <MagicVerifyClient />;
}
