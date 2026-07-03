"use client";

/**
 * PartDoor — the design/mfg engineer's door (verb: DROP). Part-first: a real
 * dropzone over the existing upload flow, plus a "my recent parts" strip off the
 * real analyses endpoint, and the door cross-nav. NO catalog on this door.
 *
 * On drop, the file is handed straight to PartWorkspace (seeded via `initialFile`),
 * which runs the same real cost + DFM path and renders the FE-2 part hero. When
 * the user resets ("New part"), PartWorkspace calls `onExit` and we return to
 * this landing — so the door, not the bare workspace cold-start, is home.
 */

import { useState } from "react";
import PartWorkspace from "@/components/workspace/PartWorkspace";
import { Dropzone } from "@/components/ui/dropzone";
import { Rise } from "@/components/ui/motion";
import { CAD_ACCEPT, isSupportedCad, supportedCadLabel } from "@/lib/cad-file";
import { RecentParts } from "./RecentParts";
import { DoorCrossNav, type DoorNav } from "./DoorCrossNav";

export function PartDoor({ nav }: { nav: DoorNav }) {
  const [file, setFile] = useState<File | null>(null);

  if (file) {
    // Hand off to the FE-2 part hero on the real engine path.
    return (
      <PartWorkspace
        defaultRole="design"
        initialFile={file}
        onExit={() => setFile(null)}
      />
    );
  }

  return <PartDoorLanding nav={nav} onFile={setFile} />;
}

function PartDoorLanding({
  nav,
  onFile,
}: {
  nav: DoorNav;
  onFile: (file: File) => void;
}) {
  const [error, setError] = useState<string | null>(null);

  const accept = (selected: File) => {
    if (!isSupportedCad(selected.name)) {
      setError(`Unsupported file type. Use ${supportedCadLabel()}.`);
      return;
    }
    setError(null);
    onFile(selected);
  };

  return (
    <div className="flex h-full min-h-full flex-col p-6">
      <DoorCrossNav nav={nav} />

      <div className="mx-auto w-full max-w-2xl space-y-5 py-6">
        <Rise>
          <div>
            <span className="num cv-eyebrow text-accent-text">I have a part · DROP</span>
            <h1 className="mt-2 text-display font-semibold tracking-tight text-foreground">
              Drop a CAD file — get the decision, then the receipts.
            </h1>
            <p className="mt-1.5 max-w-prose text-sm text-muted-foreground">
              The inspection and the make-vs-buy answer in minutes — findings pinned to the
              geometry, dollars pinned to their source.
            </p>
          </div>
        </Rise>

        <Rise delay={90}>
          <Dropzone
            accept={CAD_ACCEPT}
            onFiles={(files) => files[0] && accept(files[0])}
            hint="STEP, STP or STL · CAD is parsed and discarded in-process · zero egress"
          />
        </Rise>

        {error && (
          <p className="rounded-[var(--radius)] border border-fail-border bg-fail-bg px-3 py-2 text-sm text-fail">
            {error}
          </p>
        )}

        <Rise delay={150}>
          <RecentParts />
        </Rise>
      </div>
    </div>
  );
}
