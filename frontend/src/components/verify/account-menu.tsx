"use client";

import Link from "next/link";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { BookOpen, Building2, Code2, Lock, LogOut, User } from "lucide-react";
import { useAuth } from "@/components/ui/auth-provider";
import { C, MONO } from "@/lib/verify/tokens";

const itemClass =
  "flex cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2.5 text-[13px] text-[#3f4146] no-underline outline-none data-[highlighted]:bg-[#f1f2f4] data-[highlighted]:text-[#17181a]";

export function VerifyAccountMenu() {
  const { user, signOut } = useAuth();
  const initial = user?.email.trim().charAt(0).toUpperCase() || "U";

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="cv-verify-account-button"
          aria-label={user ? `Account menu for ${user.email}` : "Account menu"}
          title="Account, settings, and help"
          style={{
            width: 34,
            height: 34,
            flexShrink: 0,
            borderRadius: "50%",
            border: `1px solid ${C.hair}`,
            background: C.ink,
            color: "#fff",
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: MONO,
            fontSize: 11,
            fontWeight: 600,
          }}
        >
          {initial}
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          aria-label="Account and workspace menu"
          style={{
            zIndex: 120,
            width: 270,
            border: `1px solid ${C.hair}`,
            borderRadius: 14,
            background: "#fff",
            padding: 7,
            color: C.ink,
            boxShadow: "0 18px 50px rgba(23,24,26,0.16)",
            fontFamily: "inherit",
          }}
        >
          <div style={{ padding: "8px 10px 10px", minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <span style={{ display: "inline-flex", width: 26, height: 26, flexShrink: 0, alignItems: "center", justifyContent: "center", borderRadius: "50%", background: C.sunken, color: C.ink55 }}>
                <User size={14} aria-hidden />
              </span>
              <div style={{ minWidth: 0 }}>
                <p style={{ margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 13, fontWeight: 500 }}>{user?.email ?? "Signed-in user"}</p>
                <p style={{ margin: "3px 0 0", fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase", color: C.ink45 }}>{user?.role ?? "member"}</p>
              </div>
            </div>
          </div>

          <DropdownMenu.Separator style={{ height: 1, margin: "1px 4px 6px", background: C.hair }} />
          <DropdownMenu.Item asChild>
            <Link className={itemClass} href="/settings/organization"><Building2 size={15} aria-hidden />Organization &amp; members</Link>
          </DropdownMenu.Item>
          <DropdownMenu.Item asChild>
            <Link className={itemClass} href="/settings/security"><Lock size={15} aria-hidden />Security &amp; sign-in</Link>
          </DropdownMenu.Item>
          <DropdownMenu.Item asChild>
            <Link className={itemClass} href="/settings/developer"><Code2 size={15} aria-hidden />API keys &amp; integrations</Link>
          </DropdownMenu.Item>
          <DropdownMenu.Item asChild>
            <Link className={itemClass} href="/api-reference"><BookOpen size={15} aria-hidden />API reference &amp; help</Link>
          </DropdownMenu.Item>

          <DropdownMenu.Separator style={{ height: 1, margin: "6px 4px", background: C.hair }} />
          <DropdownMenu.Item
            onSelect={() => void signOut()}
            className={`${itemClass} text-[#b42318] data-[highlighted]:bg-[#fff0ee] data-[highlighted]:text-[#b42318]`}
          >
            <LogOut size={15} aria-hidden />Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
