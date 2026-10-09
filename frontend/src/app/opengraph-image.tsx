import { ImageResponse } from "next/og";

export const alt = "ScaleCad - Know what you can make";
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
          background: "#ddebaf",
          color: "#183d32",
          fontFamily: "Arial, sans-serif",
          padding: 64,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", width: "100%" }}>
          <div style={{ fontSize: 34, letterSpacing: "-0.02em", fontWeight: 700 }}>ScaleCad</div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 88, lineHeight: 0.95, letterSpacing: "-0.035em", fontWeight: 300, maxWidth: 780 }}>
              Know what you can make.
            </div>
            <div style={{ marginTop: 30, fontSize: 28, color: "#53635a", maxWidth: 820 }}>
              Your part. Your next decision. The evidence to move forward.
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 18, color: "#53635a", fontSize: 22 }}>
            <span>CAD in</span>
            <span style={{ width: 54, height: 1, background: "#839874" }} />
            <span>decision out</span>
          </div>
        </div>
      </div>
    ),
    size
  );
}
