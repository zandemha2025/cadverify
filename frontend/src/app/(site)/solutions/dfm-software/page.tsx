import { GrowthPage, growthMetadata } from "@/components/site/growth-page";
import { resourceAt } from "@/lib/site/growth-content";

const resource = resourceAt("/solutions/dfm-software")!;
export const metadata = growthMetadata(resource.path, resource.title, resource.description);
export default function DfmPage() { return <GrowthPage resource={resource} />; }
