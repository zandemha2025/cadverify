import { redirect } from "next/navigation";

export default function LegacySignupPage(): never {
  redirect("/signup");
}
