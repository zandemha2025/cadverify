"use client";

/**
 * Make-vs-buy breakeven chart: cost/unit (y) vs quantity (x, log scale), one
 * curve per costed process. The process currently recommended at the slider
 * quantity is drawn in the steel-blue accent and thicker; everything else is
 * muted slate. The engine's crossover is marked; the live slider quantity is a
 * dashed reference line. Colour discipline: accent = the recommendation,
 * neutral = alternatives — status colours stay reserved for status.
 */
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  type TooltipProps,
} from "recharts";
import { procLabel } from "@/lib/status";
import {
  type Breakeven,
  unitCostAt,
  sampleQuantities,
} from "@/lib/breakeven";

// Theme-aware: SVG resolves these CSS vars from the cascade, so the chart
// re-themes (light/dark) for free. ACCENT = the recommendation; MUTED =
// alternatives. Status colours stay reserved for status.
const ACCENT = "var(--cv-primary)";
const MUTED = "var(--cv-tick)";
const GRID = "var(--cv-border)";
const AXIS = "var(--cv-muted-foreground)";

function fmtMoney(n: number): string {
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: n < 10 ? 2 : 0 })}`;
}

function fmtQty(n: number): string {
  if (n >= 1000) return `${(n / 1000).toLocaleString("en-US", { maximumFractionDigits: 1 })}k`;
  return String(n);
}

function BreakevenTooltip({
  active,
  payload,
  label,
  recommended,
}: TooltipProps<number, string> & {
  recommended: string;
  // Recharts v3 omits these from the props type (read-from-context); they are
  // still supplied at runtime to custom tooltip content. Re-declared so the
  // render body type-checks against what Recharts actually passes.
  payload?: Array<{ value?: number; dataKey: string | number; color?: string }>;
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;
  const rows = [...payload]
    .filter((p) => typeof p.value === "number")
    .sort((a, b) => (a.value as number) - (b.value as number));
  return (
    <div className="rounded-[var(--radius)] border border-border bg-card px-3 py-2 text-xs shadow-md">
      <p className="num mb-1 font-medium text-foreground">
        qty {Number(label).toLocaleString()}
      </p>
      <div className="space-y-0.5">
        {rows.map((p) => (
          <div key={p.dataKey} className="flex items-center justify-between gap-4">
            <span
              className="flex items-center gap-1.5"
              style={{ color: p.dataKey === recommended ? ACCENT : AXIS }}
            >
              <span
                className="inline-block size-2 rounded-full"
                style={{ background: p.color }}
              />
              {procLabel(String(p.dataKey))}
              {p.dataKey === recommended && (
                <span className="font-semibold">· pick</span>
              )}
            </span>
            <span className="num font-medium text-foreground">
              {fmtMoney(p.value as number)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function BreakevenChart({
  breakeven,
  qty,
  recommendedProcess,
}: {
  breakeven: Breakeven;
  qty: number;
  recommendedProcess: string;
}) {
  const { curves, crossoverQty, qtyMin, qtyMax } = breakeven;
  const samples = sampleQuantities(breakeven);

  // one row per sampled quantity; one key per process
  const data = samples.map((q) => {
    const row: Record<string, number> = { qty: q };
    for (const c of curves) row[c.process] = Number(unitCostAt(c, q).toFixed(2));
    return row;
  });

  const ticks = [1, 10, 100, 1000, 10000, 100000].filter(
    (t) => t >= qtyMin && t <= qtyMax
  );

  return (
    <div className="h-[280px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="qty"
            type="number"
            scale="log"
            domain={[qtyMin, qtyMax]}
            ticks={ticks}
            allowDataOverflow
            tickFormatter={fmtQty}
            tick={{ fontSize: 11, fill: AXIS }}
            stroke={GRID}
            label={{
              value: "quantity",
              position: "insideBottomRight",
              offset: -2,
              fontSize: 11,
              fill: AXIS,
            }}
          />
          <YAxis
            tickFormatter={fmtMoney}
            tick={{ fontSize: 11, fill: AXIS }}
            stroke={GRID}
            width={56}
            label={{
              value: "$ / unit",
              angle: -90,
              position: "insideLeft",
              fontSize: 11,
              fill: AXIS,
            }}
          />
          <Tooltip
            content={<BreakevenTooltip recommended={recommendedProcess} />}
            isAnimationActive={false}
          />

          {crossoverQty != null && crossoverQty >= qtyMin && crossoverQty <= qtyMax && (
            <ReferenceLine
              x={crossoverQty}
              stroke={AXIS}
              strokeDasharray="4 4"
              label={{
                value: `crossover ≈ ${Math.round(crossoverQty).toLocaleString()}`,
                position: "top",
                fontSize: 10,
                fill: AXIS,
              }}
            />
          )}

          <ReferenceLine
            x={qty}
            stroke={ACCENT}
            strokeWidth={1.5}
            label={{
              value: `qty ${qty.toLocaleString()}`,
              position: "insideTopLeft",
              fontSize: 10,
              fill: ACCENT,
            }}
          />

          {curves.map((c) => {
            const isRec = c.process === recommendedProcess;
            return (
              <Line
                key={c.process}
                type="monotone"
                dataKey={c.process}
                name={procLabel(c.process)}
                stroke={isRec ? ACCENT : MUTED}
                strokeWidth={isRec ? 2.5 : 1.5}
                dot={false}
                activeDot={isRec ? { r: 4 } : { r: 3 }}
                isAnimationActive={false}
              />
            );
          })}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
