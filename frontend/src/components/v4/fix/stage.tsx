"use client";

/** What K1 and K4 add to the stage: the key to what's lit, the places, the phone pill. */
import * as React from "react";
import { cx } from "../ui";
import { KIND_COLOR } from "../part/model";
import { useFix } from "./ctx";
import { callout, findProblem, n0, pickMethod } from "./problems";
import { placesOf } from "./rank";

/** The words under the part when the pin is out of view (replaces "Drag to turn it"). */
export function fixHint(pin: string, kind: "problem" | "all", n: string): string | null {
  if (pin === "hidden") return kind === "all" ? `Turn the part to see pin ${n}` : "Turn to it to see where";
  if (pin === "inside") return "Inside the part: X-ray shows it";
  return null;
}

export function FixStage({ has3d }: { has3d: boolean }) {
  const fx = useFix();
  const v = fx.view;
  if (!v) return null;
  if (v.kind === "problem") {
    const P = fx.problem;
    if (!P) return null;
    const co = callout(P, fx.method);
    const lit = fx.lit && P.faces.length > 0;
    const shownN = fx.litCount ?? P.faces.length;
    const color = P.kind ? KIND_COLOR[P.kind] : "#D92D20";
    const key =
      P.id === "open"
        ? `Red: the mesh’s open edges${/\d/.test(P.where) ? ` · the check counted ${P.where.replace(/ open edges$/, "")}` : ""}`
        : lit
          ? `Lit: ${P.faceCount != null ? `${n0(P.faceCount)} ${P.faceCount === 1 ? "face" : "faces"}` : "the faces"} the check flagged${P.faceCount != null && P.faceCount > shownN && shownN > 0 ? `, ${n0(shownN)} shown` : ""}`
          : P.faces.length && has3d
            ? "Not lit: this 3D view isn’t the mesh the check measured"
            : P.region
              ? "Pinned where the check found it"
              : "The whole part: not one place on it";
    return (
      <>
        {has3d ? (
          <span className={cx("kpill", fx.pin !== "visible" && "off")} aria-live="polite">
            <b>{co.main}</b>
            <small>{co.sub}</small>
          </span>
        ) : null}
        <div className="klegend" aria-label="Key">
          <span className="li">
            {P.id === "open" ? <i className="ln2" /> : lit ? <i className="sw2" style={{ color }} /> : null}
            {key}
          </span>
          {has3d ? <span className="li turnhelp">Drag the part, or use the arrow keys, to turn it</span> : null}
        </div>
      </>
    );
  }
  const places = placesOf(fx.ranked);
  const sel = findProblem(fx.set, v.sel) ?? fx.ranked[0]?.problem ?? null;
  const selPlace = places.find((pl) => sel && pl.ids.includes(sel.id)) ?? null;
  const co = sel ? callout(sel, pickMethod(sel, null, null)) : null;
  const note = !selPlace ? null : !selPlace.located ? "Whole part: not one place on it" : fixHint(fx.pin, "all", selPlace.n);
  return (
    <>
      {note ? <span className="kstnote">{note}</span> : null}
      {has3d && co && selPlace?.located ? (
        <span className={cx("kpill", fx.pin !== "visible" && "off")} aria-live="polite">
          <b>{co.main}</b>
          <small>{co.sub}</small>
        </span>
      ) : null}
      <div className="klocs" role="group" aria-label="Where the problems are">
        {places.map((pl) => (
          <button key={pl.name} type="button" className={cx(selPlace?.name === pl.name && "on")} aria-pressed={selPlace?.name === pl.name} onClick={() => fx.setAll({ sel: pl.ids[0] })}>
            <i>{pl.n}</i>
            {pl.name} · {pl.ids.length}
          </button>
        ))}
      </div>
    </>
  );
}
