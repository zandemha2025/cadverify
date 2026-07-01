"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import ImageUploader from "./components/ImageUploader";
import ReconstructionProgress from "./components/ReconstructionProgress";
import MeshPreview from "./components/MeshPreview";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import {
  submitReconstruction,
  getReconstructionMeshUrl,
} from "@/lib/api";

type Step = "upload" | "processing" | "preview" | "complete";

export default function ReconstructPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("upload");
  const [jobId, setJobId] = useState<string | null>(null);
  const [estimatedSeconds, setEstimatedSeconds] = useState(30);
  const [reconstructionResult, setReconstructionResult] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleUpload = async (files: File[]) => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await submitReconstruction(files);
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

  const handleComplete = (result: Record<string, unknown>) => {
    setReconstructionResult(result);
    setStep("preview");
  };

  const handleError = (msg: string) => {
    setError(msg);
    setStep("upload");
    toast.error(msg);
  };

  const handleReset = () => {
    setStep("upload");
    setJobId(null);
    setReconstructionResult(null);
    setError(null);
  };

  // Derive confidence level from score
  const confidenceScore = (reconstructionResult?.confidence_score as number) ?? 0;
  const confidenceLevel: "high" | "medium" | "low" =
    confidenceScore >= 80 ? "high" : confidenceScore >= 50 ? "medium" : "low";

  const analysisId = (reconstructionResult?.analysis_id as string) ?? "";
  const faceCount = (reconstructionResult?.face_count as number) ?? undefined;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Image to 3D"
        subtitle="Reconstruct 3D geometry from photographs."
        actions={
          step !== "upload" ? (
            <Button variant="secondary" onClick={handleReset}>
              New reconstruction
            </Button>
          ) : undefined
        }
      />

      {/* Error banner */}
      {error && step === "upload" && (
        <div className="mx-auto max-w-2xl">
          <ErrorState
            title="Reconstruction failed"
            message={error}
            onRetry={handleReset}
          />
        </div>
      )}

      {/* Step: Upload */}
      {step === "upload" && (
        <Card className="mx-auto max-w-2xl">
          <CardHeader>
            <CardTitle>Upload images</CardTitle>
          </CardHeader>
          <CardContent>
            <ImageUploader onUpload={handleUpload} disabled={submitting} />
            {submitting && (
              <p className="mt-3 text-center text-sm text-muted-foreground">
                Submitting…
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Step: Processing */}
      {step === "processing" && jobId && (
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
      {step === "preview" && jobId && (
        <Card>
          <CardContent>
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
