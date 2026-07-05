"use client";

/**
 * The pilot request form on /company#pilot. Page-local (NOT foundation).
 *
 * Ported faithfully from handoff_cadverify_2026-07-04/site/Company.dc.html: work
 * email, company, and "what do you make?" fields, the deployment note, and the
 * Send pill. Kept as a semantic <form> with real labelled controls; there is no
 * lead-capture endpoint wired yet, so submit is a no-op guard (never a faked
 * "we received it" success, which would be dishonest). The copy is verbatim
 * canonical — do not rewrite it.
 */

import * as React from "react";
import styles from "./company.module.css";

export function PilotForm() {
  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    // No lead-capture backend is wired on this branch. Guard the default nav
    // so the form does not post to itself; do not fake a success state.
    e.preventDefault();
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
        <input
          className={styles.pilotInput}
          name="email"
          type="email"
          placeholder="Work email"
          aria-label="Work email"
          autoComplete="email"
        />
        <input
          className={styles.pilotInput}
          name="company"
          placeholder="Company"
          aria-label="Company"
          autoComplete="organization"
        />
        <input
          className={`${styles.pilotInput} ${styles.formGridWide}`}
          name="what"
          placeholder="What do you make?"
          aria-label="What do you make?"
        />
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
    </form>
  );
}
