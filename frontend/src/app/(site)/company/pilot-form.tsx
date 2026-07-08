"use client";

/**
 * The pilot request form on /company#pilot. Page-local (NOT foundation).
 *
 * Ported faithfully from handoff_cadverify_2026-07-04/site/Company.dc.html: work
 * email, company, and "what do you make?" fields, the deployment note, and the
 * Send pill. There is no lead-capture endpoint wired yet, so submit opens a
 * real addressed email draft instead of faking a server-side receipt.
 */

import * as React from "react";
import styles from "./company.module.css";

export function PilotForm() {
  const [sentToMail, setSentToMail] = React.useState(false);

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const email = String(form.get("email") || "").trim();
    const company = String(form.get("company") || "").trim();
    const what = String(form.get("what") || "").trim();
    const subject = encodeURIComponent(`CadVerify pilot request${company ? ` — ${company}` : ""}`);
    const body = encodeURIComponent([
      "Pilot request",
      "",
      `Work email: ${email}`,
      `Company: ${company}`,
      `What we make: ${what}`,
      "",
      "Deployment preference: cloud / VPC / air-gapped",
    ].join("\n"));
    setSentToMail(true);
    window.location.href = `mailto:pilots@cadverify.com?subject=${subject}&body=${body}`;
  }

  return (
    <form
      className={styles.formCard}
      onSubmit={onSubmit}
      aria-label="Request a pilot"
    >
      <p style={{ margin: 0, fontSize: 19, fontWeight: 400 }}>Request a pilot</p>
      <p style={{ margin: "8px 0 0", fontSize: 13.5, fontWeight: 300, color: "rgba(245,245,247,0.5)" }}>
        We reply within two business days. Security teams welcome from day one.
      </p>
      <div className={styles.formGrid}>
        <label className={styles.fieldLabel}>
          <span>Work email</span>
          <input
            className={styles.pilotInput}
            name="email"
            type="email"
            placeholder="you@company.com"
            autoComplete="email"
            required
          />
        </label>
        <label className={styles.fieldLabel}>
          <span>Company</span>
          <input
            className={styles.pilotInput}
            name="company"
            placeholder="Company name"
            autoComplete="organization"
            required
          />
        </label>
        <label className={`${styles.fieldLabel} ${styles.formGridWide}`}>
          <span>What do you make?</span>
          <input
            className={styles.pilotInput}
            name="what"
            placeholder="Parts, programs, materials, or supplier flow"
            required
          />
        </label>
      </div>
      <div className={styles.formFoot}>
        <span
          className="st-mono"
          style={{ fontSize: 11, color: "rgba(245,245,247,0.35)" }}
        >
          cloud · VPC · air-gapped — your call
        </span>
        <button type="submit" className={styles.sendBtn}>
          Send
        </button>
      </div>
      <p className={styles.mailFallback}>
        {sentToMail ? "Email draft opened." : "Submits through your email client."} Direct:
        {" "}
        <a href="mailto:pilots@cadverify.com">pilots@cadverify.com</a>
      </p>
    </form>
  );
}
