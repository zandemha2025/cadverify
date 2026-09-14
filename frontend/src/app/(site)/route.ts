import { HOME_HTML } from "./home-v2-html";

export const dynamic = "force-static";

export function GET(): Response {
  return new Response(HOME_HTML, {
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}
