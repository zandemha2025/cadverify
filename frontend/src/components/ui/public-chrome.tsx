import Link from "next/link";
import * as React from "react";
import { Button } from "@/components/ui/button";

const GITHUB_URL = "https://github.com/zandemha2025/cadverify";

/**
 * The primary public CTA — "Sign up" → /signup. The platform is fully gated
 * (no anonymous demo), so the marketing front door is account creation. No
 * client-auth coupling: the perimeter is always logged-out.
 */
export function PrimaryCta({
  size = "md",
  className,
}: {
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  return (
    <Button asChild size={size} className={className}>
      <Link href="/signup">Sign up</Link>
    </Button>
  );
}

/** Ghost nav link for the public header (shares Button so weights/sizes match). */
export function PublicNavLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <Button asChild variant="ghost" size="sm">
      <Link href={href}>{children}</Link>
    </Button>
  );
}

/**
 * THE one public/marketing header. Wordmark + caller-supplied nav links + the
 * auth-aware CTA, on shared chrome (slate tokens, border, card surface).
 */
export function PublicHeader({
  children,
  showCta = true,
}: {
  children?: React.ReactNode;
  showCta?: boolean;
}) {
  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex h-14 max-w-screen-2xl items-center justify-between px-4 lg:px-8">
        <Link href="/" className="group flex items-center gap-2.5">
          <span
            aria-hidden
            className="h-4 w-[3px] rounded-[1px] bg-primary transition-transform group-hover:scale-y-110"
          />
          <span className="cv-wordmark text-[17px] text-foreground">
            CadVerify
          </span>
          <span className="hidden text-xs text-subtle-foreground sm:inline">
            should-cost, made of glass
          </span>
        </Link>
        <nav className="flex items-center gap-1 sm:gap-2">
          {children}
          {showCta && (
            <>
              <PublicNavLink href="/login">Log in</PublicNavLink>
              <PrimaryCta size="sm" />
            </>
          )}
        </nav>
      </div>
    </header>
  );
}

/** THE one public footer. */
export function PublicFooter() {
  return (
    <footer className="border-t border-border bg-card">
      <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center justify-center gap-6 px-4 py-8 text-sm text-muted-foreground lg:px-8">
        <a href="/scalar" className="transition-colors hover:text-foreground">
          API reference
        </a>
        <Link href="/privacy" className="transition-colors hover:text-foreground">
          Privacy
        </Link>
        <Link href="/terms" className="transition-colors hover:text-foreground">
          Terms
        </Link>
        <Link href="/status" className="transition-colors hover:text-foreground">
          Status
        </Link>
        <Link href="/docs" className="transition-colors hover:text-foreground">
          Quickstart
        </Link>
        <Link href="/" className="transition-colors hover:text-foreground">
          Home
        </Link>
        <a
          href={GITHUB_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="transition-colors hover:text-foreground"
        >
          GitHub
        </a>
      </div>
    </footer>
  );
}
