"use client";

import { useState, useCallback } from "react";
import dynamic from "next/dynamic";
import FileDropZone from "@/components/FileDropZone";
import AnalysisDashboard from "@/components/AnalysisDashboard";
import RulePackSelector from "@/components/RulePackSelector";
import { validateFile, type ValidationResult } from "@/lib/api";

const ModelViewer = dynamic(() => import("@/components/ModelViewer"), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center bg-gray-100 rounded-xl">
      <p className="text-gray-400 text-sm">Loading 3D viewer...</p>
    </div>
  ),
});

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedRulePack, setSelectedRulePack] = useState<string | null>(null);

  const handleFileSelect = useCallback(async (selectedFile: File) => {
    const ext = selectedFile.name.split(".").pop()?.toLowerCase();
    if (!ext || !["stl", "step", "stp"].includes(ext)) {
      setError("Unsupported file type. Use .stl, .step, or .stp");
      return;
    }

    setFile(selectedFile);
    setResult(null);
    setError(null);
    setIsLoading(true);

    try {
      const data = await validateFile(
        selectedFile,
        undefined,
        selectedRulePack ?? undefined
      );
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setIsLoading(false);
    }
  }, [selectedRulePack]);

  const handleReset = useCallback(() => {
    setFile(null);
    setResult(null);
    setError(null);
  }, []);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">CADVerify</h1>
            <p className="text-xs text-gray-500">Manufacturing Validation Platform</p>
          </div>
          <div className="flex items-center gap-3">
            <RulePackSelector
              selected={selectedRulePack}
              onSelect={setSelectedRulePack}
              disabled={isLoading}
            />
            {file && (
              <button
                onClick={handleReset}
                className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg hover:bg-gray-100 transition"
              >
                New Analysis
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6">
        {!file ? (
          /* Upload state */
          <div className="max-w-2xl mx-auto mt-12">
            <div className="text-center mb-8">
              <h2 className="text-3xl font-bold text-gray-900 mb-2">
                Validate your CAD files
              </h2>
              <p className="text-gray-500">
                Upload STEP or STL files for instant manufacturing validation across
                21 processes — additive, CNC, molding, casting, and sheet metal.
              </p>
            </div>
            <FileDropZone onFileSelect={handleFileSelect} isLoading={isLoading} />
            <div className="mt-6 grid grid-cols-3 gap-4 text-center">
              <Feature title="21 Processes" desc="FDM to DMLS to CNC to injection molding" />
              <Feature title="41 Materials" desc="PLA to Inconel 718 to titanium" />
              <Feature title="19 Machines" desc="Bambu Lab to EOS to Haas" />
            </div>
          </div>
        ) : (
          /* Analysis state */
          <div className="grid lg:grid-cols-2 gap-6">
            {/* Left: 3D Viewer */}
            <div className="h-[500px] lg:h-[calc(100vh-120px)] lg:sticky lg:top-6">
              <ModelViewer file={file} />
            </div>

            {/* Right: Results */}
            <div className="pb-12">
              {isLoading && (
                <div className="flex items-center justify-center h-64">
                  <div className="text-center">
                    <div className="inline-block w-8 h-8 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin mb-3" />
                    <p className="text-gray-500 text-sm">Analyzing across all manufacturing processes...</p>
                  </div>
                </div>
              )}

              {error && (
                <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-red-700">
                  <p className="font-semibold">Analysis Failed</p>
                  <p className="text-sm mt-1">{error}</p>
                </div>
              )}

              {result && <AnalysisDashboard result={result} />}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function Feature({ title, desc }: { title: string; desc: string }) {
  return (
    <div>
      <p className="font-semibold text-gray-800">{title}</p>
      <p className="text-xs text-gray-500">{desc}</p>
    </div>
  );
}
