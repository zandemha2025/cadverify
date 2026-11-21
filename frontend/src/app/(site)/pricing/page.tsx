import type { Metadata } from "next";
import { getPlans } from "@/lib/plans";
import { PrecisePricing } from "@/components/site/precise-pricing";
export const metadata: Metadata = { title: "Pricing — ScaleCAD", description: "Try it free on your own parts. Call us when you want it across a factory.", alternates: { canonical: "/pricing" } };
export default async function PricingPage() { const { pro } = await getPlans(); return <PrecisePricing pro={pro} />; }
