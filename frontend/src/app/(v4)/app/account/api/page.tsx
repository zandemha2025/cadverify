import { backendOrigin } from "@/lib/api-base";
import { ApiScreen } from "@/components/v4/account/api-screen";

export const dynamic = "force-dynamic";

export default function Page() {
  return <ApiScreen apiOrigin={backendOrigin()} />;
}
