import Script from "next/script";
import { startMagic } from "./actions";

export default function SignupPage() {
  const sitekey = process.env.NEXT_PUBLIC_TURNSTILE_SITEKEY!;
  const apiBase = process.env.NEXT_PUBLIC_API_BASE!;
  return (
    <main className="mx-auto max-w-sm py-24 space-y-6">
      <h1 className="text-2xl font-semibold">Get your CadVerify API key</h1>
      <a
        href={`${apiBase}/auth/google/start`}
        className="block w-full rounded-md bg-black px-4 py-2 text-center text-white"
      >
        Continue with Google
      </a>
      <div className="text-center text-sm text-neutral-500">or</div>
      <form action={startMagic} className="space-y-3">
        <input
          name="email"
          type="email"
          required
          placeholder="you@company.com"
          className="w-full rounded-md border px-3 py-2"
        />
        <Script
          src="https://challenges.cloudflare.com/turnstile/v0/api.js"
          async
          defer
        />
        <div className="cf-turnstile" data-sitekey={sitekey} />
        <button
          type="submit"
          className="w-full rounded-md border border-black px-4 py-2"
        >
          Send magic link
        </button>
      </form>
    </main>
  );
}
