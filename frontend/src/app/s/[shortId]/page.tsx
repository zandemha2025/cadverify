import type { Metadata } from "next";
import { fetchSharedAnalysis } from "@/lib/api";
import type { SharedAnalysis, Issue, ProcessScore } from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  OG Meta Tags for link previews (Slack, email, social)             */
/* ------------------------------------------------------------------ */

export async function generateMetadata({
  params,
}: {
  params: Promise<{ shortId: string }>;
}): Promise<Metadata> {
  const { shortId } = await params;
  try {
    const data = await fetchSharedAnalysis(shortId);
    const processCount = data.process_scores?.length ?? 0;
    return {
      title: `${data.filename} - DFM Analysis`,
      openGraph: {
        title: `${data.filename} - DFM Analysis`,
        description: `Verdict: ${data.verdict} | ${processCount} processes evaluated | ${data.face_count} faces`,
        type: "article",
        siteName: "CadVerify",
      },
      twitter: { card: "summary" },
      robots: { index: false, follow: false },
    };
  } catch {
    return { title: "Shared Analysis - CadVerify" };
  }
}

/* ------------------------------------------------------------------ */
/*  Verdict styling                                                    */
/* ------------------------------------------------------------------ */

const VERDICT_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  pass: { bg: "bg-green-50 border-green-200", text: "text-green-800", label: "Manufacturable" },
  issues: { bg: "bg-yellow-50 border-yellow-200", text: "text-yellow-800", label: "Issues Found" },
  fail: { bg: "bg-red-50 border-red-200", text: "text-red-800", label: "Not Manufacturable" },
};

const SEVERITY_STYLES: Record<string, string> = {
  error: "bg-red-100 text-red-700",
  warning: "bg-yellow-100 text-yellow-700",
  info: "bg-blue-100 text-blue-700",
};

/* ------------------------------------------------------------------ */
/*  Server Component — read-only public share page                     */
/* ------------------------------------------------------------------ */

export default async function SharedAnalysisPage({
  params,
}: {
  params: Promise<{ shortId: string }>;
}) {
  const { shortId } = await params;

  let data: SharedAnalysis | null = null;
  try {
    data = await fetchSharedAnalysis(shortId);
  } catch {
    /* 404 or network error */
  }

  if (!data) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-16 text-center">
        <h1 className="text-2xl font-bold text-gray-800">
          Analysis Not Available
        </h1>
        <p className="mt-2 text-gray-500">
          This shared analysis is no longer available. It may have been revoked
          by its owner.
        </p>
        <a
          href="/"
          className="mt-6 inline-block rounded-md bg-black px-4 py-2 text-sm text-white hover:bg-gray-800"
        >
          Go to CadVerify
        </a>
      </main>
    );
  }

  const verdict = VERDICT_STYLES[data.verdict] ?? {
    bg: "bg-gray-50 border-gray-200",
    text: "text-gray-800",
    label: data.verdict,
  };

  const sortedIssues = [...(data.universal_issues || [])].sort((a, b) => {
    const order: Record<string, number> = { error: 0, warning: 1, info: 2 };
    return (order[a.severity] ?? 3) - (order[b.severity] ?? 3);
  });

  const sortedProcesses = [...(data.process_scores || [])].sort(
    (a, b) => b.score - a.score
  );

  const geo = data.geometry || ({} as Record<string, unknown>);

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      {/* Header */}
      <div className={`rounded-xl border p-5 ${verdict.bg}`}>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">{data.filename}</h1>
            <p className="mt-1 text-sm text-gray-500">
              {data.file_type.toUpperCase()} &middot;{" "}
              {new Date(data.created_at).toLocaleDateString()} &middot;{" "}
              {data.duration_ms}ms
            </p>
          </div>
          <span className={`text-lg font-bold ${verdict.text}`}>
            {verdict.label}
          </span>
        </div>
      </div>

      {/* Geometry Overview */}
      {"faces" in geo && (
        <section className="mt-6">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
            Geometry
          </h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Faces" value={String(data.face_count)} />
            {geo.volume_mm3 != null && (
              <StatCard
                label="Volume"
                value={`${(Number(geo.volume_mm3) / 1000).toFixed(1)} cm3`}
              />
            )}
            {geo.bounding_box_mm && (
              <StatCard
                label="Dimensions"
                value={`${(geo.bounding_box_mm as number[]).map((d: number) => d.toFixed(1)).join(" x ")} mm`}
              />
            )}
            {geo.is_watertight != null && (
              <StatCard
                label="Watertight"
                value={geo.is_watertight ? "Yes" : "No"}
              />
            )}
          </div>
        </section>
      )}

      {/* Issues */}
      {sortedIssues.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
            Issues ({sortedIssues.length})
          </h2>
          <div className="space-y-2">
            {sortedIssues.map((issue: Issue, i: number) => (
              <div key={i} className="rounded-lg border bg-white p-3">
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded px-1.5 py-0.5 text-xs font-medium ${SEVERITY_STYLES[issue.severity] ?? SEVERITY_STYLES.info}`}
                  >
                    {issue.severity}
                  </span>
                  <span className="font-mono text-xs text-gray-500">
                    {issue.code}
                  </span>
                </div>
                <p className="mt-1 text-sm text-gray-700">{issue.message}</p>
                {issue.fix_suggestion && (
                  <p className="mt-1 text-sm text-blue-700">
                    {issue.fix_suggestion}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Process Ranking */}
      {sortedProcesses.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
            Process Ranking
          </h2>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-left text-sm">
              <thead className="border-b bg-gray-50">
                <tr>
                  <th className="px-3 py-2 font-medium text-gray-600">Process</th>
                  <th className="px-3 py-2 font-medium text-gray-600">Score</th>
                  <th className="px-3 py-2 font-medium text-gray-600">Verdict</th>
                  <th className="px-3 py-2 font-medium text-gray-600">Material</th>
                  <th className="px-3 py-2 font-medium text-gray-600">Machine</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {sortedProcesses.map((ps: ProcessScore) => (
                  <tr key={ps.process}>
                    <td className="px-3 py-2 font-medium">{ps.process}</td>
                    <td className="px-3 py-2">{ps.score}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                          ps.verdict === "pass"
                            ? "bg-green-100 text-green-700"
                            : ps.verdict === "issues"
                              ? "bg-yellow-100 text-yellow-700"
                              : "bg-red-100 text-red-700"
                        }`}
                      >
                        {ps.verdict}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-gray-600">
                      {ps.recommended_material ?? "-"}
                    </td>
                    <td className="px-3 py-2 text-gray-600">
                      {ps.recommended_machine ?? "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* CTA Footer */}
      <div className="mt-8 rounded-lg border bg-gray-50 p-4 text-center">
        <p className="text-sm text-gray-600">
          This is a shared analysis from CadVerify.
        </p>
        <a
          href="/"
          className="mt-2 inline-block rounded-md bg-black px-4 py-2 text-sm text-white hover:bg-gray-800"
        >
          View on CadVerify
        </a>
      </div>
    </main>
  );
}

/* ------------------------------------------------------------------ */
/*  Helper components                                                  */
/* ------------------------------------------------------------------ */

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-white p-3">
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p className="mt-0.5 text-sm font-semibold text-gray-800">{value}</p>
    </div>
  );
}
