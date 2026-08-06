import { redirect } from "next/navigation";

export default function OnboardingPage() {
  redirect("/verify?welcome=1");
}
