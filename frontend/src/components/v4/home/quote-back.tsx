"use client";

/**
 * The vendor's quote-back (flywheel gear 1): a supplier opening a part's share
 * link can answer with their actual price — and optional lead time — in about
 * thirty seconds. The answer POSTs through the same-origin public-share proxy
 * (the one write that surface accepts) and lands, server-side, as quote-typed
 * ground truth on the BUYER's org plus a notification. No account, no PII
 * beyond what the vendor types; the short link is the capability.
 */
import * as React from "react";

type State = { kind: "idle" } | { kind: "sending" } | { kind: "done" } | { kind: "error"; message: string };

export function QuoteBack({ shortId, quantity }: { shortId: string; quantity: number | null }) {
  const [state, setState] = React.useState<State>({ kind: "idle" });
  const [unitCost, setUnitCost] = React.useState("");
  const [leadDays, setLeadDays] = React.useState("");
  const [shop, setShop] = React.useState("");
  const [contact, setContact] = React.useState("");
  const [note, setNote] = React.useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setState({ kind: "sending" });
    const payload: Record<string, unknown> = { unit_cost_usd: Number(unitCost) };
    if (leadDays) payload.lead_days = Number(leadDays);
    if (shop.trim()) payload.shop_name = shop.trim();
    if (contact.trim()) payload.contact = contact.trim();
    if (note.trim()) payload.note = note.trim();
    try {
      const res = await fetch(`/api/public-share/s/cost/${shortId}/quote`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = (await res.json().catch(() => ({}))) as { detail?: string; message?: string };
      if (res.ok) {
        setState({ kind: "done" });
      } else {
        setState({ kind: "error", message: body.detail || "The quote didn't send — try again." });
      }
    } catch {
      setState({ kind: "error", message: "No connection — try again." });
    }
  }

  if (state.kind === "done") {
    return (
      <section className="sp-quote" aria-label="Quote sent">
        <div className="gh">
          <span>Quote sent</span>
          <span />
        </div>
        <p className="sp-line">
          Thank you — the buyer received your price{leadDays ? ` and ${leadDays}-day lead` : ""}. They
          may contact you{contact ? ` at ${contact}` : ""} about the order.
        </p>
      </section>
    );
  }

  return (
    <section className="sp-quote" aria-label="Send your quote">
      <form onSubmit={submit}>
        <div className="gh">
          <span>This is my quote</span>
          <span>{quantity ? `for ${quantity.toLocaleString("en-US")} pieces` : ""}</span>
        </div>
        <p className="sp-line">What you&apos;d charge per part. The buyer sees it as a quote against their should-cost; it takes 30 seconds and needs no account.</p>
        <label className="field">
          Price each (USD)
          <input
            type="number" step="0.01" min="0" inputMode="decimal" required
            placeholder="12.75" value={unitCost}
            onChange={(e) => setUnitCost(e.target.value)}
            disabled={state.kind === "sending"}
          />
        </label>
        <label className="field">
          Lead time (days, optional)
          <input
            type="number" min="1" inputMode="numeric" placeholder="21"
            value={leadDays} onChange={(e) => setLeadDays(e.target.value)}
            disabled={state.kind === "sending"}
          />
        </label>
        <label className="field">
          Shop (optional)
          <input type="text" placeholder="Acme Machine" maxLength={120}
            value={shop} onChange={(e) => setShop(e.target.value)}
            disabled={state.kind === "sending"} />
        </label>
        <label className="field">
          Contact (optional)
          <input type="text" placeholder="quotes@acme.com" maxLength={120}
            value={contact} onChange={(e) => setContact(e.target.value)}
            disabled={state.kind === "sending"} />
        </label>
        <label className="field">
          Note (optional)
          <input type="text" placeholder="includes finishing" maxLength={500}
            value={note} onChange={(e) => setNote(e.target.value)}
            disabled={state.kind === "sending"} />
        </label>
        {state.kind === "error" ? <p role="alert" style={{ color: "#b3261e" }}>{state.message}</p> : null}
        <button className="btn ink" type="submit" disabled={state.kind === "sending" || !unitCost}>
          {state.kind === "sending" ? "Sending…" : "Send quote"}
        </button>
      </form>
    </section>
  );
}
