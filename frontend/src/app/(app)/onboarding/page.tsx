import type { Metadata } from "next";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "Onboarding - CadVerify",
  robots: { index: false, follow: false },
};

const STEPS = [
  {
    title: "Declare the floor",
    body: "Add the machines you own, their process families, envelopes, materials, and marginal rates.",
    href: "/verify",
    action: "Open machine inventory",
  },
  {
    title: "Publish governed rates",
    body: "Keep the default table visible until a reviewed rate card is published. Every verdict pins its rate version.",
    href: "/verify",
    action: "Open calibration",
  },
  {
    title: "Send actuals back",
    body: "Validation only flips from hatched to measured when real invoices and hours arrive.",
    href: "/verify",
    action: "Open ground truth",
  },
];

export default function OnboardingPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          First run
        </p>
        <h1 className="text-display-l font-semibold text-foreground">
          Declare your world before the engine prices it.
        </h1>
        <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
          CadVerify can compute from defaults on day zero, but the pilot becomes yours when the floor, rates, and actuals are declared instead of implied.
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        {STEPS.map((step, i) => (
          <Card key={step.title}>
            <CardHeader>
              <CardTitle>
                <span className="num mr-2 text-muted-foreground">0{i + 1}</span>
                {step.title}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm leading-6 text-muted-foreground">{step.body}</p>
              <Button asChild variant={i === 0 ? "primary" : "secondary"}>
                <Link href={step.href}>{step.action}</Link>
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
