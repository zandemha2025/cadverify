"use client";

import { useCallback, useState } from "react";

interface FileDropZoneProps {
  onFileSelect: (file: File) => void;
  isLoading: boolean;
}

export default function FileDropZone({ onFileSelect, isLoading }: FileDropZoneProps) {
  const [isDragOver, setIsDragOver] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) onFileSelect(file);
    },
    [onFileSelect]
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) onFileSelect(file);
    },
    [onFileSelect]
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={handleDrop}
      className={`
        border-2 border-dashed rounded-2xl p-12 text-center cursor-pointer
        transition-all duration-200
        ${isDragOver
          ? "border-blue-500 bg-blue-50 scale-[1.02]"
          : "border-gray-300 hover:border-gray-400 hover:bg-gray-50"
        }
        ${isLoading ? "opacity-50 pointer-events-none" : ""}
      `}
    >
      <input
        type="file"
        accept=".stl,.step,.stp"
        onChange={handleFileInput}
        className="hidden"
        id="file-upload"
        disabled={isLoading}
      />
      <label htmlFor="file-upload" className="cursor-pointer">
        <div className="mb-4">
          <svg className="mx-auto h-16 w-16 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
          </svg>
        </div>
        <p className="text-lg font-semibold text-gray-700">
          {isLoading ? "Analyzing..." : "Drop your STEP or STL file here"}
        </p>
        <p className="text-sm text-gray-500 mt-2">
          or click to browse. Supports .stl, .step, .stp
        </p>
      </label>
    </div>
  );
}
