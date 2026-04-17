"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import ImageUploader from "./components/ImageUploader";
import ReconstructionProgress from "./components/ReconstructionProgress";
import MeshPreview from "./components/MeshPreview";
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
  const [reconstructionResult, setReconstructionResult] = useState<Record<string, unknown> | null>(null);
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
      const msg = err instanceof Error ? err.message : "Failed to submit reconstruction";
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
    <main className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Image to 3D</h1>
        <p className="mt-1 text-sm text-gray-500">
          Reconstruct 3D geometry from photographs
        </p>
      </div>

      {/* Error banner */}
      {error && step === "upload" && (
        <div className="rounded-md border border-red-200 bg-red-50 p-4">
          <p className="text-sm text-red-700">{error}</p>
          <button
            type="button"
            onClick={handleReset}
            className="mt-2 text-sm font-medium text-red-700 underline hover:text-red-900"
          >
            Try Again
          </button>
        </div>
      )}

      {/* Step: Upload */}
      {step === "upload" && (
        <section className="rounded-md border p-6">
          <h2 className="mb-4 text-lg font-medium text-gray-700">
            Upload Images
          </h2>
          <ImageUploader onUpload={handleUpload} disabled={submitting} />
          {submitting && (
            <p className="mt-3 text-center text-sm text-gray-500">
              Submitting...
            </p>
          )}
        </section>
      )}

      {/* Step: Processing */}
      {step === "processing" && jobId && (
        <section className="rounded-md border p-6">
          <ReconstructionProgress
            jobId={jobId}
            estimatedSeconds={estimatedSeconds}
            onComplete={handleComplete}
            onError={handleError}
          />
        </section>
      )}

      {/* Step: Preview */}
      {step === "preview" && jobId && (
        <section className="rounded-md border p-6">
          <MeshPreview
            meshUrl={getReconstructionMeshUrl(jobId)}
            confidenceScore={confidenceScore}
            confidenceLevel={confidenceLevel}
            analysisUrl={analysisId ? `/analyses/${analysisId}` : "#"}
            faceCount={faceCount}
          />

          <div className="mt-6 flex items-center justify-between">
            <button
              type="button"
              onClick={handleReset}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Start New Reconstruction
            </button>
            {analysisId && (
              <button
                type="button"
                onClick={() => router.push(`/analyses/${analysisId}`)}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
              >
                Go to Analysis
              </button>
            )}
          </div>
        </section>
      )}
    </main>
  );
}
