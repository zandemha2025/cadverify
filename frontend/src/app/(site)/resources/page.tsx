import { growthResources } from "@/lib/site/growth-content";
import { growthMetadata } from "@/components/site/growth-page";
import { GrowthLink } from "@/components/site/growth-actions";
import { SiteShell } from "@/components/site/site-shell";

export const metadata = growthMetadata("/resources", "Manufacturing guides and free tools", "Practical CAD manufacturability guides, a CNC DFM checklist, software comparisons and a free make-versus-buy calculator from ScaleCAD.");

export default function ResourcesPage() {
  return <SiteShell><div className="growth"><header className="growth-hero"><span className="growth-eyebrow">The manufacturing desk</span><h1>Better questions.<br />Better manufacturing decisions.</h1><p className="growth-intro">Review the part, challenge the assumptions, and keep the evidence. Start with the decision in front of you.</p></header>
    <div className="growth-cards">
      <article className="growth-card growth-callout"><span className="growth-eyebrow">Free tool · no account</span><h2><GrowthLink href="/tools/make-vs-buy-calculator">Make vs buy calculator</GrowthLink></h2><p>Compare fixed and variable costs, find the equality quantity, and see how volume changes the decision. Your inputs stay in your browser.</p><GrowthLink href="/tools/make-vs-buy-calculator">Run the calculation →</GrowthLink></article>
      {growthResources.map(resource => <article key={resource.path} className="growth-card"><span className="growth-eyebrow">{resource.category}</span><h2><GrowthLink href={resource.path}>{resource.title}</GrowthLink></h2><p>{resource.description}</p><GrowthLink href={resource.path}>Read {resource.category.toLowerCase()} →</GrowthLink></article>)}
    </div>
  </div></SiteShell>;
}
