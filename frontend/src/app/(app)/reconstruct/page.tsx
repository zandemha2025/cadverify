"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import ImageUploader from "./components/ImageUploader";
import ReconstructionProgress from "./components/ReconstructionProgress";
import MeshPreview from "./components/MeshPreview";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { reconstructionViewModel } from "./reconstruction-result";
import { reconstructionSubmissionGate } from "./reconstruction-capability";
import {
  reconstructionAttempt,
  type ReconstructionAttempt,
} from "./reconstruction-attempt";
import { createReconstructionSubmissionId } from "@/lib/reconstruction-id";
import {
  submitReconstruction,
  getReconstructionCapability,
  getReconstructionMeshUrl,
  type ReconstructionCapability,
  type ReconstructionJobResult,
} from "@/lib/api";

type Step = "upload" | "processing" | "preview" | "complete";

export default function ReconstructPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("upload");
  const [jobId, setJobId] = useState<string | null>(null);
  const [estimatedSeconds, setEstimatedSeconds] = useState(30);
  const [reconstructionResult, setReconstructionResult] =
    useState<ReconstructionJobResult | null>(null);
  const [completionStatus, setCompletionStatus] = useState<
    "done" | "partial" | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [capability, setCapability] =
    useState<ReconstructionCapability | null>(null);
  const [capabilityError, setCapabilityError] = useState<string | null>(null);
  const [capabilityAttempt, setCapabilityAttempt] = useState(0);
  const [egressAcknowledged, setEgressAcknowledged] = useState(false);
  const submissionRef = useRef<ReconstructionAttempt | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setCapability(null);
    setCapabilityError(null);
    getReconstructionCapability(controller.signal)
      .then(setCapability)
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setCapabilityError(
          err instanceof Error
            ? err.message
            : "Could not load reconstruction availability",
        );
      });
    return () => controller.abort();
  }, [capabilityAttempt]);

  const handleUpload = async (files: File[]) => {
    const gate = reconstructionSubmissionGate(capability, egressAcknowledged);
    if (!gate.allowed) {
      setError(gate.reason);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const attempt = reconstructionAttempt(
        submissionRef.current,
        files,
        createReconstructionSubmissionId,
      );
      submissionRef.current = attempt;
      const res = await submitReconstruction(
        files,
        undefined,
        undefined,
        attempt.submissionId,
        egressAcknowledged,
      );
      setJobId(res.job_id);
      setEstimatedSeconds(res.estimated_seconds || 30);
      setStep("processing");
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Failed to submit reconstruction";
      setError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleComplete = (
    result: ReconstructionJobResult,
    terminalStatus: "done" | "partial",
  ) => {
    setReconstructionResult(result);
    setCompletionStatus(terminalStatus);
    setStep("preview");
    if (terminalStatus === "partial") {
      toast.warning(
        "Reconstruction completed with limited output. Review it carefully.",
      );
    }
  };

  const handleError = (msg: string) => {
    // The worker reached a real terminal failure. A human retry should create
    // a new job, unlike an ambiguous POST/network retry above.
    submissionRef.current = null;
    setError(msg);
    setStep("upload");
    toast.error(msg);
  };

  const handleReset = () => {
    setStep("upload");
    setJobId(null);
    setReconstructionResult(null);
    setCompletionStatus(null);
    setError(null);
    submissionRef.current = null;
  };

  const {
    confidencePercent: confidenceScore,
    confidenceLevel,
    analysisId,
    faceCount,
  } = reconstructionViewModel(reconstructionResult);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Image to 3D"
        subtitle="Create an estimated mesh from photographs when an approved backend is enabled."
        actions={
          step !== "upload" ? (
            <Button variant="secondary" onClick={handleReset}>
              New reconstruction
            </Button>
          ) : undefined
        }
      />

      {!capability && !capabilityError && (
        <Card className="mx-auto max-w-2xl" aria-busy="true">
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            Checking Image-to-3D availability…
          </CardContent>
        </Card>
      )}

      {capabilityError && (
        <div className="mx-auto max-w-2xl">
          <ErrorState
            title="Couldn’t load Image-to-3D availability"
            message={capabilityError}
            onRetry={() => setCapabilityAttempt((attempt) => attempt + 1)}
          />
        </div>
      )}

      {capability && !capability.available && (
        <Card className="mx-auto max-w-2xl">
          <CardHeader>
            <CardTitle>Image-to-3D is not enabled</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">{capability.message}</p>
            <p className="text-sm text-muted-foreground">
              No image has been uploaded or sent to a third party.
            </p>
            <Button onClick={() => router.push(capability.verify_path)}>
              Verify CAD instead
            </Button>
          </CardContent>
        </Card>
      )}

      {capability?.available && !capability.can_submit && (
        <Card className="mx-auto max-w-2xl">
          <CardHeader>
            <CardTitle>Image-to-3D is read-only for your account</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              An analyst role or higher is required to submit customer images.
              You can still review completed work available to your organization.
            </p>
            <Button onClick={() => router.push("/history")}>Review analyses</Button>
          </CardContent>
        </Card>
      )}

      {/* Error banner */}
      {capability?.available && capability.can_submit && error && step === "upload" && (
        <div className="mx-auto max-w-2xl">
          <ErrorState
            title="Reconstruction failed"
            message={error}
            onRetry={() => setError(null)}
          />
        </div>
      )}

      {/* Step: Upload */}
      {capability?.available && capability.can_submit && step === "upload" && (
        <Card className="mx-auto max-w-2xl">
          <CardHeader>
            <CardTitle>Upload images</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-[var(--radius)] border border-border bg-muted/40 p-3 text-sm text-muted-foreground">
              {capability.accuracy_notice}
            </div>
            {capability.requires_egress_acknowledgement && (
              <label className="flex min-h-11 items-start gap-3 rounded-[var(--radius)] border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-foreground">
                <input
                  type="checkbox"
                  className="mt-0.5 size-4"
                  checked={egressAcknowledged}
                  onChange={(event) =>
                    setEgressAcknowledged(event.target.checked)
                  }
                />
                <span>{capability.message} I approve this transfer.</span>
              </label>
            )}
            <ImageUploader
              onUpload={handleUpload}
              disabled={
                submitting ||
                (capability.requires_egress_acknowledgement &&
                  !egressAcknowledged)
              }
            />
            {submitting && (
              <p className="mt-3 text-center text-sm text-muted-foreground">
                Submitting…
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Step: Processing */}
      {capability?.available && capability.can_submit && step === "processing" && jobId && (
        <Card className="mx-auto max-w-2xl">
          <CardContent>
            <ReconstructionProgress
              jobId={jobId}
              estimatedSeconds={estimatedSeconds}
              onComplete={handleComplete}
              onError={handleError}
            />
          </CardContent>
        </Card>
      )}

      {/* Step: Preview */}
      {capability?.available && capability.can_submit && step === "preview" && jobId && (
        <Card>
          <CardContent>
            {completionStatus === "partial" && (
              <div className="mb-4 rounded-[var(--radius)] border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-foreground">
                This reconstruction completed with limited output. Review the mesh
                before using its analysis.
              </div>
            )}
            <MeshPreview
              meshUrl={getReconstructionMeshUrl(jobId)}
              confidenceScore={confidenceScore}
              confidenceLevel={confidenceLevel}
              analysisUrl={analysisId ? `/analyses/${analysisId}` : "#"}
              faceCount={faceCount}
            />

            <div className="mt-6 flex items-center justify-between">
              <Button variant="ghost" onClick={handleReset}>
                Start new reconstruction
              </Button>
              {analysisId && (
                <Button onClick={() => router.push(`/analyses/${analysisId}`)}>
                  Go to analysis
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
