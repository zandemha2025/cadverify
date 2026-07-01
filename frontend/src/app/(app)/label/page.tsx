"use client";

import { useCallback, useEffect, useState } from "react";
import { Tags } from "lucide-react";
import { API_BASE } from "@/lib/api-base";
import { ONTOLOGY } from "@/lib/ontology";
import CorpusViewer from "./CorpusViewer";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Spinner } from "@/components/ui/spinner";

interface Part {
  part_id: string;
  filename: string | null;
  dataset: string | null;
  license: string | null;
  n_faces: number | null;
  volume_cm3: number | null;
  bbox_mm: number[] | null;
  watertight: boolean | null;
  process_family_guess: string | null;
  label: string | null;
  mesh_url: string;
}

interface PartsResponse {
  total: number;
  offset: number;
  limit: number;
  labeled: number;
  unlabeled: number;
  parts: Part[];
}

interface Progress {
  total_parts: number;
  labeled: number;
  unlabeled: number;
  per_label_counts: Record<string, number>;
  per_guess_counts: Record<string, number>;
  labelers: string[];
}

type Confidence = "low" | "medium" | "high";

const DEFAULT_LABELER = "nazeem@anodeadvisory.com";

export default function LabelPage() {
  const [parts, setParts] = useState<Part[]>([]);
  const [index, setIndex] = useState(0);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [labeler, setLabeler] = useState(DEFAULT_LABELER);
  const [confidence, setConfidence] = useState<Confidence>("medium");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const current: Part | undefined = parts[index];

  const refreshProgress = useCallback(async () => {
    try {
      const res = await fetch(
        `${API_BASE}/corpus/progress?labeler=${encodeURIComponent(labeler)}`,
      );
      if (res.ok) setProgress((await res.json()) as Progress);
    } catch {
      /* progress is non-critical */
    }
  }, [labeler]);

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE}/corpus/parts?unlabeled_only=true&limit=200&labeler=${encodeURIComponent(
          labeler,
        )}`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as PartsResponse;
      setParts(data.parts);
      setIndex(0);
    } catch (e) {
      setError(
        `Could not reach the labeling backend at ${API_BASE}. Is it running with LABELING_ENABLED=1? (${
          e instanceof Error ? e.message : String(e)
        })`,
      );
    } finally {
      setLoading(false);
    }
  }, [labeler]);

  useEffect(() => {
    void loadQueue();
    void refreshProgress();
  }, [loadQueue, refreshProgress]);

  const advance = useCallback(() => {
    setIndex((i) => Math.min(i + 1, parts.length));
    setConfidence("medium");
    setNotes("");
  }, [parts.length]);

  const submitLabel = useCallback(
    async (labelKey: string) => {
      if (!current || saving) return;
      setSaving(true);
      setError(null);
      try {
        const res = await fetch(`${API_BASE}/corpus/labels`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            part_id: current.part_id,
            label: labelKey,
            labeler,
            confidence,
            notes: notes || undefined,
          }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        advance();
        void refreshProgress();
      } catch (e) {
        setError(
          `Failed to save label (${
            e instanceof Error ? e.message : String(e)
          })`,
        );
      } finally {
        setSaving(false);
      }
    },
    [current, saving, labeler, confidence, notes, advance, refreshProgress],
  );

  const goPrev = useCallback(() => setIndex((i) => Math.max(i - 1, 0)), []);
  const goNext = useCallback(
    () => setIndex((i) => Math.min(i + 1, parts.length)),
    [parts.length],
  );

  // Keyboard shortcuts: 1-6 label, arrows navigate, s skip.
  // Ignored while an input/textarea is focused.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName || "").toUpperCase();
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      const opt = ONTOLOGY.find((o) => o.hot === e.key);
      if (opt) {
        e.preventDefault();
        void submitLabel(opt.key);
        return;
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        goPrev();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        goNext();
      } else if (e.key === "s" || e.key === "S") {
        e.preventDefault();
        goNext(); // skip = advance without labeling
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [submitLabel, goPrev, goNext]);

  const done = !loading && parts.length > 0 && index >= parts.length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Parts (Label)"
        subtitle="Human ground-truth labeling · CAD stays on localhost."
        actions={
          <div className="flex items-center gap-3">
            <div className="w-64">
              <Field label="Labeler" htmlFor="labeler">
                <Input
                  id="labeler"
                  value={labeler}
                  onChange={(e) => setLabeler(e.target.value)}
                />
              </Field>
            </div>
            {progress && (
              <StatusBadge
                tone="info"
                icon={false}
                label={`${progress.labeled} / ${progress.total_parts} labeled`}
              />
            )}
          </div>
        }
      />

      {error && <ErrorState title="Labeling error" message={error} />}

      {loading ? (
        <div className="flex justify-center py-24">
          <Spinner />
        </div>
      ) : parts.length === 0 ? (
        <EmptyState
          icon={Tags}
          title="No parts in the corpus queue"
          description="Seed the corpus or check that the labeling backend is running."
          action={
            <Button variant="secondary" onClick={() => void loadQueue()}>
              Reload queue
            </Button>
          }
        />
      ) : done ? (
        <EmptyState
          icon={Tags}
          title="Queue complete for this labeler"
          description="You've labeled every unlabeled part in the queue."
          action={
            <Button onClick={() => void loadQueue()}>
              Reload unlabeled queue
            </Button>
          }
        />
      ) : (
        <div className="flex flex-col gap-6 lg:flex-row">
          {/* Left ~70%: STL viewer */}
          <div className="h-[55vh] w-full overflow-hidden lg:h-auto lg:w-[70%]">
            {current && <CorpusViewer partId={current.part_id} />}
          </div>

          {/* Right ~30%: metadata + controls */}
          <div className="flex w-full flex-col gap-4 lg:w-[30%]">
            <Card>
              <CardContent compact>
                <p
                  className="truncate text-sm font-semibold text-foreground"
                  title={current?.filename ?? ""}
                >
                  {current?.filename ?? current?.part_id}
                </p>
                <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <dt>Dataset</dt>
                  <dd className="text-right text-foreground">
                    {current?.dataset ?? "—"}
                  </dd>
                  <dt>License</dt>
                  <dd className="text-right text-foreground">
                    {current?.license ?? "—"}
                  </dd>
                  <dt>Faces</dt>
                  <dd className="num text-right text-foreground">
                    {current?.n_faces?.toLocaleString() ?? "—"}
                  </dd>
                  <dt>Volume (cm³)</dt>
                  <dd className="num text-right text-foreground">
                    {current?.volume_cm3 ?? "—"}
                  </dd>
                  <dt>BBox (mm)</dt>
                  <dd className="num text-right text-foreground">
                    {current?.bbox_mm ? current.bbox_mm.join(" × ") : "—"}
                  </dd>
                  <dt>Watertight</dt>
                  <dd className="text-right text-foreground">
                    {current?.watertight == null
                      ? "—"
                      : current.watertight
                        ? "yes"
                        : "no"}
                  </dd>
                </dl>
                {current?.process_family_guess && (
                  <p className="mt-3 rounded-[var(--radius)] border border-warn-border bg-warn-bg px-2 py-1 text-[11px] text-warn">
                    Unverified heuristic guess:{" "}
                    <span className="font-semibold">
                      {current.process_family_guess}
                    </span>{" "}
                    — NOT a label, shown for context only.
                  </p>
                )}
              </CardContent>
            </Card>

            {/* Ontology buttons */}
            <Card>
              <CardContent compact>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  True manufacturing method
                </p>
                <div className="grid grid-cols-1 gap-2">
                  {ONTOLOGY.map((o) => (
                    <Button
                      key={o.key}
                      variant="secondary"
                      disabled={saving}
                      onClick={() => void submitLabel(o.key)}
                      className="w-full justify-between"
                    >
                      <span>{o.text}</span>
                      <kbd className="rounded-sm bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                        {o.hot}
                      </kbd>
                    </Button>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Confidence + notes */}
            <Card>
              <CardContent compact className="space-y-3">
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Confidence
                  </p>
                  <div className="flex gap-2">
                    {(["low", "medium", "high"] as Confidence[]).map((c) => (
                      <Button
                        key={c}
                        type="button"
                        size="sm"
                        variant={confidence === c ? "primary" : "secondary"}
                        onClick={() => setConfidence(c)}
                        className="flex-1 capitalize"
                      >
                        {c}
                      </Button>
                    ))}
                  </div>
                </div>
                <Textarea
                  rows={2}
                  placeholder="Notes (optional)"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </CardContent>
            </Card>

            {/* Navigation */}
            <div className="flex items-center justify-between gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={goPrev}
                disabled={index === 0}
              >
                ← Prev
              </Button>
              <span className="num text-xs text-muted-foreground">
                {index + 1} / {parts.length} in queue
              </span>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" onClick={goNext}>
                  Skip (s)
                </Button>
                <Button variant="secondary" size="sm" onClick={goNext}>
                  Next →
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
