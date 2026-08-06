import type { Metadata } from "next";
import { NotificationsClient } from "./notifications-client";

export const metadata: Metadata = {
  title: "Notifications - ProofShape",
  robots: { index: false, follow: false },
};

export default function NotificationsPage() {
  return <NotificationsClient />;
}
