"use client";

import { ArrowRight, Boxes, Sparkles, Upload, Wrench } from "lucide-react";
import type { ReactNode } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { C, MONO } from "@/lib/verify/tokens";

export const WELCOME_STORAGE_KEY = "proofshape_welcome_v2";

export function WelcomeGuide({
  open,
  onOpenChange,
  onSample,
  onUpload,
  onDesign,
  onMachines,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSample: () => void;
  onUpload: () => void;
  onDesign: () => void;
  onMachines: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        aria-describedby="proofshape-welcome-description"
        className="max-h-[min(92vh,820px)] max-w-[760px] gap-0 overflow-y-auto p-0"
        style={{
          borderColor: C.hair,
          borderRadius: 22,
          background: C.panel,
          color: C.ink,
          boxShadow: "0 34px 100px rgba(23,24,26,0.22)",
        }}
      >
        <div style={{ padding: "30px 30px 26px" }}>
          <p
            style={{
              margin: 0,
              fontFamily: MONO,
              fontSize: 10,
              fontWeight: 650,
              letterSpacing: "0.14em",
              color: C.measured,
            }}
          >
            START HERE · ABOUT 60 SECONDS
          </p>
          <DialogTitle
            style={{
              marginTop: 10,
              fontSize: 30,
              fontWeight: 450,
              lineHeight: 1.12,
              letterSpacing: "-0.025em",
              color: C.ink,
            }}
          >
            What do you want ProofShape to help you do?
          </DialogTitle>
          <DialogDescription
            id="proofshape-welcome-description"
            style={{
              marginTop: 10,
              maxWidth: 650,
              color: C.ink55,
              fontSize: 14,
              lineHeight: 1.65,
            }}
          >
            ProofShape turns CAD into a manufacturing answer: whether a part can be
            made, how to make it, what it should cost, and what needs attention.
            Choose one starting point. You can use every tool later.
          </DialogDescription>

          <button
            type="button"
            data-testid="welcome-guided-example"
            onClick={onSample}
            style={{
              width: "100%",
              marginTop: 24,
              display: "flex",
              alignItems: "center",
              gap: 16,
              border: 0,
              borderRadius: 16,
              background: C.ink,
              color: "#fff",
              padding: "18px 20px",
              textAlign: "left",
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            <span
              aria-hidden
              style={{
                width: 42,
                height: 42,
                flexShrink: 0,
                display: "grid",
                placeItems: "center",
                borderRadius: 12,
                background: "rgba(255,255,255,0.12)",
              }}
            >
              <Sparkles size={19} />
            </span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span
                style={{
                  display: "block",
                  fontFamily: MONO,
                  fontSize: 9.5,
                  letterSpacing: "0.12em",
                  color: "rgba(255,255,255,0.7)",
                }}
              >
                RECOMMENDED · NO FILE NEEDED
              </span>
              <span style={{ display: "block", marginTop: 5, fontSize: 16, fontWeight: 650 }}>
                Show me a real example
              </span>
              <span
                style={{
                  display: "block",
                  marginTop: 4,
                  color: "rgba(255,255,255,0.72)",
                  fontSize: 12.5,
                  lineHeight: 1.5,
                }}
              >
                Analyze a sample part, then explain the result and what to do next.
              </span>
            </span>
            <ArrowRight aria-hidden size={19} style={{ flexShrink: 0 }} />
          </button>

          <div className="grid gap-3 sm:grid-cols-2" style={{ marginTop: 12 }}>
            <Choice
              icon={<Upload size={18} />}
              title="Check my CAD file"
              body="Upload STEP, STL, or IGES and get a DFM, process, and cost answer."
              onClick={onUpload}
            />
            <Choice
              icon={<Boxes size={18} />}
              title="Create a simple part"
              body="Build a plate, bracket, or enclosure, then verify the generated STEP."
              onClick={onDesign}
            />
          </div>

          <div
            style={{
              marginTop: 18,
              display: "flex",
              alignItems: "center",
              gap: 12,
              flexWrap: "wrap",
              borderTop: `1px solid ${C.hair2}`,
              paddingTop: 18,
            }}
          >
            <Wrench aria-hidden size={17} color={C.shop} />
            <p style={{ margin: 0, flex: 1, minWidth: 220, color: C.ink55, fontSize: 12.5, lineHeight: 1.55 }}>
              Want estimates based on your own factory? Add machines and hourly rates
              after you see the first result.
            </p>
            <button
              type="button"
              onClick={onMachines}
              style={{
                border: `1px solid ${C.hair}`,
                borderRadius: 999,
                background: C.panel,
                color: C.ink,
                padding: "8px 13px",
                fontFamily: "inherit",
                fontSize: 11.5,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Set up my shop
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Choice({
  icon,
  title,
  body,
  onClick,
}: {
  icon: ReactNode;
  title: string;
  body: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        minHeight: 118,
        display: "flex",
        alignItems: "flex-start",
        gap: 12,
        border: `1px solid ${C.hair}`,
        borderRadius: 14,
        background: C.sunken,
        color: C.ink,
        padding: "16px",
        textAlign: "left",
        cursor: "pointer",
        fontFamily: "inherit",
      }}
    >
      <span
        aria-hidden
        style={{
          width: 34,
          height: 34,
          flexShrink: 0,
          display: "grid",
          placeItems: "center",
          borderRadius: 10,
          border: `1px solid ${C.hair}`,
          background: C.panel,
          color: C.measured,
        }}
      >
        {icon}
      </span>
      <span>
        <span style={{ display: "block", fontSize: 14, fontWeight: 650 }}>{title}</span>
        <span style={{ display: "block", marginTop: 5, color: C.ink55, fontSize: 12, lineHeight: 1.55 }}>
          {body}
        </span>
      </span>
    </button>
  );
}
