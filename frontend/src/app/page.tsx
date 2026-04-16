"use client";

import { useState, useCallback } from "react";
import dynamic from "next/dynamic";
import FileDropZone from "@/components/FileDropZone";
import AnalysisDashboard from "@/components/AnalysisDashboard";
import RulePackSelector from "@/components/RulePackSelector";
import { validateFile, validateQuick, type ValidationResult, type Issue } from "@/lib/api";

const ModelViewer = dynamic(() => import("@/components/ModelViewer"), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center bg-gray-100 rounded-xl">
      <p className="text-gray-400 text-sm">Loading 3D viewer...</p>
    </div>
  ),
});

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

/* ---------- Landing page (unauthenticated) ---------- */

function LandingPage() {
  const [demoFile, setDemoFile] = useState<File | null>(null);
  const [demoResult, setDemoResult] = useState<ValidationResult | null>(null);
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);

  const handleDemoUpload = useCallback(async (file: File) => {
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!ext || !["stl", "step", "stp"].includes(ext)) {
      setDemoError("Unsupported file type. Use .stl, .step, or .stp");
      return;
    }
    setDemoFile(file);
    setDemoLoading(true);
    setDemoError(null);
    setDemoResult(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${API_BASE}/validate/demo`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ message: res.statusText }));
        throw new Error(err.message || err.detail || "Validation failed");
      }
      const data = await res.json();
      setDemoResult(data);
    } catch (err) {
      setDemoError(err instanceof Error ? err.message : "Demo analysis failed");
    } finally {
      setDemoLoading(false);
    }
  }, []);

  const handleReset = useCallback(() => {
    setDemoFile(null);
    setDemoResult(null);
    setDemoError(null);
  }, []);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">CadVerify</h1>
            <p className="text-xs text-gray-500">Manufacturing Validation Platform</p>
          </div>
          <div className="flex items-center gap-3">
            <a
              href="/docs"
              className="text-sm text-gray-600 hover:text-gray-900 transition"
            >
              Docs
            </a>
            <a
              href="/auth/signup"
              className="text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition"
            >
              Get API Key
            </a>
          </div>
        </div>
      </header>

      <main>
        {!demoResult ? (
          <>
            {/* Hero */}
            <section className="max-w-3xl mx-auto px-4 pt-16 pb-12 text-center">
              <h2 className="text-4xl font-bold text-gray-900 mb-4">
                CadVerify
              </h2>
              <p className="text-lg text-gray-600 mb-8">
                Upload a CAD file, get manufacturability feedback across 21 processes in seconds.
              </p>
              <div className="flex justify-center gap-4">
                <a
                  href="/auth/signup"
                  className="inline-flex items-center px-6 py-3 font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition"
                >
                  Get API Key
                </a>
                <a
                  href="#demo"
                  className="inline-flex items-center px-6 py-3 font-semibold text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 rounded-lg transition"
                >
                  Try the Demo
                </a>
              </div>
            </section>

            {/* Demo upload */}
            <section id="demo" className="max-w-2xl mx-auto px-4 pb-16">
              <h3 className="text-2xl font-bold text-gray-900 mb-2 text-center">
                Full Analysis Demo
              </h3>
              <p className="text-gray-500 text-center mb-6">
                Upload an STL file for a complete DFM analysis across all 21 manufacturing processes — no account required.
              </p>

              <FileDropZone onFileSelect={handleDemoUpload} isLoading={demoLoading} />

              {demoLoading && (
                <div className="mt-6 flex items-center justify-center">
                  <div className="text-center">
                    <div className="inline-block w-8 h-8 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin mb-3" />
                    <p className="text-gray-500 text-sm">
                      Analyzing across all manufacturing processes...
                    </p>
                  </div>
                </div>
              )}

              {demoError && (
                <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
                  {demoError}
                </div>
              )}
            </section>

            {/* How it works */}
            <section className="bg-white border-t border-b py-16">
              <div className="max-w-4xl mx-auto px-4">
                <h3 className="text-2xl font-bold text-gray-900 mb-10 text-center">
                  How it works
                </h3>
                <div className="grid md:grid-cols-3 gap-8 text-center">
                  <Step
                    number="1"
                    title="Upload your STEP or STL file"
                    desc="Drag and drop or use the API to submit your CAD geometry."
                  />
                  <Step
                    number="2"
                    title="Get instant DFM analysis across 21 manufacturing processes"
                    desc="Additive, CNC, molding, casting, and sheet metal checks run in seconds."
                  />
                  <Step
                    number="3"
                    title="Share results, export PDF, integrate via API"
                    desc="Collaborate with your team or automate quality gates in your pipeline."
                  />
                </div>
              </div>
            </section>

            {/* Footer */}
            <footer className="py-10">
              <div className="max-w-4xl mx-auto px-4 flex flex-wrap justify-center gap-6 text-sm text-gray-500">
                <a href="https://cadvrfy-api.fly.dev/scalar" className="hover:text-gray-900 transition">
                  API Docs
                </a>
                <a href="/docs" className="hover:text-gray-900 transition">
                  Quickstart
                </a>
              </div>
            </footer>
          </>
        ) : (
          /* Full results view */
          <div className="max-w-7xl mx-auto px-4 py-6">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="text-xl font-bold text-gray-900">
                  Analysis: {demoResult.filename}
                </h2>
                <p className="text-sm text-gray-500">
                  {demoResult.geometry?.faces?.toLocaleString()} faces &middot;{" "}
                  {demoResult.analysis_time_ms}ms &middot;{" "}
                  {demoResult.process_scores?.length} processes evaluated
                </p>
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={handleReset}
                  className="text-sm text-gray-600 hover:text-gray-900 px-4 py-2 rounded-lg border hover:bg-gray-50 transition"
                >
                  Analyze Another File
                </button>
                <a
                  href="/auth/signup"
                  className="text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition"
                >
                  Get API Key
                </a>
              </div>
            </div>

            <div className="grid lg:grid-cols-2 gap-6">
              {demoFile && (
                <div className="h-[500px] lg:h-[calc(100vh-160px)] lg:sticky lg:top-6">
                  <ModelViewer file={demoFile} />
                </div>
              )}
              <div className="pb-12">
                <AnalysisDashboard result={demoResult} />
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function Step({
  number,
  title,
  desc,
}: {
  number: string;
  title: string;
  desc: string;
}) {
  return (
    <div>
      <div className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-blue-100 text-blue-700 font-bold mb-3">
        {number}
      </div>
      <h4 className="font-semibold text-gray-800 mb-1">{title}</h4>
      <p className="text-sm text-gray-500">{desc}</p>
    </div>
  );
}

/* ---------- Dashboard (authenticated) ---------- */

function Dashboard() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedRulePack, setSelectedRulePack] = useState<string | null>(null);

  const handleFileSelect = useCallback(
    async (selectedFile: File) => {
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
    },
    [selectedRulePack]
  );

  const handleReset = useCallback(() => {
    setFile(null);
    setResult(null);
    setError(null);
  }, []);

  return (
    <div className="min-h-screen bg-gray-50">
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
          <div className="grid lg:grid-cols-2 gap-6">
            <div className="h-[500px] lg:h-[calc(100vh-120px)] lg:sticky lg:top-6">
              <ModelViewer file={file} />
            </div>
            <div className="pb-12">
              {isLoading && (
                <div className="flex items-center justify-center h-64">
                  <div className="text-center">
                    <div className="inline-block w-8 h-8 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin mb-3" />
                    <p className="text-gray-500 text-sm">
                      Analyzing across all manufacturing processes...
                    </p>
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

/* ---------- Root page: show landing or dashboard ---------- */

export default function Home() {
  const [isAuthenticated] = useState(() => {
    if (typeof window === "undefined") return false;
    return !!localStorage.getItem("cadverify_api_key");
  });

  if (isAuthenticated) {
    return <Dashboard />;
  }

  return <LandingPage />;
}
