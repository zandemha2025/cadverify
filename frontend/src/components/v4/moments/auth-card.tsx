"use client";

/**
 * The account-state card (board X12): icon, title, fact line, optional fields,
 * a key/value info box, an error line, actions, links and a footnote. Every
 * signed-out screen except sign-in itself (sign up, managed access, reset,
 * email link, invite) is one of these on the v4 stage.
 */
import * as React from "react";
import { cx } from "../ui";
import "./moments.css";

export type CardIcon = { tone: "ok" | "bad" | "wait"; mark?: React.ReactNode };

export function AuthCard({
  label,
  icon,
  title,
  meta,
  children,
  info,
  error,
  notice,
  actions,
  links,
  note,
  busy,
}: {
  label: string;
  icon?: CardIcon;
  title: React.ReactNode;
  meta?: React.ReactNode[];
  children?: React.ReactNode;
  info?: [React.ReactNode, React.ReactNode][];
  error?: string | null;
  notice?: React.ReactNode;
  actions?: React.ReactNode;
  links?: React.ReactNode;
  note?: React.ReactNode;
  busy?: boolean;
}) {
  return (
    <main id="main" className="world mo-x12" aria-label={label}>
      <div className="stage" aria-hidden="true" />
      <div className="area">
        <section className="card swap" aria-labelledby="au-title" aria-busy={busy || undefined}>
          <div className="hd">
            {icon ? (
              <div className={cx("ico", icon.tone)} aria-hidden="true">
                {icon.tone === "wait" && icon.mark == null ? <span className="spin" /> : icon.mark}
              </div>
            ) : null}
            <h1 className="ptitle" id="au-title">
              {title}
            </h1>
            {meta && meta.length ? (
              <p className="pmeta" style={{ marginTop: 6 }}>
                {meta.map((m, i) => (
                  <span key={i} style={{ overflowWrap: "anywhere" }}>
                    {m}
                  </span>
                ))}
              </p>
            ) : null}
          </div>
          {children}
          {info && info.length ? (
            <div className="info">
              <div className="kv">
                {info.map(([k, v], i) => (
                  <React.Fragment key={i}>
                    <span>{k}</span>
                    <b>{v}</b>
                  </React.Fragment>
                ))}
              </div>
            </div>
          ) : null}
          {error ? (
            <div className="err" role="alert">
              {error}
            </div>
          ) : null}
          {notice ? (
            <div className="ok-note" role="status">
              {notice}
            </div>
          ) : null}
          {actions ? <div className="acts">{actions}</div> : null}
          {links ? <div className="links">{links}</div> : <div style={{ height: 12 }} />}
          {note ? <p className="fn">{note}</p> : null}
        </section>
      </div>
    </main>
  );
}

/** A labelled input in the card's form, with an optional hint or error under it. */
export function CardField({
  label,
  hint,
  error,
  ...props
}: { label: string; hint?: React.ReactNode; error?: string | null; id: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  const helpId = `${props.id}-help`;
  return (
    <label className="field" htmlFor={props.id}>
      {label}
      <input {...props} aria-invalid={error ? true : props["aria-invalid"]} aria-describedby={hint || error ? helpId : undefined} />
      {error || hint ? (
        <span className={cx("hintx", error && "bad")} id={helpId}>
          {error || hint}
        </span>
      ) : null}
    </label>
  );
}
