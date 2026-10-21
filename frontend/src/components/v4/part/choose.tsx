"use client";

/**
 * "Make it this way": choose the process for this part, or go back to
 * ScaleCAD's pick. The choice is the record's decided outcome (Make in-house on
 * a machine of yours that clears it, else Make outside), saved and audited by
 * PUT /cost-decisions/{id}/disposition; the page then follows it.
 */
import * as React from "react";
import { R } from "../routes";
import { usePart } from "./ctx";
import { putDisposition } from "./api";
import { chooseBody, enginePick, followed, pairAt, recordedChoice, type Choice } from "./choice";
import { isWorkable, methodName, shortId, type Method } from "./model";

export function useChoice() {
  const p = usePart();
  const gov = p.data.decision;
  const choice: Choice | null = recordedChoice(gov);
  const pick = enginePick(p.data.cost, p.q);
  const pair = pairAt(p.data.cost, p.q);
  const follow = followed(p.data.cost, p.q, choice);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const id = p.data.decisionId;

  /** Whether "Make it this way" can be offered for a process at the current quantity. */
  const canChoose = (m: Method): boolean => !!id && !p.costOff && m.members.length === 1 && isWorkable(m) && m.prices.has(p.q);

  const makeThisWay = async (m: Method) => {
    const e = m.prices.get(p.q);
    if (!id || !e || busy) return;
    setBusy(m.code);
    setErr(null);
    try {
      const body = chooseBody(e, !!m.inHouse);
      // Keep the note already on the record; only the way to make it changes.
      const res = await putDisposition(id, { ...body, note: gov?.disposition_note ?? null });
      p.patchData({ decision: p.data.decision ? { ...p.data.decision, ...res } : ({ ...res } as never) });
      p.setSel(m.code);
      p.setCostPick(m.code);
      p.toast({ text: `${methodName(m.code)}${m.inHouse ? ` on your ${m.inHouse}` : " outside"} is the way to make it. Saved to record ${shortId(id)}.`, link: { label: "Open", href: R.record(id) } });
    } catch (x) {
      setErr(x instanceof Error ? x.message : "The choice wasn't saved.");
    } finally {
      setBusy(null);
    }
  };

  const backToPick = async () => {
    if (!id || busy) return;
    setBusy("back");
    setErr(null);
    try {
      const res = await putDisposition(id, { disposition: null });
      p.patchData({ decision: p.data.decision ? { ...p.data.decision, ...res } : ({ ...res } as never) });
      p.setCostPick(null);
      p.setDecidePick(null);
      if (pick) p.setSel(pick.process);
      p.toast({ text: "Back to ScaleCAD’s pick. The record and its numbers stay." });
    } catch (x) {
      setErr(x instanceof Error ? x.message : "The choice wasn't cleared.");
    } finally {
      setBusy(null);
    }
  };

  // A choice made on an earlier check, while this check has none yet.
  const earlier = !choice && !gov?.user_disposition ? p.data.earlierChoice ?? null : null;
  const earlierMethod = earlier ? p.methods.find((m) => m.code === earlier.process) ?? null : null;
  const canKeep = !!earlierMethod && canChoose(earlierMethod) && (earlier!.kind !== "inhouse" || !!earlierMethod.inHouse);
  const keepEarlier = async () => {
    if (earlierMethod && canKeep) await makeThisWay(earlierMethod);
  };

  return { choice, pick, pair, follow, canChoose, makeThisWay, backToPick, busy, err, earlier, earlierMethod, canKeep, keepEarlier };
}
