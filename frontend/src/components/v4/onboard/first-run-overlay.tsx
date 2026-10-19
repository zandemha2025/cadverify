"use client";

/**
 * The first run on the part page (N2–N4, N6's tip, N7 on a phone): mounted in
 * the part page's overlay, inside the part's context. It shows
 *
 * - the three tips on a person's first result, once (N2), then, if the shop has
 *   no machines, the "Your shop" card (Add your machines / Not now);
 * - "Make it about your shop" (N3), from that card, from Home (`?shop=add`) or
 *   the chip after "Not now";
 * - the re-check on your machines and its before/now answer (N4).
 *
 * `?tips=1` shows the tips again (search: "Show the tips again").
 */
import * as React from "react";
import { useAuth } from "@/components/ui/auth-provider";
import { usePart } from "../part/ctx";
import { useFix } from "../fix/ctx";
import * as homeApi from "../home/data";
import { shopCardDue, tipsDue, type TipStep, type TipsState } from "./first-run";
import { Tips } from "./tips";
import { ShopSheet } from "./shop-sheet";
import { Aha } from "./aha";
import { closeShopSheet, openShopSheet, readTips, useRecheck, useShopSheet, writeTips } from "./state";
import "./onboard.css";

function useParam(name: string): string | null {
  const [v, setV] = React.useState<string | null>(null);
  React.useEffect(() => {
    setV(new URLSearchParams(window.location.search).get(name));
  }, [name]);
  return v;
}

function dropParam(name: string) {
  try {
    const u = new URL(window.location.href);
    if (!u.searchParams.has(name)) return;
    u.searchParams.delete(name);
    window.history.replaceState(window.history.state, "", `${u.pathname}${u.search}`);
  } catch {
    /* the address keeps it; nothing else changes */
  }
}

/** Is a dialog open over the page (out of checks, sample result, asking to fix…)? */
function useModalOpen(): boolean {
  const [open, setOpen] = React.useState(false);
  React.useEffect(() => {
    const t = window.setInterval(() => setOpen(!!document.querySelector(".ob [aria-modal='true']:not(.nb-ss)")), 400);
    return () => window.clearInterval(t);
  }, []);
  return open;
}

export function FirstRun() {
  const p = usePart();
  const fx = useFix();
  const { user } = useAuth();
  const uid = user?.id ?? null;
  const key = p.data.key;
  const rc = useRecheck(key);
  const sheetOpen = useShopSheet(key);
  const modal = useModalOpen();
  const shopParam = useParam("shop");
  const tipsParam = useParam("tips");
  const [tips, setTips] = React.useState<TipsState | null>(null);
  const [step, setStep] = React.useState<TipStep>("tip1");
  const [skipped, setSkipped] = React.useState(false);
  const [team, setTeam] = React.useState<string[] | null>(null);
  const now = React.useRef(Date.now()).current;

  // The person's tips state, once known; ?tips=1 starts them over.
  React.useEffect(() => {
    if (uid == null) return;
    if (tipsParam === "1") {
      const fresh: TipsState = { done: false, shownAt: null, shop: "open" };
      writeTips(uid, fresh);
      setTips(fresh);
      dropParam("tips");
      return;
    }
    setTips(readTips(uid));
  }, [uid, tipsParam]);

  // ?shop=add opens "Make it about your shop" over this part (Home's "Add your machines").
  React.useEffect(() => {
    if (shopParam === "add" && key) {
      openShopSheet(key);
      dropParam("shop");
    }
  }, [shopParam, key]);

  // A teammate's machines (N6): the org has machines and more than one member.
  const nMachines = p.data.machines.length;
  React.useEffect(() => {
    if (!nMachines) return;
    let live = true;
    homeApi
      .members()
      .then((m) => live && setTeam(m.filter((x) => x.is_active).length > 1 ? p.data.machines.map((x) => x.name ?? x.process) : null))
      .catch(() => live && setTeam(null));
    return () => {
      live = false;
    };
  }, [nMachines, p.data.machines]);

  const save = React.useCallback(
    (s: TipsState) => {
      setTips(s);
      writeTips(uid, s);
    },
    [uid],
  );

  const result = !p.checking && !!p.data.cost && !p.costOff && !p.interrupted;
  const quiet = !result || !!p.session?.sample || !!p.session?.panel || modal || !!fx.view || !!rc || sheetOpen;
  const showTips = !!tips && tipsDue(tips, now) && !quiet;

  // First shown: remember when, so a later visit doesn't show them again.
  React.useEffect(() => {
    if (showTips && tips && tips.shownAt == null) {
      save({ ...tips, shownAt: Date.now() });
      setStep(p.has3d ? "tip1" : "tip2");
    }
  }, [showTips, tips, save, p.has3d]);

  const finish = React.useCallback(() => {
    if (!tips) return;
    save({ ...tips, done: true, shownAt: tips.shownAt ?? Date.now(), shop: nMachines ? "done" : tips.shop });
    setStep("done");
  }, [tips, save, nMachines]);

  const onStep = React.useCallback(
    (s: TipStep) => {
      if (s === "done") finish();
      else setStep(s);
    },
    [finish],
  );

  // The "Skipped" note goes after a few seconds; Home › Setup keeps the place.
  React.useEffect(() => {
    if (!skipped) return;
    const t = window.setTimeout(() => setSkipped(false), 9000);
    return () => window.clearTimeout(t);
  }, [skipped]);

  const card = tips && !quiet && !nMachines && !skipped ? shopCardDue(tips, now) : null;

  return (
    <>
      {showTips ? <Tips step={step} onStep={onStep} onDone={finish} teamMachines={team} /> : null}
      {card === "card" ? (
        <aside className="nb-shopcard" aria-labelledby="nb-sc-t">
          <span className="h">
            <b id="nb-sc-t">Your shop</b>
            <span className="chip c-unk">
              <i />
              Not set up
            </span>
          </span>
          <p>Add the machines you have. This part re-checks against them, and the answer names the machine that can make it.</p>
          <small>About 2 minutes · re-checking the same file doesn’t use a check</small>
          <span className="acts">
            <button className="btn ink sm" type="button" onClick={() => key && openShopSheet(key)}>
              Add your machines
            </button>
            <button className="btn ghost sm" type="button" onClick={() => tips && save({ ...tips, shop: "later" })}>
              Not now
            </button>
          </span>
        </aside>
      ) : card === "chip" ? (
        <button className="btn sm nb-shopchip" type="button" onClick={() => key && openShopSheet(key)}>
          Your shop: not set up · Add machines
        </button>
      ) : null}
      {skipped && !sheetOpen && !rc ? (
        <div className="toast nb-toast" role="status">
          <span>Skipped. Answers use typical machines and rates. Home › Setup keeps your place.</span>
          <button
            className="btn sm"
            type="button"
            onClick={() => {
              setSkipped(false);
              if (key) openShopSheet(key);
            }}
          >
            Add machines
          </button>
        </div>
      ) : null}
      {sheetOpen ? (
        <ShopSheet
          onClose={() => {
            closeShopSheet();
            if (tips) save({ ...tips, shop: "done" });
          }}
          onSkip={() => {
            closeShopSheet();
            setSkipped(true);
            if (tips) save({ ...tips, shop: "done" });
          }}
        />
      ) : null}
      {rc ? <Aha rc={rc} /> : null}
    </>
  );
}
