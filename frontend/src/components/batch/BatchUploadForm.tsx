"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { createBatch, createBatchS3 } from "@/lib/api/batch";

type InputMode = "zip" | "s3";

const MAX_FILE_SIZE = 5 * 1024 * 1024 * 1024; // 5 GB

export default function BatchUploadForm() {
  const router = useRouter();
  const [mode, setMode] = useState<InputMode>("zip");
  const [file, setFile] = useState<File | null>(null);
  const [manifest, setManifest] = useState<File | null>(null);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [concurrencyLimit, setConcurrencyLimit] = useState(10);
  const [s3Bucket, setS3Bucket] = useState("");
  const [s3Prefix, setS3Prefix] = useState("");
  const [manifestUrl, setManifestUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);

  const handleFileDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) {
      if (!dropped.name.toLowerCase().endsWith(".zip")) {
        toast.error("Only .zip files are accepted");
        return;
      }
      if (dropped.size > MAX_FILE_SIZE) {
        toast.error("File exceeds 5 GB limit");
        return;
      }
      setFile(dropped);
    }
  }, []);

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = e.target.files?.[0];
      if (selected) {
        if (selected.size > MAX_FILE_SIZE) {
          toast.error("File exceeds 5 GB limit");
          return;
        }
        setFile(selected);
      }
    },
    [],
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setUploading(true);

    try {
      let result;
      if (mode === "zip") {
        if (!file) {
          toast.error("Please select a ZIP file");
          setUploading(false);
          return;
        }
        result = await createBatch(file, {
          webhookUrl: webhookUrl || undefined,
          manifest: manifest || undefined,
          concurrencyLimit,
        });
      } else {
        if (!s3Bucket || !s3Prefix) {
          toast.error("S3 bucket and prefix are required");
          setUploading(false);
          return;
        }
        result = await createBatchS3({
          s3Bucket,
          s3Prefix,
          manifestUrl: manifestUrl || undefined,
          webhookUrl: webhookUrl || undefined,
          concurrencyLimit,
        });
      }

      toast.success("Batch created");
      router.push(`/batch/${result.batch_id}`);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to create batch",
      );
    } finally {
      setUploading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* Mode toggle */}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setMode("zip")}
          className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
            mode === "zip"
              ? "bg-blue-600 text-white"
              : "bg-gray-100 text-gray-700 hover:bg-gray-200"
          }`}
        >
          ZIP Upload
        </button>
        <button
          type="button"
          onClick={() => setMode("s3")}
          className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
            mode === "s3"
              ? "bg-blue-600 text-white"
              : "bg-gray-100 text-gray-700 hover:bg-gray-200"
          }`}
        >
          S3 Reference
        </button>
      </div>

      {/* ZIP mode */}
      {mode === "zip" && (
        <div className="space-y-4">
          {/* Drop zone */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragOver(true);
            }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={handleFileDrop}
            className={`rounded-xl border-2 border-dashed p-8 text-center transition-all ${
              isDragOver
                ? "border-blue-500 bg-blue-50"
                : "border-gray-300 hover:border-gray-400"
            } ${uploading ? "pointer-events-none opacity-50" : "cursor-pointer"}`}
          >
            <input
              type="file"
              accept=".zip"
              onChange={handleFileInput}
              className="hidden"
              id="batch-zip-upload"
              disabled={uploading}
            />
            <label htmlFor="batch-zip-upload" className="cursor-pointer">
              <p className="text-lg font-semibold text-gray-700">
                {file ? file.name : "Drop your ZIP file here"}
              </p>
              <p className="mt-1 text-sm text-gray-500">
                {file
                  ? `${(file.size / 1024 / 1024).toFixed(1)} MB`
                  : "or click to browse. Max 5 GB."}
              </p>
            </label>
          </div>

          {/* Optional manifest */}
          <div>
            <label className="block text-sm font-medium text-gray-700">
              CSV Manifest (optional)
            </label>
            <input
              type="file"
              accept=".csv"
              onChange={(e) => setManifest(e.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-sm text-gray-500 file:mr-4 file:rounded file:border-0 file:bg-gray-100 file:px-4 file:py-2 file:text-sm file:font-medium hover:file:bg-gray-200"
              disabled={uploading}
            />
          </div>
        </div>
      )}

      {/* S3 mode */}
      {mode === "s3" && (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">
              S3 Bucket <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={s3Bucket}
              onChange={(e) => setS3Bucket(e.target.value)}
              placeholder="my-cad-files-bucket"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              disabled={uploading}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              S3 Prefix <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={s3Prefix}
              onChange={(e) => setS3Prefix(e.target.value)}
              placeholder="batches/2024-01/"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              disabled={uploading}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">
              Manifest URL (optional)
            </label>
            <input
              type="text"
              value={manifestUrl}
              onChange={(e) => setManifestUrl(e.target.value)}
              placeholder="https://..."
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              disabled={uploading}
            />
          </div>
        </div>
      )}

      {/* Shared options */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700">
            Webhook URL (optional)
          </label>
          <input
            type="url"
            value={webhookUrl}
            onChange={(e) => setWebhookUrl(e.target.value)}
            placeholder="https://..."
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            disabled={uploading}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">
            Concurrency Limit
          </label>
          <input
            type="number"
            min={1}
            max={100}
            value={concurrencyLimit}
            onChange={(e) =>
              setConcurrencyLimit(
                Math.max(1, Math.min(100, Number(e.target.value) || 10)),
              )
            }
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            disabled={uploading}
          />
        </div>
      </div>

      {/* Submit */}
      <button
        type="submit"
        disabled={uploading || (mode === "zip" && !file)}
        className="w-full rounded-md bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {uploading ? "Uploading..." : "Start Batch"}
      </button>
    </form>
  );
}
