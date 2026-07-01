import type { Metadata } from "next";
import { Geist, Geist_Mono, Archivo } from "next/font/google";
import { Toaster } from "sonner";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Display voice: Archivo, loaded WITH the width axis (`wdth`) so the headlines
// and the monumental hero number can use the Expanded width — the signature
// "bold industrial confidence" cut, not a quiet neutral UI sans.
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
      className={`${geistSans.variable} ${geistMono.variable} ${archivo.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        {/* No-flash theme: apply the persisted theme before paint. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "try{var t=localStorage.getItem('cv_theme');if(t==='dark'||(!t&&window.matchMedia('(prefers-color-scheme: dark)').matches)){document.documentElement.classList.add('dark')}}catch(e){}",
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
