import { ImageResponse } from "next/og";

export const alt = "ScaleCAD - Can you make it?";
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
          background: "#f4f5f2",
          color: "#0d0f0e",
          fontFamily: "Arial, sans-serif",
          padding: 64,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", width: "100%" }}>
          <div style={{ fontSize: 34, letterSpacing: "-0.02em", fontWeight: 700 }}>ScaleCAD</div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 70, lineHeight: 0.95, letterSpacing: "-0.035em", fontWeight: 300, maxWidth: 1000 }}>
              Can you make it?
            </div>
            <div style={{ marginTop: 30, fontSize: 28, color: "#474d4a", maxWidth: 820 }}>
              Every number shows where it came from.
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 18, color: "#474d4a", fontSize: 22 }}>
            <span>CAD in</span>
            <span style={{ width: 54, height: 1, background: "#ff5b1f" }} />
            <span>decision out</span>
          </div>
        </div>
      </div>
    ),
    size
  );
}
