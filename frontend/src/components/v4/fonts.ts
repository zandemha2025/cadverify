import localFont from "next/font/local";

// The v4 fonts ship with the app (./fonts, both under the SIL Open Font License,
// see the OFL-*.txt files beside them), so a build never fetches them. With
// next/font/google the frontend image build on CI failed on Sora alone: its
// font-file requests came back in a form Turbopack could not resolve, while the
// same build passed elsewhere. Render builds that image too.
//
// Both files are the Google Fonts releases' variable fonts, subset to Latin and
// Latin Extended; Instrument Sans is pinned at its default width (only its
// weight axis was ever loaded).

/** The v4 screens' text and display faces. */
export const v4Sans = localFont({
  src: "./fonts/InstrumentSans.woff2",
  variable: "--font-v4-sans",
  weight: "400 700",
  display: "swap",
});
export const v4Disp = localFont({
  src: "./fonts/Sora.woff2",
  variable: "--font-v4-disp",
  weight: "100 800",
  display: "swap",
});

/** The same faces for the sign-in screens, which don't preload them. */
export const v4AuthSans = localFont({
  src: "./fonts/InstrumentSans.woff2",
  variable: "--font-v4-sans",
  weight: "400 700",
  display: "swap",
  preload: false,
});
export const v4AuthDisp = localFont({
  src: "./fonts/Sora.woff2",
  variable: "--font-v4-disp",
  weight: "100 800",
  display: "swap",
  preload: false,
});
