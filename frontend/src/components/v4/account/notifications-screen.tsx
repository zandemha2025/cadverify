"use client";

/**
 * Notifications (board A5): the inbox grouped by part, with All / Unread /
 * Dismissed, Mark all read, and per item Open (marks it read, then opens its
 * record or the changes list), Dismiss and Restore, plus Dismiss all / Restore
 * all for a part. Reading or dismissing only changes your inbox; records, the
 * audit log and webhook deliveries stay as they are.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { API_BASE } from "@/lib/api-base";
import {
  dismissNotification,
  markAllNotificationsRead,
  markNotificationRead,
  restoreNotification,
  type DerivedNotif,
} from "@/lib/verify/notifications-api";
import { Content, KV, Loading, Sheet, cx } from "../ui";
import { R } from "../routes";
import { AccountFrame, AccountHead, Banner, PartGlyph } from "./frame";
import { messageFrom } from "./api";
import { dayLabel, groupNotifications, kindName, notificationHref, plural, whenLabel, type NotificationRow } from "./derive";

type View = "all" | "unread" | "dismissed";

async function readRows(dismissed: boolean): Promise<NotificationRow[]> {
  const q = new URLSearchParams({ status: "open", unread: "false", dismissed: String(dismissed), limit: "100" });
  const res = await fetch(`${API_BASE}/notifications?${q.toString()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(messageFrom(await res.json().catch(() => null)) ?? `Request failed (${res.status})`);
  const body = (await res.json()) as { notifications?: NotificationRow[] };
  return body.notifications ?? [];
}

function apply(row: NotificationRow, d: DerivedNotif): NotificationRow {
  return { ...row, is_read: d.isRead, read_at: d.readAt, is_dismissed: d.isDismissed, dismissed_at: d.dismissedAt };
}

export function NotificationsScreen() {
  const router = useRouter();
  const [active, setActive] = React.useState<NotificationRow[] | null>(null);
  const [dismissed, setDismissed] = React.useState<NotificationRow[] | null>(null);
  const [loadErr, setLoadErr] = React.useState<string | null>(null);
  const [actErr, setActErr] = React.useState<string | null>(null);
  const [view, setView] = React.useState<View>("all");
  const [sel, setSel] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoadErr(null);
    setActErr(null);
    try {
      const [a, d] = await Promise.all([readRows(false), readRows(true)]);
      setActive(a);
      setDismissed(d);
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : "Couldn’t load notifications.");
    }
  }, []);
  React.useEffect(() => {
    void load();
  }, [load]);

  const now = new Date();
  const unreadRows = (active ?? []).filter((r) => !r.is_read);
  const shownRows = view === "dismissed" ? dismissed ?? [] : view === "unread" ? unreadRows : active ?? [];
  const groups = groupNotifications(shownRows);
  const g = groups.find((x) => x.key === sel) ?? groups[0] ?? null;
  const kinds = new Set((active ?? []).map((r) => kindName(r)));
  const partCount = new Set((active ?? []).map((r) => r.metadata?.filename).filter(Boolean)).size;

  async function pick(key: string) {
    setSel(key);
    // On a phone the sheet sits under the list: bring it into view.
    if (window.matchMedia("(max-width: 900px)").matches) {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.requestAnimationFrame(() => document.getElementById("a-notif-sheet")?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" }));
    }
    if (view === "dismissed") return;
    const grp = groups.find((x) => x.key === key);
    const unread = grp?.items.filter((i) => !i.is_read) ?? [];
    if (!unread.length) return;
    const done = await Promise.allSettled(unread.map((i) => markNotificationRead(i.id)));
    const byId = new Map<string, DerivedNotif>();
    done.forEach((r) => {
      if (r.status === "fulfilled") byId.set(r.value.id, r.value);
    });
    setActive((rows) => (rows ? rows.map((r) => (byId.has(r.id) ? apply(r, byId.get(r.id)!) : r)) : rows));
  }

  async function act(id: string, kind: "dismiss" | "restore") {
    setBusy(id);
    setActErr(null);
    try {
      if (kind === "dismiss") {
        const d = await dismissNotification(id);
        const row = active?.find((r) => r.id === id);
        setActive((rows) => (rows ? rows.filter((r) => r.id !== id) : rows));
        if (row) setDismissed((rows) => [apply(row, d), ...(rows ?? []).filter((r) => r.id !== id)]);
      } else {
        const d = await restoreNotification(id);
        const row = dismissed?.find((r) => r.id === id);
        setDismissed((rows) => (rows ? rows.filter((r) => r.id !== id) : rows));
        if (row) setActive((rows) => [apply(row, d), ...(rows ?? []).filter((r) => r.id !== id)].sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? "")));
      }
    } catch (e) {
      setActErr(e instanceof Error ? e.message : "Notification was not updated.");
    } finally {
      setBusy(null);
    }
  }

  async function actAll(ids: string[], kind: "dismiss" | "restore") {
    setBusy("group");
    setActErr(null);
    const fn = kind === "dismiss" ? dismissNotification : restoreNotification;
    const done = await Promise.allSettled(ids.map((id) => fn(id)));
    const ok = new Map<string, DerivedNotif>();
    let failed = 0;
    done.forEach((r) => {
      if (r.status === "fulfilled") ok.set(r.value.id, r.value);
      else failed += 1;
    });
    if (kind === "dismiss") {
      const moved = (active ?? []).filter((r) => ok.has(r.id)).map((r) => apply(r, ok.get(r.id)!));
      setActive((rows) => (rows ? rows.filter((r) => !ok.has(r.id)) : rows));
      setDismissed((rows) => [...moved, ...(rows ?? [])]);
    } else {
      const moved = (dismissed ?? []).filter((r) => ok.has(r.id)).map((r) => apply(r, ok.get(r.id)!));
      setDismissed((rows) => (rows ? rows.filter((r) => !ok.has(r.id)) : rows));
      setActive((rows) => [...moved, ...(rows ?? [])].sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? "")));
    }
    if (failed) setActErr(`${plural(failed, "notification")} didn’t change.`);
    setSel(null);
    setBusy(null);
  }

  async function readAll() {
    setBusy("all");
    setActErr(null);
    try {
      const r = await markAllNotificationsRead();
      setActive((rows) => (rows ? rows.map((x) => ({ ...x, is_read: true, read_at: x.read_at ?? r.readAt })) : rows));
    } catch (e) {
      setActErr(e instanceof Error ? e.message : "Notifications were not updated.");
    } finally {
      setBusy(null);
    }
  }

  async function open(row: NotificationRow, e: React.MouseEvent<HTMLAnchorElement>) {
    const href = notificationHref(row);
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
      if (!row.is_read) void markNotificationRead(row.id).catch(() => undefined);
      return;
    }
    e.preventDefault();
    if (busy) return;
    setBusy(`open:${row.id}`);
    if (!row.is_read && !row.is_dismissed) await markNotificationRead(row.id).catch(() => undefined);
    router.push(href);
  }

  const filters: [View, string, number | null][] = [
    ["all", "All", active ? active.length : null],
    ["unread", "Unread", active ? unreadRows.length : null],
    ["dismissed", "Dismissed", dismissed ? dismissed.length : null],
  ];
  const emptyTitle = view === "dismissed" ? "No dismissed notifications" : view === "unread" ? "No unread notifications" : "No notifications";
  const emptyLine = view === "dismissed" ? "Dismissed items can be restored here." : "New checks and review requests appear here.";
  const items = g?.items ?? [];

  return (
    <AccountFrame label="Notifications">
      <AccountHead
        title="Notifications"
        meta={[
          <span key="u">Unread <b className="num">{active ? unreadRows.length : "—"}</b></span>,
          <span key="t">Total <b className="num">{active ? active.length : "—"}</b></span>,
          <span key="p">Parts <b className="num">{active ? partCount : "—"}</b></span>,
          ...(kinds.size === 1 ? [<span key="k">Kind <b>{[...kinds][0]}</b></span>] : []),
        ]}
      />
      <Content>
        {actErr ? (
          <Banner title="Nothing changed." actions={<button className="btn sm" type="button" onClick={() => void load()}>Reload inbox</button>}>
            {actErr}
          </Banner>
        ) : null}
        {loadErr ? (
          <Banner title="Couldn’t load notifications." actions={<button className="btn sm" type="button" onClick={() => void load()}>Try again</button>}>
            {loadErr}
          </Banner>
        ) : null}
        <section className="panel" aria-label="By part">
          <div className="ph" style={{ alignItems: "center", flexWrap: "wrap" }}>
            <span className="a-tools">
              <span className="seg" role="group" aria-label="Show">
                {filters.map(([k, label, n]) => (
                  <button key={k} type="button" className={cx(view === k && "on")} aria-pressed={view === k} onClick={() => { setView(k); setSel(null); }}>
                    {label}{" "}
                    <span className="num" style={{ opacity: 0.7 }}>
                      {n ?? "—"}
                    </span>
                  </button>
                ))}
              </span>
            </span>
            <span className="a-tools">
              {unreadRows.length > 0 ? (
                <button className="btn sm" type="button" onClick={() => void readAll()} disabled={busy === "all"} aria-busy={busy === "all"}>
                  {busy === "all" ? "Marking…" : "Mark all read"}
                </button>
              ) : null}
              <Link className="btn sm" href={R.parts}>
                Open parts
              </Link>
            </span>
          </div>
          {!active && !loadErr ? (
            <Loading rows={4} label="Loading notifications" />
          ) : (
            <div className="list" aria-label="Notifications by part">
              {groups.map((x) => {
                const n = x.items.length;
                return (
                  <button key={x.key} type="button" className={cx("lrow a-nrow", g?.key === x.key && "on")} aria-pressed={g?.key === x.key} onClick={() => void pick(x.key)}>
                    <PartGlyph />
                    <span style={{ minWidth: 0 }}>
                      <b title={x.file}>{x.file}</b>
                      <small>
                        {x.kind} · {plural(n, x.isPart ? "check" : "notification")} · latest {whenLabel(x.latest, now)} UTC
                      </small>
                    </span>
                    <span className="c num" style={{ color: "var(--ink3)", fontWeight: 500 }}>
                      {n}
                    </span>
                    <span className={cx("a-un", (view === "dismissed" || x.unread === 0) && "read")} role="img" aria-label={view === "dismissed" ? "Dismissed" : x.unread ? `${x.unread} unread` : "Read"} />
                  </button>
                );
              })}
              {groups.length === 0 && (active || dismissed) ? (
                <div className="empty">
                  <b>{emptyTitle}</b>
                  <span>{emptyLine}</span>
                </div>
              ) : null}
            </div>
          )}
        </section>
      </Content>
      <Sheet label="Selected part" style={{ bottom: 20 }}>
        <span id="a-notif-sheet" />
        {g ? (
          <>
            <div className="top" style={{ display: "flex", gap: 14, alignItems: "center" }}>
              <PartGlyph large />
              <span style={{ minWidth: 0 }}>
                <h2 className="stitle a-wrap">{g.file}</h2>
                <p className="smeta">
                  {plural(items.length, g.isPart ? "check" : "notification")} · {view === "dismissed" ? "dismissed" : "in inbox"}
                  {g.latest ? ` · ${dayLabel(g.latest)}` : ""}
                </p>
              </span>
            </div>
            <div className="scroll">
              <div style={{ padding: "4px 0" }} aria-live="polite">
                {items.map((i) => {
                  const t = whenLabel(i.created_at, now);
                  const what = `${kindName(i).toLowerCase()}, ${g.file}, ${t}`;
                  const isDis = view === "dismissed";
                  return (
                    <div className="a-ni" key={i.id}>
                      <span>
                        <b>{kindName(i)}</b>
                        <small>{isDis ? `Dismissed ${dayLabel(i.dismissed_at)}` : i.is_read ? `Read ${dayLabel(i.read_at)}` : "Unread"}</small>
                      </span>
                      <span className="a-when num">{t} UTC</span>
                      <span className="a-nacts">
                        <a className="btn sm" href={notificationHref(i)} aria-label={`Open notification: ${what}`} aria-busy={busy === `open:${i.id}`} onClick={(e) => void open(i, e)}>
                          {busy === `open:${i.id}` ? "Opening…" : "Open"}
                        </a>
                        <button className="btn sm" type="button" aria-label={`${isDis ? "Restore" : "Dismiss"} notification: ${what}`} disabled={busy === i.id || busy === "group"} onClick={() => void act(i.id, isDis ? "restore" : "dismiss")}>
                          {busy === i.id ? "Working…" : isDis ? "Restore" : "Dismiss"}
                        </button>
                      </span>
                    </div>
                  );
                })}
              </div>
              <div style={{ display: "flex", gap: 8, padding: "10px 12px", flexWrap: "wrap" }}>
                <Link className="btn ink sm" href={g.isPart ? R.records : R.changes}>
                  {g.isPart ? "Open records" : "Open changes"}
                </Link>
                <button className="btn sm" type="button" disabled={busy === "group" || !items.length} onClick={() => void actAll(items.map((i) => i.id), view === "dismissed" ? "restore" : "dismiss")}>
                  {busy === "group" ? "Working…" : `${view === "dismissed" ? "Restore" : "Dismiss"} all ${items.length}`}
                </button>
              </div>
              <div className="note">
                <b>Source of truth</b>
                <span>Records, the audit log and webhook deliveries stay as they are. Reading or dismissing only changes your inbox.</span>
              </div>
              <KV
                rows={[
                  ["Shown", "Latest 100"],
                  ["Check recorded", "Everyone"],
                  ["Change needs review", "Admins"],
                ]}
              />
            </div>
          </>
        ) : (
          <div className="top">
            <h2 className="stitle">No part selected</h2>
            <p className="smeta">{active || dismissed ? emptyTitle : "Loading…"}</p>
          </div>
        )}
      </Sheet>
    </AccountFrame>
  );
}
