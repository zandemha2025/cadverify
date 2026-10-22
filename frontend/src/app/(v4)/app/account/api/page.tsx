import { ApiScreen } from "@/components/v4/account/api-screen";
import { apiDocsServed } from "@/lib/api-docs";
import { publicApiOrigin } from "@/lib/public-api";

export const dynamic = "force-dynamic";

export default async function Page() {
  return <ApiScreen apiOrigin={publicApiOrigin()} docsEnabled={(await apiDocsServed()) && publicApiOrigin() !== null} />;
}
