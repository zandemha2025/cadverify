"use client";

import Link from "next/link";
import { useCallback } from "react";
import {
  PublicHeader,
  PublicFooter,
} from "@/components/ui/public-chrome";
import { Button } from "@/components/ui/button";

function CopyButton({ text }: { text: string }) {
  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Fallback for older browsers
      const textarea = document.createElement("textarea");
      textarea.value = text;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    }
  }, [text]);

  return (
    <Button
      variant="secondary"
      size="sm"
      onClick={handleCopy}
      className="absolute right-2 top-2"
      title="Copy to clipboard"
    >
      Copy
    </Button>
  );
}

function CodeBlock({ code, language }: { code: string; language?: string }) {
  return (
    <div className="relative mb-6 mt-3">
      <CopyButton text={code} />
      <pre className="overflow-x-auto rounded-[var(--radius)] bg-neutral-900 p-4 text-sm leading-relaxed text-neutral-100">
        <code className="num" data-language={language}>
          {code}
        </code>
      </pre>
    </div>
  );
}

const API_VALIDATE_URL = "https://cadvrfy-api.fly.dev/api/v1/validate";
const APP_URL = "https://cadvrfy.vercel.app";
const GITHUB_URL = "https://github.com/zandemha2025/cadverify";

export default function DocsPage() {
  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <PublicHeader>
        <Button asChild variant="ghost" size="sm">
          <a href="/scalar">API reference</a>
        </Button>
      </PublicHeader>

      <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-12 lg:px-8">
        <h1 className="mb-2 text-3xl font-bold text-foreground">Quickstart</h1>
        <p className="mb-10 text-muted-foreground">
          Get started with CadVerify in minutes. Validate CAD files via the API
          or self-host with Docker Compose.
        </p>

        {/* Section 1: curl */}
        <section className="mb-12">
          <h2 className="mb-3 text-2xl font-semibold text-foreground">
            1. Quick start with curl
          </h2>
          <p className="mb-2 text-muted-foreground">
            Send a STEP or STL file and get manufacturability feedback in one
            request:
          </p>
          <CodeBlock
            language="bash"
            code={`curl -X POST ${API_VALIDATE_URL} \\
  -H "Authorization: Bearer cv_live_YOUR_KEY" \\
  -F "file=@part.stl" \\
  -F "processes=fdm,cnc_3axis"`}
          />
          <p className="text-sm text-muted-foreground">
            Replace{" "}
            <code className="num rounded bg-muted px-1">cv_live_YOUR_KEY</code>{" "}
            with your actual API key. See the{" "}
            <a href="/scalar" className="text-primary hover:underline">
              full API reference
            </a>{" "}
            for all available parameters and response fields.
          </p>
        </section>

        {/* Section 2: Self-host */}
        <section className="mb-12">
          <h2 className="mb-3 text-2xl font-semibold text-foreground">
            2. Self-host with Docker Compose
          </h2>
          <p className="mb-2 text-muted-foreground">
            Run CadVerify on your own infrastructure:
          </p>
          <CodeBlock
            language="bash"
            code={`git clone ${GITHUB_URL}.git
cd cadverify
cp .env.example .env
# Edit .env with your settings
docker compose up -d
# Open http://localhost:3000`}
          />
          <p className="text-sm text-muted-foreground">
            The Docker Compose stack includes the backend API, frontend, and a
            Postgres database. Edit{" "}
            <code className="num rounded bg-muted px-1">.env</code> to configure
            database credentials, Sentry DSN, and other settings.
          </p>
        </section>

        {/* Section 3: Authenticated request walkthrough */}
        <section className="mb-12">
          <h2 className="mb-3 text-2xl font-semibold text-foreground">
            3. Authenticated request walkthrough
          </h2>
          <ol className="list-inside list-decimal space-y-3 text-foreground">
            <li>
              Sign up at{" "}
              <Link href="/signup" className="text-primary hover:underline">
                {APP_URL}/signup
              </Link>{" "}
              to get your API key.
            </li>
            <li>
              Store your key securely — it is shown once at creation time.
            </li>
            <li>
              Include{" "}
              <code className="num rounded bg-muted px-1 text-sm">
                Authorization: Bearer cv_live_...
              </code>{" "}
              in every request.
            </li>
            <li>
              Check rate limits via the{" "}
              <code className="num rounded bg-muted px-1 text-sm">
                X-RateLimit-Remaining
              </code>{" "}
              response header.
            </li>
            <li>
              View your keys and usage at{" "}
              <Link href="/settings/developer" className="text-primary hover:underline">
                {APP_URL}/settings/developer
              </Link>
              .
            </li>
          </ol>
          <CodeBlock
            language="bash"
            code={`# Example: authenticated validation with process filter
curl -X POST ${API_VALIDATE_URL} \\
  -H "Authorization: Bearer cv_live_sk_abc123..." \\
  -F "file=@bracket.step" \\
  -F "processes=cnc_3axis,cnc_5axis"

# Check rate limit headers in the response:
# X-RateLimit-Limit: 100
# X-RateLimit-Remaining: 97
# X-RateLimit-Reset: 1700000000`}
          />
        </section>

        {/* Inline next steps */}
        <div className="flex flex-wrap gap-3 border-t border-border pt-8">
          <Button asChild>
            <Link href="/signup">Get an API key</Link>
          </Button>
          <Button asChild variant="secondary">
            <a href="/scalar">Full API reference</a>
          </Button>
        </div>
      </main>

      <PublicFooter />
    </div>
  );
}
