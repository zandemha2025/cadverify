"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { createBatch } from "@/lib/api/batch";
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
      router.push(`/batch/${result.batch_id}`);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to create batch",
      );
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
        <Field label="CSV manifest (optional)">
          <Input
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
        <Field label="Webhook URL (optional)">
          <Input
            type="url"
            value={webhookUrl}
            onChange={(e) => setWebhookUrl(e.target.value)}
            placeholder="https://..."
            disabled={uploading}
          />
        </Field>
        <Field label="Concurrency limit">
          <Input
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
        {uploading ? "Uploading…" : "Start batch"}
      </Button>
    </form>
  );
}
