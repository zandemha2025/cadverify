"use client";

/** mm | in: the person's length unit, remembered on their account. */
import * as React from "react";
import { cx } from "../ui";
import { useUnits } from "./use-units";
import "./units.css";

export function UnitSwitch({ className }: { className?: string }) {
  const { unit, setUnit } = useUnits();
  return (
    <span className={cx("seg", className)} role="group" aria-label="Length unit">
      {(["mm", "in"] as const).map((u) => (
        <button key={u} type="button" className={cx(unit === u && "on")} aria-pressed={unit === u} onClick={() => void setUnit(u)}>
          {u}
        </button>
      ))}
    </span>
  );
}
