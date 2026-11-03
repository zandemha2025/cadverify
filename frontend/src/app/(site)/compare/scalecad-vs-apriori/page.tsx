import { GrowthPage, growthMetadata } from "@/components/site/growth-page";
import { resourceAt } from "@/lib/site/growth-content";

const resource = resourceAt("/compare/scalecad-vs-apriori")!;
export const metadata = growthMetadata(resource.path, resource.title, resource.description);
export default function ComparisonPage() { return <GrowthPage resource={resource} />; }
