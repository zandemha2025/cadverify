import localFont from "next/font/local";

const display = localFont({ src: "../../app/fonts/funneldisplay.ttf", variable: "--font-funnel-display", weight: "300 800", display: "swap" });
const sans = localFont({ src: "../../app/fonts/funnelsans.ttf", variable: "--font-funnel-sans", weight: "300 800", display: "swap" });
const mono = localFont({ src: "../../app/fonts/martianmono.ttf", variable: "--font-martian-mono", weight: "100 800", display: "swap" });
export const siteFonts = `${display.variable} ${sans.variable} ${mono.variable}`;
