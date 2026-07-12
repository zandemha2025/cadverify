"use client";
/**
 * Client interactions for the org-admin surface. Each control invokes a Server
 * Action from ./actions and surfaces its real `{ ok } | { error }` result inline
 * — no optimistic fabrication. On success we `router.refresh()` so the server
 * component re-reads live backend state (the action also `revalidatePath`s).
 */
import * as React from "react";
import { useRouter } from "next/navigation";
import { Trash2, UserMinus, Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/field";
import { AlertDialog } from "@/components/ui/alert-dialog";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import {
  createInvite,
  revokeInvite,
  removeMember,
  createSamlMapping,
  deleteSamlMapping,
  type OrgRole,
} from "./actions";

const ROLE_OPTIONS: OrgRole[] = ["viewer", "member", "admin"];

// ── Invites ────────────────────────────────────────────────────────────────
export function InviteForm() {
  const router = useRouter();
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState<OrgRole>("member");
  const [error, setError] = React.useState<string | null>(null);
  const [link, setLink] = React.useState<string | null>(null);
  const [emailed, setEmailed] = React.useState(false);
  const [pending, start] = React.useTransition();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLink(null);
    start(async () => {
      const res = await createInvite(email.trim(), role);
      if (!res.ok) {
        setError(res.error);
        return;
      }
      setLink(res.data?.accept_link ?? "");
      setEmailed(!!res.data?.emailed);
      setEmail("");
      router.refresh();
    });
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <Field label="Email" htmlFor="invite-email" className="flex-1">
          <Input
            id="invite-email"
            type="email"
            required
            placeholder="teammate@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            error={!!error}
          />
        </Field>
        <Field label="Role" className="sm:w-40">
          <Select value={role} onValueChange={(v) => setRole(v as OrgRole)}>
            <SelectTrigger className="capitalize">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ROLE_OPTIONS.map((r) => (
                <SelectItem key={r} value={r} className="capitalize">
                  {r}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Button type="submit" loading={pending} className="sm:mb-0">
          Send invite
        </Button>
      </div>
      {error && <p className="text-xs text-fail">{error}</p>}
      {link !== null && (
        <div className="rounded-[var(--radius)] border border-pass-border bg-pass-bg px-3 py-2 text-xs">
          <p className="font-medium text-foreground">
            Invite created{emailed ? " and emailed." : "."} One-time accept link
            (shown once):
          </p>
          <CopyLink link={link} />
        </div>
      )}
    </form>
  );
}

function CopyLink({ link }: { link: string }) {
  const [copied, setCopied] = React.useState(false);
  if (!link) return null;
  return (
    <div className="mt-1 flex items-center gap-2">
      <code className="num min-w-0 flex-1 truncate rounded-xs bg-card px-2 py-1 text-[11px] text-muted-foreground">
        {link}
      </code>
      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={() => {
          void navigator.clipboard?.writeText(link);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}

export function RevokeInviteButton({ inviteId }: { inviteId: number }) {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [pending, start] = React.useTransition();

  function confirm() {
    setError(null);
    start(async () => {
      const res = await revokeInvite(inviteId);
      if (!res.ok) {
        setError(res.error);
        return;
      }
      setOpen(false);
      router.refresh();
    });
  }

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="text-fail hover:text-fail"
        onClick={() => setOpen(true)}
      >
        Revoke
      </Button>
      {error && <p className="mt-1 text-right text-xs text-fail">{error}</p>}
      <AlertDialog
        open={open}
        onOpenChange={setOpen}
        title="Revoke this invite?"
        description="The one-time accept link will stop working immediately."
        confirmLabel="Revoke invite"
        loading={pending}
        onConfirm={confirm}
      />
    </>
  );
}

// ── Members ──────────────────────────────────────────────────────────────────
export function RemoveMemberButton({
  userId,
  email,
  isSelf,
}: {
  userId: number;
  email: string;
  isSelf: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [pending, start] = React.useTransition();

  function confirm() {
    setError(null);
    start(async () => {
      const res = await removeMember(userId);
      if (!res.ok) {
        // Surface the backend's real guard (e.g. last-admin) honestly.
        setError(res.error);
        return;
      }
      setOpen(false);
      router.refresh();
    });
  }

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="text-fail hover:text-fail"
        onClick={() => {
          setError(null);
          setOpen(true);
        }}
      >
        <UserMinus className="size-3.5" />
        {isSelf ? "Leave" : "Remove"}
      </Button>
      {error && <p className="mt-1 text-right text-xs text-fail">{error}</p>}
      <AlertDialog
        open={open}
        onOpenChange={setOpen}
        title={isSelf ? "Leave this organization?" : `Remove ${email}?`}
        description={
          isSelf
            ? "You will lose access to this organization immediately."
            : "They lose access to this organization immediately. The last admin cannot be removed."
        }
        confirmLabel={isSelf ? "Leave org" : "Remove member"}
        loading={pending}
        onConfirm={confirm}
      />
    </>
  );
}

// ── SAML group → role mappings ───────────────────────────────────────────────
export function SamlMappingForm() {
  const router = useRouter();
  const [attr, setAttr] = React.useState("groups");
  const [value, setValue] = React.useState("");
  const [role, setRole] = React.useState<OrgRole>("member");
  const [error, setError] = React.useState<string | null>(null);
  const [pending, start] = React.useTransition();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    start(async () => {
      const res = await createSamlMapping(attr.trim(), value.trim(), role);
      if (!res.ok) {
        setError(res.error);
        return;
      }
      setValue("");
      router.refresh();
    });
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <Field
          label="SAML attribute"
          htmlFor="saml-attr"
          className="sm:w-48"
          hint="e.g. groups, memberOf"
        >
          <Input
            id="saml-attr"
            required
            value={attr}
            onChange={(e) => setAttr(e.target.value)}
          />
        </Field>
        <Field label="Group value" htmlFor="saml-value" className="flex-1">
          <Input
            id="saml-value"
            required
            placeholder="cadverify-admins"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            error={!!error}
          />
        </Field>
        <Field label="Grants role" className="sm:w-40">
          <Select value={role} onValueChange={(v) => setRole(v as OrgRole)}>
            <SelectTrigger className="capitalize">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ROLE_OPTIONS.map((r) => (
                <SelectItem key={r} value={r} className="capitalize">
                  {r}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Button type="submit" loading={pending}>
          Add mapping
        </Button>
      </div>
      {error && <p className="text-xs text-fail">{error}</p>}
    </form>
  );
}

export function DeleteMappingButton({ mappingId }: { mappingId: number }) {
  const router = useRouter();
  const [error, setError] = React.useState<string | null>(null);
  const [pending, start] = React.useTransition();

  function del() {
    setError(null);
    start(async () => {
      const res = await deleteSamlMapping(mappingId);
      if (!res.ok) {
        setError(res.error);
        return;
      }
      router.refresh();
    });
  }

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="text-fail hover:text-fail"
        loading={pending}
        onClick={del}
      >
        <Trash2 className="size-3.5" />
        Delete
      </Button>
      {error && <p className="mt-1 text-right text-xs text-fail">{error}</p>}
    </>
  );
}
