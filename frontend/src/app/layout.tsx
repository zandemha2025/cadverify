import type { Metadata } from "next";
import { Geist, Geist_Mono, Archivo } from "next/font/google";
import { Toaster } from "sonner";
import { STAGE_UI } from "@/lib/stage-flag";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// MARKETING-ONLY. Archivo was the authed app's display voice pre-"Governed
// Catalog" re-founding; that identity retired it in favor of Geist Mono for
// the one hero metric (see globals.css --font-display comment). It's loaded
// here — WITH the width axis (`wdth`) for the Expanded cut — only as the
// `--font-display` fallback the (deferred) marketing surfaces still consume;
// the authed app never sets it. Keep the import until the marketing
// re-founding decision lands; do not read this as the app's current voice.
const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
  axes: ["wdth"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "CadVerify — Know what the part should cost. And why.",
  description:
    "Glass-box, per-shop-calibrated should-cost for real CAD parts. Every cost driver measured, sourced, and editable — the decision, not a fake-exact price.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      // Stage-UI gate: when NEXT_PUBLIC_STAGE_UI is on, `[data-stage]` swaps the
      // semantic tokens onto the D5 stage register (see globals.css). Off = the
      // attribute is omitted entirely → today's graphite UI, byte-identical.
      data-stage={STAGE_UI ? "" : undefined}
      className={`${geistSans.variable} ${geistMono.variable} ${archivo.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        {/* No-flash theme: DARK-FIRST. The authed app defaults to dark graphite
            (the command register); only a user who has pinned light opts out.
            Applied before paint so the theme never flickers. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{if(localStorage.getItem('cv_theme')!=='light'){document.documentElement.classList.add('dark')}}catch(e){document.documentElement.classList.add('dark')}",
          }}
        />
      </head>
      <body className="min-h-full flex flex-col">
        {children}
        <Toaster position="top-right" richColors closeButton />
      </body>
    </html>
  );
}
