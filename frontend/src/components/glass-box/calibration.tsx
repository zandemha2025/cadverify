"use client";

/**
 * CalibrationBar — per-shop calibration as an always-on fact about the current
 * view, not a buried config. The topbar pill ("Calibrated to <shop> ▾") expands
 * to a panel that shows which rates are SHOP (bound to your reality) vs DEFAULT
 * (still generic) and their verbatim sources — "your numbers become yours," with
 * the gaps visible. When nothing is calibrated, the gap IS the call to action.
 */

import * as React from "react";
import {
  ChevronDown,
  Building2,
  ArrowLeftRight,
  FileText,
  Plus,
  Check,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ProvenanceChip, ProvenanceDot } from "./provenance";

export interface CalibrationRate {
  name: string;
  display: string; // pre-formatted, e.g. "$52/hr"
}

/** A bindable shop in the live picker (structurally a ShopProfileInfo). */
export interface CalibrationShop {
  id: string;
  name: string;
  region?: string;
  source?: string | null;
}

function RateList({
  rates,
  provenance,
}: {
  rates: CalibrationRate[];
  provenance: "SHOP" | "DEFAULT";
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {rates.map((r) => (
        <span
          key={r.name}
          className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-card px-2 py-1 text-xs"
        >
          <ProvenanceDot provenance={provenance} />
          <span className="text-foreground">{r.name}</span>
          <span className="num font-medium text-muted-foreground">{r.display}</span>
        </span>
      ))}
    </div>
  );
}

function ShopPickerRow({
  selected,
  title,
  subtitle,
  disabled,
  onClick,
}: {
  selected: boolean;
  title: React.ReactNode;
  subtitle?: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={selected}
      className={cn(
        "flex w-full items-center gap-2 rounded-sm border px-2.5 py-2 text-left text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
        selected
          ? "border-prov-shop-border bg-prov-shop-bg"
          : "border-border bg-card hover:bg-muted"
      )}
    >
      <span className="flex size-4 shrink-0 items-center justify-center">
        {selected ? (
          <Check className="size-3.5 text-prov-shop" />
        ) : (
          <span className="size-2 rounded-full bg-muted-foreground/30" aria-hidden />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium text-foreground">{title}</span>
        {subtitle && (
          <span className="block truncate text-micro text-muted-foreground">
            {subtitle}
          </span>
        )}
      </span>
    </button>
  );
}

/** The live shop picker — bind a real profile (or generic defaults) → re-cost. */
function ShopPicker({
  shops,
  activeShopId,
  recosting,
  onSelectShop,
  onClose,
}: {
  shops: CalibrationShop[];
  activeShopId: string | null;
  recosting?: boolean;
  onSelectShop: (id: string | null) => void;
  onClose: () => void;
}) {
  const pick = (id: string | null) => {
    if (recosting) return;
    onSelectShop(id);
    onClose();
  };
  return (
    <div className="mt-4 space-y-1.5 border-t border-border pt-3">
      <div className="flex items-center justify-between">
        <span className="cv-eyebrow">Bind a shop — re-costs</span>
        {recosting && (
          <span className="inline-flex items-center gap-1 text-micro text-muted-foreground">
            <Loader2 className="size-3 animate-spin" /> re-costing…
          </span>
        )}
      </div>
      <ShopPickerRow
        selected={activeShopId === null}
        title="Generic defaults"
        subtitle="no shop bound — every rate is a generic DEFAULT"
        disabled={recosting}
        onClick={() => pick(null)}
      />
      {shops.map((s) => (
        <ShopPickerRow
          key={s.id}
          selected={activeShopId === s.id}
          title={s.name}
          subtitle={[s.region, s.source ?? undefined].filter(Boolean).join(" · ")}
          disabled={recosting}
          onClick={() => pick(s.id)}
        />
      ))}
    </div>
  );
}

export function CalibrationBar({
  shopName,
  source,
  note,
  shopRates,
  defaultRates,
  shops,
  activeShopId = null,
  recosting,
  onSelectShop,
  onSwap,
  onOpenProfile,
  onNewCalibration,
  className,
}: {
  /** null → not calibrated (generic defaults); the gap becomes the CTA */
  shopName: string | null;
  source?: string;
  note?: string;
  shopRates?: CalibrationRate[];
  defaultRates?: CalibrationRate[];
  /** when present, render the LIVE shop picker that binds a profile + re-costs (F1) */
  shops?: CalibrationShop[];
  activeShopId?: string | null;
  recosting?: boolean;
  onSelectShop?: (id: string | null) => void;
  onSwap?: () => void;
  onOpenProfile?: () => void;
  onNewCalibration?: () => void;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const calibrated = !!shopName;
  const livePicker = !!shops && !!onSelectShop;

  return (
    <div className={cn("relative inline-block", className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-[var(--radius)] border px-2.5 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          calibrated
            ? "border-prov-shop-border bg-prov-shop-bg text-prov-shop hover:brightness-[0.98]"
            : "border-warn-border bg-warn-bg text-warn"
        )}
      >
        {calibrated ? (
          <ProvenanceDot provenance="SHOP" />
        ) : (
          <span className="size-2 rounded-full bg-warn" aria-hidden />
        )}
        {calibrated ? (
          <>
            Calibrated to <span className="font-semibold">{shopName}</span>
          </>
        ) : (
          "Not calibrated — generic defaults"
        )}
        {recosting ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : (
          <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden />
          <div className="cv-reveal absolute right-0 z-50 mt-2 w-[28rem] max-w-[90vw] rounded-[var(--radius-lg)] border border-border bg-card p-4 shadow-pop">
            {calibrated ? (
              <>
                <div className="flex items-center gap-2">
                  <Building2 className="size-4 text-prov-shop" />
                  <span className="text-sm font-semibold text-foreground">{shopName}</span>
                </div>
                {source && (
                  <p className="mt-1 text-xs text-muted-foreground">Source: {source}</p>
                )}
                {note && (
                  <p className="mt-2 rounded-sm bg-prov-shop-bg px-2.5 py-2 text-xs text-foreground">
                    {note}
                  </p>
                )}

                {shopRates && shopRates.length > 0 && (
                  <div className="mt-3 space-y-1.5">
                    <span className="cv-eyebrow">Bound to this shop</span>
                    <RateList rates={shopRates} provenance="SHOP" />
                  </div>
                )}
                {defaultRates && defaultRates.length > 0 && (
                  <div className="mt-3 space-y-1.5">
                    <span className="cv-eyebrow">Still generic — the gaps</span>
                    <RateList rates={defaultRates} provenance="DEFAULT" />
                  </div>
                )}
              </>
            ) : (
              <div className="space-y-2">
                <p className="text-sm font-semibold text-foreground">
                  Calibrate to a shop to make these numbers yours.
                </p>
                <p className="text-xs text-muted-foreground">
                  Every rate is a generic <ProvenanceChip provenance="DEFAULT" size="xs" /> until
                  a shop profile binds your real labor, machine and material rates.
                </p>
              </div>
            )}

            {livePicker ? (
              <ShopPicker
                shops={shops!}
                activeShopId={activeShopId}
                recosting={recosting}
                onSelectShop={onSelectShop!}
                onClose={() => setOpen(false)}
              />
            ) : (
            <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-3">
              {onSwap && (
                <button
                  type="button"
                  onClick={onSwap}
                  className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <ArrowLeftRight className="size-3.5" />
                  {calibrated ? "Swap shop — re-cost" : "Choose a shop"}
                </button>
              )}
              {calibrated && onOpenProfile && (
                <button
                  type="button"
                  onClick={onOpenProfile}
                  className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <FileText className="size-3.5" />
                  Open shop profile
                </button>
              )}
              {onNewCalibration && (
                <button
                  type="button"
                  onClick={onNewCalibration}
                  className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-card px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Plus className="size-3.5" />
                  New calibration
                </button>
              )}
            </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
