"use client";

import { useCallback } from "react";

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
    <button
      onClick={handleCopy}
      className="absolute top-2 right-2 px-2 py-1 text-xs text-gray-400 hover:text-gray-200 bg-gray-700 hover:bg-gray-600 rounded transition"
      title="Copy to clipboard"
    >
      Copy
    </button>
  );
}

function CodeBlock({ code, language }: { code: string; language?: string }) {
  return (
    <div className="relative mt-3 mb-6">
      <CopyButton text={code} />
      <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 overflow-x-auto text-sm leading-relaxed">
        <code>{code}</code>
      </pre>
    </div>
  );
}

export default function DocsPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b">
        <div className="max-w-4xl mx-auto px-4 py-4 flex items-center justify-between">
          <a href="/" className="text-xl font-bold text-gray-900">
            CadVerify
          </a>
          <div className="flex items-center gap-4">
            <a
              href="/scalar"
              className="text-sm text-gray-600 hover:text-gray-900 transition"
            >
              API Reference
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

      <main className="max-w-4xl mx-auto px-4 py-12">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Quickstart</h1>
        <p className="text-gray-500 mb-10">
          Get started with CadVerify in minutes. Validate CAD files via the API
          or self-host with Docker Compose.
        </p>

        {/* Section 1: curl */}
        <section className="mb-12">
          <h2 className="text-2xl font-semibold text-gray-900 mb-3">
            1. Quick Start with curl
          </h2>
          <p className="text-gray-600 mb-2">
            Send a STEP or STL file and get manufacturability feedback in one
            request:
          </p>
          <CodeBlock
            language="bash"
            code={`curl -X POST https://api.cadverify.com/api/v1/validate \\
  -H "Authorization: Bearer cv_live_YOUR_KEY" \\
  -F "file=@part.stl" \\
  -F "processes=fdm,cnc_3axis"`}
          />
          <p className="text-sm text-gray-500">
            Replace <code className="bg-gray-100 px-1 rounded">cv_live_YOUR_KEY</code> with
            your actual API key. See the{" "}
            <a href="/scalar" className="text-blue-600 hover:underline">
              full API reference
            </a>{" "}
            for all available parameters and response fields.
          </p>
        </section>

        {/* Section 2: Self-host */}
        <section className="mb-12">
          <h2 className="text-2xl font-semibold text-gray-900 mb-3">
            2. Self-Host with Docker Compose
          </h2>
          <p className="text-gray-600 mb-2">
            Run CadVerify on your own infrastructure:
          </p>
          <CodeBlock
            language="bash"
            code={`git clone https://github.com/cadverify/cadverify.git
cd cadverify
cp .env.example .env
# Edit .env with your settings
docker compose up -d
# Open http://localhost:3000`}
          />
          <p className="text-sm text-gray-500">
            The Docker Compose stack includes the backend API, frontend, and a
            Postgres database. Edit <code className="bg-gray-100 px-1 rounded">.env</code>{" "}
            to configure database credentials, Sentry DSN, and other settings.
          </p>
        </section>

        {/* Section 3: Authenticated request walkthrough */}
        <section className="mb-12">
          <h2 className="text-2xl font-semibold text-gray-900 mb-3">
            3. Authenticated Request Walkthrough
          </h2>
          <ol className="list-decimal list-inside space-y-3 text-gray-700">
            <li>
              Sign up at{" "}
              <a href="/auth/signup" className="text-blue-600 hover:underline">
                cadverify.com
              </a>{" "}
              to get your API key.
            </li>
            <li>
              Store your key securely — it is shown once at creation time.
            </li>
            <li>
              Include{" "}
              <code className="bg-gray-100 px-1 rounded text-sm">
                Authorization: Bearer cv_live_...
              </code>{" "}
              in every request.
            </li>
            <li>
              Check rate limits via the{" "}
              <code className="bg-gray-100 px-1 rounded text-sm">
                X-RateLimit-Remaining
              </code>{" "}
              response header.
            </li>
            <li>
              View your usage at{" "}
              <a href="/dashboard" className="text-blue-600 hover:underline">
                cadverify.com/dashboard
              </a>
              .
            </li>
          </ol>
          <CodeBlock
            language="bash"
            code={`# Example: authenticated validation with process filter
curl -X POST https://api.cadverify.com/api/v1/validate \\
  -H "Authorization: Bearer cv_live_sk_abc123..." \\
  -F "file=@bracket.step" \\
  -F "processes=cnc_3axis,cnc_5axis"

# Check rate limit headers in the response:
# X-RateLimit-Limit: 100
# X-RateLimit-Remaining: 97
# X-RateLimit-Reset: 1700000000`}
          />
        </section>

        {/* Links */}
        <div className="border-t pt-8 flex flex-wrap gap-6 text-sm text-gray-500">
          <a href="/scalar" className="hover:text-gray-900 transition">
            Full API Reference
          </a>
          <a href="/" className="hover:text-gray-900 transition">
            Home
          </a>
          <a
            href="https://github.com/cadverify/cadverify"
            className="hover:text-gray-900 transition"
            target="_blank"
            rel="noopener noreferrer"
          >
            GitHub
          </a>
        </div>
      </main>
    </div>
  );
}
