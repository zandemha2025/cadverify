import { redirect } from "next/navigation";
import { apiDocsServed } from "@/lib/api-docs";
import { publicApiOrigin } from "@/lib/public-api";

/**
 * The API console is the API's own interactive docs, at the deployment's
 * public API address. When docs are off (the default in a release) or the
 * deployment has no public API address, this goes to the in-app API reference
 * instead of an address that doesn't answer.
 */
export async function GET(): Promise<never> {
  const origin = publicApiOrigin();
  if (origin && (await apiDocsServed())) redirect(`${origin}/docs`);
  redirect("/api-reference");
}
