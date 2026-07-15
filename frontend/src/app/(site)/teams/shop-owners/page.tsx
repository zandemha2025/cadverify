import type { Metadata } from "next";
import ShopOwnersClient from "./shop-owners-client";

export const metadata: Metadata = {
  title: "For shop owners — ProofShape",
  description:
    "Your machines ARE the inventory. Declare them once, and every part that hits your inbox gets a verdict — fits which machine, in what material, at what marginal cost.",
};

export default function ShopOwnersPage() {
  return <ShopOwnersClient />;
}
