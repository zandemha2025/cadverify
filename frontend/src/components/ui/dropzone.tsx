"use client";

import * as React from "react";
import { UploadCloud } from "lucide-react";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";

/**
 * The ONE drag-and-drop / click upload target. Merges FileDropZone,
 * BatchUploadForm's inner zone, and reconstruct ImageUploader.
 */
export function Dropzone({
  accept,
  multiple = false,
  onFiles,
  isLoading = false,
  disabled = false,
  hint,
  className,
}: {
  accept?: string;
  multiple?: boolean;
  onFiles: (files: File[]) => void;
  isLoading?: boolean;
  disabled?: boolean;
  hint?: string;
  className?: string;
}) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = React.useState(false);
  const blocked = disabled || isLoading;

  const emit = (list: FileList | null) => {
    if (!list || list.length === 0) return;
    onFiles(Array.from(list));
  };

  return (
    <div
      onClick={() => !blocked && inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        if (!blocked) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (!blocked) emit(e.dataTransfer.files);
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && !blocked) {
          e.preventDefault();
          inputRef.current?.click();
        }
      }}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-[var(--radius)] border-2 border-dashed px-6 py-10 text-center transition-colors",
        dragging
          ? "border-primary bg-primary-50"
          : "border-border-strong bg-card hover:bg-muted/60",
        blocked && "pointer-events-none opacity-60",
        className
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        className="hidden"
        onChange={(e) => {
          emit(e.target.files);
          e.target.value = "";
        }}
      />
      {isLoading ? (
        <Spinner />
      ) : (
        <UploadCloud className="size-8 text-muted-foreground" />
      )}
      <div>
        <p className="text-sm font-medium text-foreground">
          {isLoading
            ? "Uploading…"
            : "Drag and drop or click to upload"}
        </p>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </div>
    </div>
  );
}
