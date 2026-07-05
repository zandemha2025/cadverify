import { ImageResponse } from "next/og";

export const alt = "CadVerify - verification, made of glass";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          background: "#050506",
          color: "#f7f7f2",
          fontFamily: "Arial, sans-serif",
          padding: 64,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", width: "100%" }}>
          <div style={{ fontSize: 34, letterSpacing: "-0.02em", fontWeight: 700 }}>CadVerify</div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 88, lineHeight: 0.95, letterSpacing: "-0.07em", fontWeight: 300, maxWidth: 780 }}>
              Verification, made of glass.
            </div>
            <div style={{ marginTop: 30, fontSize: 28, color: "rgba(247,247,242,0.68)", maxWidth: 820 }}>
              Makeability, cost, provenance, and validation in one auditable record.
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 18, color: "rgba(247,247,242,0.56)", fontSize: 22 }}>
            <span>CAD in</span>
            <span style={{ width: 54, height: 1, background: "rgba(247,247,242,0.36)" }} />
            <span>decision out</span>
          </div>
        </div>
      </div>
    ),
    size
  );
}
