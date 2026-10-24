"use client";

/**
 * Cloudflare Turnstile for the v4 signed-out screens: the same script, site key,
 * nonce and token flow as components/auth/turnstile-widget.tsx, drawn in the
 * light theme and labelled "Security check" (boards X1, X12).
 */
import * as React from "react";
import Script from "next/script";

type TurnstileApi = {
  render: (
    container: HTMLElement,
    options: {
      sitekey: string;
      theme: "light";
      size: "flexible";
      callback: (token: string) => void;
      "expired-callback": () => void;
      "error-callback": () => void;
    },
  ) => string;
  reset: (widgetId: string) => void;
  remove: (widgetId: string) => void;
};

function api(): TurnstileApi | undefined {
  return (window as unknown as { turnstile?: TurnstileApi }).turnstile;
}

export function SecurityCheck({
  siteKey,
  nonce,
  resetSignal,
  onToken,
  verified,
}: {
  siteKey: string;
  nonce?: string;
  resetSignal: number;
  onToken: (token: string | null) => void;
  verified: boolean;
}) {
  const container = React.useRef<HTMLDivElement>(null);
  const widgetId = React.useRef<string | null>(null);
  const onTokenRef = React.useRef(onToken);

  React.useEffect(() => {
    onTokenRef.current = onToken;
  }, [onToken]);

  const renderWidget = React.useCallback(() => {
    const t = api();
    if (!container.current || !t || widgetId.current) return;
    widgetId.current = t.render(container.current, {
      sitekey: siteKey,
      theme: "light",
      size: "flexible",
      callback: (token) => onTokenRef.current(token),
      "expired-callback": () => onTokenRef.current(null),
      "error-callback": () => onTokenRef.current(null),
    });
  }, [siteKey]);

  // The script may already be loaded from an earlier screen.
  React.useEffect(() => {
    renderWidget();
  }, [renderWidget]);

  React.useEffect(() => {
    const t = api();
    if (resetSignal > 0 && widgetId.current && t) {
      t.reset(widgetId.current);
      onTokenRef.current(null);
    }
  }, [resetSignal]);

  React.useEffect(
    () => () => {
      const t = api();
      if (widgetId.current && t) {
        t.remove(widgetId.current);
        widgetId.current = null;
      }
    },
    [],
  );

  return (
    <div className="mo-tsw" role="group" aria-label="Security check">
      <span className="row">
        <span>Security check</span>
        <span className={verified ? "ok" : undefined} aria-live="polite">
          {verified ? "Verified" : "Confirm you’re human"}
        </span>
      </span>
      <Script
        src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
        nonce={nonce}
        strategy="afterInteractive"
        onReady={renderWidget}
        onError={() => onTokenRef.current(null)}
      />
      <div ref={container} className="slot" />
    </div>
  );
}
