"use client";

import { useCallback, useEffect, useState } from "react";
import { X } from "lucide-react";
import { Dropzone } from "@/components/ui/dropzone";
import { Button } from "@/components/ui/button";

interface ImageUploaderProps {
  onUpload: (files: File[]) => void;
  disabled: boolean;
}

const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];
const ACCEPTED_EXT = ".jpg,.jpeg,.png,.webp";
const MAX_FILES = 4;
const MAX_SIZE_BYTES = 20 * 1024 * 1024; // 20 MB

export default function ImageUploader({ onUpload, disabled }: ImageUploaderProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Generate preview object URLs when files change
  useEffect(() => {
    const urls = files.map((f) => URL.createObjectURL(f));
    setPreviews(urls);
    return () => urls.forEach((u) => URL.revokeObjectURL(u));
  }, [files]);

  const validate = useCallback(
    (incoming: File[]): File[] | null => {
      setError(null);
      const totalCount = files.length + incoming.length;
      if (totalCount > MAX_FILES) {
        setError(
          `Maximum ${MAX_FILES} images allowed. You have ${files.length}, tried to add ${incoming.length}.`,
        );
        return null;
      }
      for (const f of incoming) {
        if (!ACCEPTED_TYPES.includes(f.type)) {
          setError(`"${f.name}" is not a supported image type. Use JPEG, PNG, or WebP.`);
          return null;
        }
        if (f.size > MAX_SIZE_BYTES) {
          setError(`"${f.name}" exceeds the 20 MB limit.`);
          return null;
        }
      }
      return incoming;
    },
    [files.length],
  );

  const addFiles = useCallback(
    (incoming: File[]) => {
      const valid = validate(incoming);
      if (valid) setFiles((prev) => [...prev, ...valid]);
    },
    [validate],
  );

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
    setError(null);
  };

  return (
    <div className="space-y-4">
      <Dropzone
        accept={ACCEPTED_EXT}
        multiple
        onFiles={addFiles}
        disabled={disabled}
        hint="JPEG, PNG, or WebP · max 4 images, 20 MB each"
      />

      {error && (
        <p className="text-sm text-fail" role="alert">
          {error}
        </p>
      )}

      {/* Preview grid */}
      {files.length > 0 && (
        <div className="grid grid-cols-2 gap-3">
          {previews.map((src, i) => (
            <div
              key={`${files[i].name}-${i}`}
              className="relative overflow-hidden rounded-[var(--radius)] border border-border"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={src}
                alt={`Upload preview ${i + 1}`}
                className="h-32 w-full object-cover"
              />
              <Button
                type="button"
                variant="secondary"
                size="icon"
                onClick={() => removeFile(i)}
                aria-label={`Remove image ${i + 1}`}
                className="absolute right-1 top-1 h-7 w-7"
              >
                <X className="size-3.5" />
              </Button>
            </div>
          ))}
        </div>
      )}

      <Button
        type="button"
        disabled={files.length === 0 || disabled}
        onClick={() => onUpload(files)}
        className="w-full"
      >
        Reconstruct ({files.length} image{files.length !== 1 ? "s" : ""})
      </Button>
    </div>
  );
}
