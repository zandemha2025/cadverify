import { redirect } from "next/navigation";
import { backendUrl } from "@/lib/api-base";

export function GET(): never {
  redirect(backendUrl("/docs"));
}
