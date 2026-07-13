"use client";

import { useCallback, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import {
  BatchApiError,
  createBatch,
  type BatchCreateResponse,
} from "@/lib/api/batch";
import { Dropzone } from "@/components/ui/dropzone";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  releaseSingleFlight,
  tryAcquireSingleFlight,
} from "@/lib/single-flight";

const MAX_FILE_SIZE = 5 * 1024 * 1024 * 1024; // 5 GB

export default function BatchUploadForm() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [manifest, setManifest] = useState<File | null>(null);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [concurrencyLimit, setConcurrencyLimit] = useState(10);
  const [uploading, setUploading] = useState(false);
  const [acceptedFailure, setAcceptedFailure] = useState<{
    batch: BatchCreateResponse;
    message: string;
  } | null>(null);
  const submissionLockRef = useRef(false);

  const handleFiles = useCallback((files: File[]) => {
    const dropped = files[0];
    if (!dropped) return;
    if (!dropped.name.toLowerCase().endsWith(".zip")) {
      toast.error("Only .zip files are accepted");
      return;
    }
    if (dropped.size > MAX_FILE_SIZE) {
      toast.error("File exceeds 5 GB limit");
      return;
    }
    setFile(dropped);
    setAcceptedFailure(null);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      toast.error("Please select a ZIP file");
      return;
    }
    if (!tryAcquireSingleFlight(submissionLockRef)) return;
    setUploading(true);

    try {
      const result = await createBatch(file, {
        webhookUrl: webhookUrl || undefined,
        manifest: manifest || undefined,
        concurrencyLimit,
      });

      toast.success("Batch created");
      setAcceptedFailure(null);
      router.push(`/batch/${result.batch_id}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to create batch";
      if (err instanceof BatchApiError && err.acceptedBatch) {
        setAcceptedFailure({ batch: err.acceptedBatch, message });
      }
      toast.error(message);
    } finally {
      releaseSingleFlight(submissionLockRef);
      setUploading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="space-y-4">
        <Dropzone
          accept=".zip"
          onFiles={handleFiles}
          isLoading={uploading}
          hint={
            file
              ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB`
              : "ZIP archive up to 5 GB"
          }
        />
        {acceptedFailure && (
          <div
            role="alert"
            className="space-y-3 rounded-[var(--radius)] border border-fail-border bg-fail-bg p-4 text-sm"
          >
            <div className="flex items-start gap-3">
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-fail" />
              <div className="min-w-0 space-y-1">
                <p className="font-semibold text-foreground">Accepted batch is durably failed</p>
                <p className="text-fail">{acceptedFailure.message}</p>
                <p className="text-muted-foreground">
                  The selected ZIP is still here. Inspect the failed record or retry it explicitly;
                  the failed batch will not process in the background.
                </p>
              </div>
            </div>
            <Button asChild type="button" variant="secondary" size="sm">
              <Link href={`/batch/${acceptedFailure.batch.batch_id}`}>
                Inspect failed batch
              </Link>
            </Button>
          </div>
        )}
        <Field label="CSV manifest (optional)" htmlFor="batch-csv-manifest">
          <Input
            id="batch-csv-manifest"
            type="file"
            accept=".csv"
            onChange={(e) => setManifest(e.target.files?.[0] ?? null)}
            disabled={uploading}
            className="h-auto py-1.5 text-muted-foreground file:mr-3 file:rounded-sm file:border-0 file:bg-muted file:px-3 file:py-1 file:text-sm file:font-medium"
          />
        </Field>
      </div>

      {/* Shared options */}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Webhook URL (optional)" htmlFor="batch-webhook-url">
          <Input
            id="batch-webhook-url"
            type="url"
            value={webhookUrl}
            onChange={(e) => setWebhookUrl(e.target.value)}
            placeholder="https://..."
            disabled={uploading}
          />
        </Field>
        <Field label="Concurrency limit" htmlFor="batch-concurrency-limit">
          <Input
            id="batch-concurrency-limit"
            type="number"
            min={1}
            max={100}
            value={concurrencyLimit}
            onChange={(e) =>
              setConcurrencyLimit(
                Math.max(1, Math.min(100, Number(e.target.value) || 10)),
              )
            }
            disabled={uploading}
            className="num"
          />
        </Field>
      </div>

      <Button
        type="submit"
        loading={uploading}
        disabled={uploading || !file}
        className="w-full"
      >
        {uploading
          ? "Uploading…"
          : acceptedFailure
            ? "Retry this ZIP"
            : "Start batch"}
      </Button>
    </form>
  );
}
