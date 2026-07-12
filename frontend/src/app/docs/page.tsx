import { redirect } from "next/navigation";

/**
 * /developers is the accepted dark-theater API quickstart. Keep /docs as a
 * compatibility alias so old links do not expose the retired public chrome.
 */
export default function DocsAliasPage() {
  redirect("/developers");
}
