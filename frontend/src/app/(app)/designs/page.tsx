"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Box,
  CheckCircle2,
  Download,
  Layers3,
  Loader2,
  PanelTop,
  PencilLine,
  RefreshCw,
  ShieldCheck,
  Square,
  Trash2,
  TriangleAlert,
} from "lucide-react";

import CadViewer from "@/components/ui/cad-viewer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/ui/page-header";
import { Textarea } from "@/components/ui/textarea";
import {
  DEFAULT_DESIGN_FORM,
  buildDesignPlan,
  formFromDesign,
  formFromPlan,
  resolveViewedRevisionNo,
  validateDesignForm,
  type DesignForm,
  type TemplateKind,
} from "@/lib/design-plan";
import {
  archiveDesign,
  createDesign,
  createDesignRevision,
  designRevisionPreviewUrl,
  designRevisionStepUrl,
  interpretDesignPrompt,
  listDesigns,
  listDesignRevisions,
  type Design,
  type DesignRevision,
} from "@/lib/designs-api";
import { cn } from "@/lib/utils";
import {
  releaseSingleFlight,
  tryAcquireSingleFlight,
} from "@/lib/single-flight";

const TEMPLATES: Array<{
  kind: TemplateKind;
  name: string;
  description: string;
  icon: typeof Square;
}> = [
  {
    kind: "plate",
    name: "Mounting plate",
    description: "Flat stock with optional corner holes",
    icon: Square,
  },
  {
    kind: "bracket",
    name: "L bracket",
    description: "Joined base and upright flange",
    icon: Layers3,
  },
  {
    kind: "enclosure",
    name: "Open enclosure",
    description: "Base and four walls, open at the top",
    icon: PanelTop,
  },
];

function statusBadge(design: Design) {
  if (design.status === "ready") {
    return (
      <Badge className="border-pass-border bg-pass-bg text-pass">
        <CheckCircle2 className="size-3" /> Ready
      </Badge>
    );
  }
  if (design.status === "failed") {
    return (
      <Badge className="border-fail-border bg-fail-bg text-fail">
        <TriangleAlert className="size-3" /> Needs attention
      </Badge>
    );
  }
  return (
    <Badge variant="primary">
      <Loader2 className="size-3 animate-spin" /> Generating
    </Badge>
  );
}

function NumberField({
  id,
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <Label htmlFor={id}>{label}</Label>
        <span className="num text-[10px] text-subtle-foreground">mm</span>
      </div>
      <Input
        id={id}
        type="number"
        inputMode="decimal"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </div>
  );
}

function formatBytes(value: number | null | undefined): string {
  if (!value) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DesignsPage() {
  const [designs, setDesigns] = useState<Design[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [revisionHistory, setRevisionHistory] = useState<DesignRevision[]>([]);
  const [viewedRevisionNo, setViewedRevisionNo] = useState<number | null>(null);
  const [form, setForm] = useState<DesignForm>({ ...DEFAULT_DESIGN_FORM });
  const [description, setDescription] = useState("");
  const [interpreting, setInterpreting] = useState(false);
  const [interpretation, setInterpretation] = useState<{
    tone: "ready" | "needs_input";
    message: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const revisionDesignIdRef = useRef<string | null>(null);
  const submissionLockRef = useRef(false);

  const selected = useMemo(
    () => designs.find((design) => design.id === selectedId) ?? designs[0] ?? null,
    [designs, selectedId],
  );

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const next = await listDesigns();
      setDesigns(next);
      setSelectedId((current) =>
        current && next.some((design) => design.id === current)
          ? current
          : (next[0]?.id ?? null),
      );
      setError(null);
    } catch (caught) {
      if (!quiet) {
        setError(caught instanceof Error ? caught.message : "Could not load designs.");
      }
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const hasActiveGeneration = designs.some(
    (design) => design.status === "generating",
  );
  useEffect(() => {
    if (!hasActiveGeneration) return;
    const timer = window.setInterval(() => void refresh(true), 1500);
    return () => window.clearInterval(timer);
  }, [hasActiveGeneration, refresh]);

  useEffect(() => {
    if (!selected) {
      setRevisionHistory([]);
      setViewedRevisionNo(null);
      revisionDesignIdRef.current = null;
      return;
    }
    const designChanged = revisionDesignIdRef.current !== selected.id;
    revisionDesignIdRef.current = selected.id;
    let cancelled = false;
    void listDesignRevisions(selected.id).then(
      (revisions) => {
        if (cancelled) return;
        setRevisionHistory(revisions);
        setViewedRevisionNo((current) =>
          resolveViewedRevisionNo(
            current,
            revisions,
            selected.current_revision,
            designChanged,
          ),
        );
      },
      () => {
        if (!cancelled) {
          setRevisionHistory(selected.revision ? [selected.revision] : []);
          setViewedRevisionNo(selected.current_revision);
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const update = <K extends keyof DesignForm,>(key: K, value: DesignForm[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const chooseTemplate = (kind: TemplateKind) => {
    const template = TEMPLATES.find((item) => item.kind === kind)!;
    setForm((current) => ({
      ...current,
      kind,
      name: editingId ? current.name : template.name,
    }));
  };

  const interpret = async () => {
    if (!description.trim()) {
      setError("Describe the starting shape and its dimensions first.");
      return;
    }
    setInterpreting(true);
    setError(null);
    try {
      const result = await interpretDesignPrompt(description.trim());
      if (result.status === "ready") {
        setForm(formFromPlan(result.plan, result.name));
        setInterpretation({
          tone: "ready",
          message: `${result.message} ${result.assumptions.join(" ")}`,
        });
      } else {
        setForm((current) => ({
          ...current,
          ...(result.kind ? { kind: result.kind } : {}),
          ...(result.prefill.width_mm !== undefined ? { width: result.prefill.width_mm } : {}),
          ...(result.prefill.depth_mm !== undefined ? { depth: result.prefill.depth_mm } : {}),
          ...(result.prefill.height_mm !== undefined ? { height: result.prefill.height_mm } : {}),
          ...(result.prefill.thickness_mm !== undefined ? { thickness: result.prefill.thickness_mm } : {}),
          ...(result.prefill.wall_thickness_mm !== undefined
            ? { wallThickness: result.prefill.wall_thickness_mm }
            : {}),
        }));
        setInterpretation({ tone: "needs_input", message: result.message });
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not interpret the description.");
    } finally {
      setInterpreting(false);
    }
  };

  const cancelRevision = () => {
    setEditingId(null);
    setForm({ ...DEFAULT_DESIGN_FORM });
    setError(null);
  };

  const beginRevision = (design: Design) => {
    setEditingId(design.id);
    setSelectedId(design.id);
    setForm(formFromDesign(design));
    setError(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const submit = async () => {
    const problem = validateDesignForm(form);
    if (problem) {
      setError(problem);
      return;
    }
    if (!tryAcquireSingleFlight(submissionLockRef)) return;
    setSubmitting(true);
    setError(null);
    try {
      const plan = buildDesignPlan(form);
      const design = editingId
        ? await createDesignRevision(editingId, {
            plan,
            design_note: form.designNote || null,
          })
        : await createDesign({
            name: form.name,
            plan,
            design_note: form.designNote || null,
          });
      setDesigns((current) => [
        design,
        ...current.filter((item) => item.id !== design.id),
      ]);
      setSelectedId(design.id);
      setViewedRevisionNo(design.current_revision);
      setEditingId(null);
      setForm({ ...DEFAULT_DESIGN_FORM });
      setDescription("");
      setInterpretation(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not start generation.");
    } finally {
      releaseSingleFlight(submissionLockRef);
      setSubmitting(false);
    }
  };

  const remove = async (design: Design) => {
    if (!window.confirm(`Archive “${design.name}”? Its audit evidence will be retained.`)) {
      return;
    }
    try {
      await archiveDesign(design.id);
      setDesigns((current) => current.filter((item) => item.id !== design.id));
      setSelectedId(null);
      if (editingId === design.id) cancelRevision();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not archive design.");
    }
  };

  const viewedRevision = selected
    ? revisionHistory.find((revision) => revision.number === viewedRevisionNo) ?? selected.revision
    : null;
  const previewUrl = selected && viewedRevision
    ? designRevisionPreviewUrl(selected.id, viewedRevision)
    : null;
  const geometry = viewedRevision?.geometry;

  return (
    <div className="space-y-6">
      <PageHeader
        title="ProofShape Design Studio"
        badge={<Badge variant="outline">Safe parametric CAD</Badge>}
        subtitle="Create real, revisioned CAD and carry it directly into manufacturing verification."
        actions={
          <Button variant="secondary" onClick={() => void refresh()} loading={loading}>
            <RefreshCw /> Refresh
          </Button>
        }
      />

      <div className="flex items-start gap-3 rounded-[var(--radius)] border border-accent-subtle-border bg-accent-subtle px-4 py-3 text-sm text-accent-text">
        <ShieldCheck className="mt-0.5 size-4 shrink-0" />
        <p>
          Geometry is built from validated operations in an isolated CAD process. No generated
          code, fake preview, or third-party model is involved in this release.
        </p>
      </div>

      {error && (
        <div role="alert" className="flex items-start gap-3 rounded-[var(--radius)] border border-fail-border bg-fail-bg px-4 py-3 text-sm text-fail">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />
          <span className="flex-1">{error}</span>
          <button type="button" className="font-medium underline" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle>{editingId ? `Create revision ${selected?.current_revision ? selected.current_revision + 1 : ""}` : "Start a design"}</CardTitle>
            <CardDescription>
              {editingId
                ? "Change dimensions below. The current revision remains immutable."
                : "Choose a proven starting shape, then enter dimensions in millimetres."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-3 rounded-[var(--radius)] border border-accent-subtle-border bg-accent-subtle p-3">
              <div className="space-y-1">
                <Label htmlFor="design-description" className="text-accent-text">
                  Describe a starting shape
                </Label>
                <p className="text-[11px] leading-4 text-muted-foreground">
                  Try “80 × 50 × 6 mm plate with four 6 mm corner holes.”
                </p>
              </div>
              <Textarea
                id="design-description"
                value={description}
                maxLength={500}
                rows={3}
                placeholder="Plate, L bracket, or open enclosure with explicit mm dimensions…"
                onChange={(event) => setDescription(event.target.value)}
              />
              <div className="flex items-center gap-3">
                <Button variant="secondary" size="sm" loading={interpreting} onClick={() => void interpret()}>
                  Interpret safely
                </Button>
                <span className="text-[10px] leading-4 text-subtle-foreground">
                  local rules · no AI egress · review required
                </span>
              </div>
              {interpretation && (
                <p
                  role="status"
                  className={cn(
                    "rounded-[var(--radius-sm)] border px-3 py-2 text-xs leading-5",
                    interpretation.tone === "ready"
                      ? "border-pass-border bg-pass-bg text-pass"
                      : "border-warn-border bg-warn-bg text-warn",
                  )}
                >
                  {interpretation.message}
                </p>
              )}
            </div>

            <div className="grid grid-cols-3 gap-2">
              {TEMPLATES.map((template) => {
                const Icon = template.icon;
                const active = form.kind === template.kind;
                return (
                  <button
                    key={template.kind}
                    type="button"
                    title={template.description}
                    onClick={() => chooseTemplate(template.kind)}
                    className={cn(
                      "flex min-h-24 flex-col items-center justify-center gap-2 rounded-[var(--radius)] border px-2 py-3 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      active
                        ? "border-primary bg-accent-subtle text-foreground"
                        : "border-border bg-card hover:bg-muted",
                    )}
                  >
                    <Icon className={cn("size-5", active ? "text-primary" : "text-muted-foreground")} />
                    <span className="text-xs font-medium leading-tight">{template.name}</span>
                  </button>
                );
              })}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="design-name">Design name</Label>
              <Input
                id="design-name"
                value={form.name}
                disabled={Boolean(editingId)}
                maxLength={120}
                onChange={(event) => update("name", event.target.value)}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <NumberField id="design-width" label="Width" value={form.width} min={form.kind === "enclosure" ? 20 : 10} max={1000} onChange={(value) => update("width", value)} />
              <NumberField id="design-depth" label="Depth" value={form.depth} min={form.kind === "enclosure" ? 20 : 10} max={1000} onChange={(value) => update("depth", value)} />
              {form.kind !== "plate" && (
                <NumberField id="design-height" label="Height" value={form.height} min={10} max={1000} onChange={(value) => update("height", value)} />
              )}
              {form.kind === "enclosure" ? (
                <NumberField id="design-wall" label="Wall" value={form.wallThickness} min={0.5} max={50} step={0.5} onChange={(value) => update("wallThickness", value)} />
              ) : (
                <NumberField id="design-thickness" label="Thickness" value={form.thickness} min={0.5} max={100} step={0.5} onChange={(value) => update("thickness", value)} />
              )}
            </div>

            {form.kind === "plate" && (
              <div className="space-y-3 rounded-[var(--radius)] border border-border bg-muted/40 p-3">
                <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-foreground">
                  <input
                    type="checkbox"
                    checked={form.fourCornerHoles}
                    onChange={(event) => update("fourCornerHoles", event.target.checked)}
                    className="size-4 accent-primary"
                  />
                  Add four corner holes
                </label>
                {form.fourCornerHoles && (
                  <div className="grid grid-cols-2 gap-3">
                    <NumberField id="hole-diameter" label="Diameter" value={form.holeDiameter} min={1} max={100} step={0.5} onChange={(value) => update("holeDiameter", value)} />
                    <NumberField id="hole-inset" label="Edge inset" value={form.holeInset} min={2} max={500} step={0.5} onChange={(value) => update("holeInset", value)} />
                  </div>
                )}
              </div>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="design-note">Design note <span className="font-normal text-subtle-foreground">(optional)</span></Label>
              <Textarea
                id="design-note"
                maxLength={1000}
                value={form.designNote}
                placeholder="Purpose, fit, or revision context for your team. This note does not change geometry."
                onChange={(event) => update("designNote", event.target.value)}
              />
            </div>

            <div className="flex gap-2">
              <Button className="flex-1" onClick={() => void submit()} loading={submitting}>
                {editingId ? "Generate new revision" : "Generate design"}
                {!submitting && <ArrowRight />}
              </Button>
              {editingId && (
                <Button variant="secondary" onClick={cancelRevision} disabled={submitting}>
                  Cancel
                </Button>
              )}
            </div>
            <p className="text-xs leading-5 text-muted-foreground">
              Need a shape outside these templates? Keep the design in your CAD tool for now and
              upload it to Verify. Unsupported geometry is never approximated here.
            </p>
          </CardContent>
        </Card>

        <div className="min-w-0 space-y-4">
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <div>
                <CardTitle>Your designs</CardTitle>
                <CardDescription>Organization-owned projects, newest revision first.</CardDescription>
              </div>
              <Badge variant="neutral">{designs.length}</Badge>
            </CardHeader>
            <CardContent compact>
              {loading && designs.length === 0 ? (
                <div className="flex h-28 items-center justify-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" /> Loading designs…
                </div>
              ) : designs.length === 0 ? (
                <EmptyState
                  icon={Box}
                  title="No designs yet"
                  description="The mounting plate example is ready. Confirm its dimensions and generate your first real CAD revision."
                  className="py-8"
                />
              ) : (
                <div className="grid gap-2 md:grid-cols-2 2xl:grid-cols-3">
                  {designs.map((design) => (
                    <button
                      key={design.id}
                      type="button"
                      onClick={() => setSelectedId(design.id)}
                      className={cn(
                        "rounded-[var(--radius)] border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        selected?.id === design.id
                          ? "border-primary bg-accent-subtle"
                          : "border-border bg-card hover:bg-muted",
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="truncate text-sm font-semibold text-foreground">{design.name}</span>
                        {statusBadge(design)}
                      </div>
                      <p className="num mt-2 text-[11px] text-muted-foreground">
                        {design.revision?.plan.kind ?? "design"} · revision {design.current_revision}
                      </p>
                    </button>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {selected && (
            <Card>
              <CardHeader className="flex-row items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <CardTitle className="truncate">{selected.name}</CardTitle>
                    {statusBadge(selected)}
                  </div>
                  <CardDescription className="mt-1">
                    Viewing revision {viewedRevision?.number ?? selected.current_revision}
                    {viewedRevision?.number !== selected.current_revision
                      ? ` · current is ${selected.current_revision}`
                      : " · current"}
                    {` · ${viewedRevision?.generation_engine ?? "waiting for engine"}`}
                  </CardDescription>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button variant="secondary" size="sm" onClick={() => beginRevision(selected)} disabled={selected.status === "generating"}>
                    <PencilLine /> Revise
                  </Button>
                  <Button variant="ghost" size="icon" title="Archive design" aria-label="Archive design" onClick={() => void remove(selected)} disabled={selected.status === "generating"}>
                    <Trash2 />
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {previewUrl ? (
                  <CadViewer src={previewUrl} surface="instrument" className="h-[460px]" />
                ) : viewedRevision?.status === "failed" ? (
                  <div className="flex h-[360px] flex-col items-center justify-center rounded-[var(--radius)] border border-fail-border bg-fail-bg px-6 text-center">
                    <TriangleAlert className="mb-3 size-8 text-fail" />
                    <p className="font-semibold text-foreground">This revision was not generated</p>
                    <p className="mt-1 max-w-md text-sm text-muted-foreground">
                      {viewedRevision.error?.message ?? "Generation failed without an artifact. Revise the dimensions and retry."}
                    </p>
                    <Button className="mt-4" variant="secondary" onClick={() => beginRevision(selected)}>
                      <PencilLine /> Revise and retry
                    </Button>
                  </div>
                ) : (
                  <div className="flex h-[360px] flex-col items-center justify-center rounded-[var(--radius)] border border-border bg-muted text-center">
                    <Loader2 className="mb-3 size-7 animate-spin text-primary" />
                    <p className="font-semibold text-foreground">Generating real CAD</p>
                    <p className="mt-1 text-sm text-muted-foreground">You can leave this page. The revision and job are durable.</p>
                  </div>
                )}

                {geometry && (
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <div className="rounded-[var(--radius)] border border-border bg-muted p-3">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Envelope</p>
                      <p className="num mt-1 text-sm font-medium text-foreground">{geometry.bbox_mm.map((value) => value.toFixed(1)).join(" × ")} mm</p>
                    </div>
                    <div className="rounded-[var(--radius)] border border-border bg-muted p-3">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Volume</p>
                      <p className="num mt-1 text-sm font-medium text-foreground">{geometry.volume_cm3.toFixed(2)} cm³</p>
                    </div>
                    <div className="rounded-[var(--radius)] border border-border bg-muted p-3">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">STEP</p>
                      <p className="num mt-1 text-sm font-medium text-foreground">{formatBytes(viewedRevision?.step_size_bytes)}</p>
                    </div>
                    <div className="rounded-[var(--radius)] border border-border bg-muted p-3">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Evidence hash</p>
                      <p className="num mt-1 truncate text-sm font-medium text-foreground" title={viewedRevision?.geometry_hash ?? undefined}>{viewedRevision?.geometry_hash?.slice(0, 12) ?? "—"}</p>
                    </div>
                  </div>
                )}

                {revisionHistory.length > 0 && (
                  <div className="space-y-2 border-t border-border pt-4">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Revision history
                      </p>
                      <p className="text-xs text-subtle-foreground">
                        Older evidence remains downloadable and verifiable.
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {revisionHistory.map((revision) => (
                        <button
                          key={revision.id}
                          type="button"
                          onClick={() => setViewedRevisionNo(revision.number)}
                          className={cn(
                            "flex items-center gap-2 rounded-[var(--radius-sm)] border px-3 py-2 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                            viewedRevision?.number === revision.number
                              ? "border-primary bg-accent-subtle text-foreground"
                              : "border-border bg-card text-muted-foreground hover:bg-muted",
                          )}
                        >
                          <span className="num font-semibold">R{revision.number}</span>
                          <span>{revision.status}</span>
                          {revision.number === selected.current_revision && (
                            <span className="text-primary">current</span>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {viewedRevision?.status === "ready" && (
                  <div className="flex flex-col gap-2 border-t border-border pt-4 sm:flex-row">
                    <Button asChild variant="secondary">
                      <a href={designRevisionStepUrl(selected.id, viewedRevision.number)}>
                        <Download /> Download R{viewedRevision.number} STEP
                      </a>
                    </Button>
                    <Button asChild>
                      <Link href={`/verify?design=${encodeURIComponent(selected.id)}&revision=${viewedRevision.number}`}>
                        Verify revision {viewedRevision.number} <ArrowRight />
                      </Link>
                    </Button>
                    <p className="self-center text-xs text-muted-foreground sm:ml-2">
                      Opens this exact revision in the existing DFM and should-cost walk.
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
