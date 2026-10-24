"use client";

/**
 * The part someone added on the sign-in screen, picked up after sign-in.
 *
 * It waits in this browser's IndexedDB (lib/pending-part.ts), keyed to the
 * email it was held for, for at most two hours. It is handed only to the
 * signed-in account with that same email, and taken at most once.
 *
 * `useHeldPart()` → `{ file, ready }`: call it on a signed-in v4 page; `ready`
 * turns true once the store has been read (`file` is null when nothing waits).
 * The in-memory hand-off (`setPendingFile`/`takePendingFile`) is checked first,
 * so a file picked moments ago on the same tab wins.
 */
import * as React from "react";
import { useAuth } from "@/components/ui/auth-provider";
import { browserPendingPartStore, takePendingPart } from "@/lib/pending-part";
import { takePendingFile } from "../pending-file";
import { markHeld } from "../onboard/state";

export function useHeldPart(): { file: File | null; ready: boolean } {
  const { user } = useAuth();
  const email = user?.email ?? null;
  const [state, setState] = React.useState<{ file: File | null; ready: boolean }>({ file: null, ready: false });
  // One take per mount, shared by Strict Mode's repeated effect runs.
  const pending = React.useRef<Promise<File | null> | null>(null);
  React.useEffect(() => {
    if (!pending.current) {
      const memory = takePendingFile();
      pending.current = memory
        ? Promise.resolve(memory)
        : email
          ? takePendingPart(browserPendingPartStore(), email)
              .then((f) => {
                // The first check says "Held from sign-up" for this file (N1).
                if (f) markHeld(f);
                return f;
              })
              .catch(() => null)
          : Promise.resolve(null);
    }
    let live = true;
    void pending.current.then((file) => {
      if (live) setState({ file, ready: true });
    });
    return () => {
      live = false;
    };
  }, [email]);
  return state;
}
