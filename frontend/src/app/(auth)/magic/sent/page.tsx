import type { Metadata } from "next";
import Link from "next/link";
import { PublicHeader } from "@/components/ui/public-chrome";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "Magic link sent - CadVerify",
  robots: { index: false, follow: false },
};

export default async function MagicSentPage({
  searchParams,
}: {
  searchParams: Promise<{ email?: string }>;
}) {
  const { email } = await searchParams;
  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <PublicHeader showCta={false} />
      <main className="flex flex-1 items-center justify-center px-4 py-16">
        <Card className="w-full max-w-md">
          <CardContent className="space-y-6 text-center">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Magic link
            </p>
            <h1 className="text-2xl font-semibold text-foreground">
              Check your email.
            </h1>
            <p className="text-sm leading-6 text-muted-foreground">
              {email
                ? `If ${email} is allowed to sign in, a single-use link is on its way.`
                : "If that address is allowed to sign in, a single-use link is on its way."}
            </p>
            <div className="flex justify-center gap-3">
              <Button asChild variant="secondary">
                <Link href="/login">Back to login</Link>
              </Button>
              <Button asChild>
                <Link href="/signup">Try another email</Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
