"use client";

import { useCallback, useEffect, useRef, useState } from "react";

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
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

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
        setError(`Maximum ${MAX_FILES} images allowed. You have ${files.length}, tried to add ${incoming.length}.`);
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
    [files.length]
  );

  const addFiles = useCallback(
    (incoming: File[]) => {
      const valid = validate(incoming);
      if (valid) {
        setFiles((prev) => [...prev, ...valid]);
      }
    },
    [validate]
  );

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
    setError(null);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    if (disabled) return;
    const dropped = Array.from(e.dataTransfer.files);
    addFiles(dropped);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    if (!disabled) setDragActive(true);
  };

  const handleDragLeave = () => setDragActive(false);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      addFiles(Array.from(e.target.files));
    }
    // Reset so the same file can be re-selected
    e.target.value = "";
  };

  const handleZoneClick = () => {
    if (!disabled) inputRef.current?.click();
  };

  const handleZoneKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleZoneClick();
    }
  };

  return (
    <div className="space-y-4">
      {/* Drop zone */}
      <div
        role="button"
        tabIndex={0}
        onClick={handleZoneClick}
        onKeyDown={handleZoneKeyDown}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
          dragActive
            ? "border-blue-500 bg-blue-50"
            : "border-gray-300 hover:border-gray-400"
        } ${disabled ? "pointer-events-none opacity-50" : "cursor-pointer"}`}
      >
        {/* Camera icon */}
        <svg
          className="mb-3 h-10 w-10 text-gray-400"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z"
          />
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z"
          />
        </svg>
        <p className="text-sm font-medium text-gray-700">
          Drop images here or click to upload
        </p>
        <p className="mt-1 text-xs text-gray-500">
          JPEG, PNG, or WebP (max 4 images, 20 MB each)
        </p>
      </div>

      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED_EXT}
        onChange={handleInputChange}
        className="hidden"
        aria-label="Select images for reconstruction"
      />

      {/* Error message */}
      {error && (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      )}

      {/* Preview grid */}
      {files.length > 0 && (
        <div className="grid grid-cols-2 gap-3">
          {previews.map((src, i) => (
            <div
              key={`${files[i].name}-${i}`}
              className="relative overflow-hidden rounded-lg border"
            >
              <img
                src={src}
                alt={`Upload preview ${i + 1}`}
                className="h-32 w-full object-cover"
              />
              <button
                type="button"
                onClick={() => removeFile(i)}
                className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-black/60 text-xs text-white hover:bg-black/80"
                aria-label={`Remove image ${i + 1}`}
              >
                X
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Submit */}
      <button
        type="button"
        disabled={files.length === 0 || disabled}
        onClick={() => onUpload(files)}
        className="w-full rounded-md bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        Reconstruct ({files.length} image{files.length !== 1 ? "s" : ""})
      </button>
    </div>
  );
}
