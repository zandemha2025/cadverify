"use client";

import { useState, useEffect } from "react";
import { getRulePacks, type RulePackInfo } from "@/lib/api";

const PACK_COLORS: Record<string, string> = {
  aerospace: "bg-blue-100 text-blue-800 border-blue-200",
  automotive: "bg-green-100 text-green-800 border-green-200",
  oil_gas: "bg-orange-100 text-orange-800 border-orange-200",
  medical: "bg-purple-100 text-purple-800 border-purple-200",
};

function getPackColor(name: string): string {
  const key = name.toLowerCase().replace(/[\s&-]+/g, "_");
  return PACK_COLORS[key] ?? "bg-gray-100 text-gray-800 border-gray-200";
}

interface RulePackSelectorProps {
  selected: string | null;
  onSelect: (packName: string | null) => void;
  disabled?: boolean;
}

export default function RulePackSelector({
  selected,
  onSelect,
  disabled = false,
}: RulePackSelectorProps) {
  const [packs, setPacks] = useState<RulePackInfo[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getRulePacks()
      .then((data) => {
        if (!cancelled) {
          setPacks(data.rule_packs ?? []);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load rule packs");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedPack = packs.find((p) => p.name === selected);

  if (error) {
    return null;
  }

  return (
    <div className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm transition ${
          disabled
            ? "opacity-50 cursor-not-allowed bg-gray-50"
            : "hover:bg-gray-50 cursor-pointer"
        } ${selected ? "border-gray-300 bg-white" : "border-gray-200 bg-white text-gray-600"}`}
      >
        <svg
          className="w-4 h-4 text-gray-400"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          />
        </svg>
        {selectedPack ? (
          <span className={`px-2 py-0.5 rounded text-xs font-medium border ${getPackColor(selectedPack.name)}`}>
            {selectedPack.name} v{selectedPack.version}
          </span>
        ) : (
          <span>Rule Pack</span>
        )}
        <svg
          className={`w-3 h-3 text-gray-400 transition-transform ${isOpen ? "rotate-180" : ""}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 mt-1 w-72 bg-white border border-gray-200 rounded-xl shadow-lg z-20 py-1">
            <button
              type="button"
              onClick={() => {
                onSelect(null);
                setIsOpen(false);
              }}
              className={`w-full text-left px-4 py-2.5 text-sm hover:bg-gray-50 transition ${
                !selected ? "bg-gray-50 font-medium" : ""
              }`}
            >
              <span className="text-gray-800">None (default rules)</span>
              <p className="text-xs text-gray-400 mt-0.5">Standard manufacturing validation</p>
            </button>
            {packs.map((pack) => (
              <button
                key={pack.name}
                type="button"
                onClick={() => {
                  onSelect(pack.name);
                  setIsOpen(false);
                }}
                className={`w-full text-left px-4 py-2.5 text-sm hover:bg-gray-50 transition ${
                  selected === pack.name ? "bg-gray-50" : ""
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium border ${getPackColor(pack.name)}`}>
                    {pack.name}
                  </span>
                  <span className="text-xs text-gray-400">v{pack.version}</span>
                </div>
                <p className="text-xs text-gray-500 mt-0.5">{pack.description}</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {pack.override_count} overrides, {pack.mandatory_issue_count} mandatory checks
                </p>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
