import type { Metadata } from "next";
import Link from "next/link";
import Image from "next/image";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { SiteShell } from "@/components/site/site-shell";
import { UPLOAD_HREF } from "@/lib/site/navigation";
import { SampleExplorer } from "@/components/site/sample-explorer";

export const metadata: Metadata = { title: "CadVerify — Know what you can make", description: "Check your part’s manufacturing options, see what needs review, and understand the resources behind the decision. Explore a sample without an account.", alternates: { canonical: "/" } };

export default function HomePage() {
  return <SiteShell>
    <section className="cv-hero cv-wrap">
      <div className="cv-hero-copy"><h1>Know what<br />you can make.<br /><span>Before you commit.</span></h1><p>Move your next part forward with a clear view of how it can be made, what needs attention, and what it will take.</p><div className="cv-actions"><Link className="cv-button" href="/sample">Explore a sample part <ArrowUpRight size={18} aria-hidden="true" /></Link><Link className="cv-text-link" href={UPLOAD_HREF}>Use your own part <ArrowRight size={17} aria-hidden="true" /></Link></div><p className="cv-hero-footnote">Recorded sample: no account needed. Your own parts: 10 free lifetime checks after signup.</p></div>
      <figure className="cv-hero-visual"><div className="cv-visual-top"><span>From geometry to a decision</span></div><Image src="/site/sample-part.png" alt="Rendered stepped part showing the rotational shape assessed by CadVerify" width={1200} height={1000} sizes="(max-width: 700px) 100vw, 50vw" priority /><svg className="cv-hero-leader" viewBox="0 0 600 440" aria-hidden="true"><path d="M185 155 H250 L326 215" /><circle cx="326" cy="215" r="4" /></svg><div className="cv-hero-finding"><strong>Rotational geometry</strong><span>CNC turning suggested</span><span>Review findings before manufacture</span></div><figcaption>Illustrated geometry / object.stl recorded example</figcaption></figure>
    </section>

    <section className="cv-workflows cv-wrap" aria-labelledby="workflow-heading"><div className="cv-section-intro"><h2 id="workflow-heading">What’s on your desk?</h2><p>Start with the decision you need to make.</p></div><div className="cv-workflow-links">{[
      { title: "Can we make this in-house?", text: "Match the part to your equipment and see where capability is missing.", href: "/teams/in-house-manufacturing" },
      { title: "What’s holding this design back?", text: "Find process-specific issues before the next manufacturing review.", href: "/teams/design-engineering" },
      { title: "What will this part really take?", text: "Trace the hours, material and rates behind a resource estimate.", href: "/teams/cost-engineering" },
    ].map(item => <Link href={item.href} key={item.href}><h3>{item.title}<ArrowUpRight size={22} aria-hidden="true" /></h3><p>{item.text}</p><span>Explore this workflow <ArrowRight size={16} aria-hidden="true" /></span></Link>)}</div></section>

    <section className="cv-example-section cv-wrap"><div className="cv-section-intro"><h2>One part.<br />A clearer next step.</h2><p>Open the example. Look at the route, the design issues, and the cost assumptions. Decide whether the evidence answers your question.</p></div><SampleExplorer /></section>

    <section className="cv-trust-band"><div className="cv-wrap cv-trust-layout"><div><h2>You shouldn’t have to<br />take a number on faith.</h2><p>Every estimate has inputs. CadVerify keeps them in view, so your team can challenge the assumptions and make an informed call.</p><Link href="/method" className="cv-text-link">See how the evidence works <ArrowRight size={18} aria-hidden="true" /></Link></div><div className="cv-provenance-list"><div><span className="cv-source-dot" /><div><h3>Measured from the part</h3><p>Geometry, dimensions and the features behind a finding.</p></div></div><div><span className="cv-source-dot cv-source-shop" /><div><h3>Declared by your team</h3><p>Your machines, materials and rates, kept with the record.</p></div></div><div><span className="cv-source-dot cv-source-assumed" /><div><h3>Assumed until validated</h3><p>Defaults stay visible. Real outcomes tell you where the model needs work.</p></div></div></div></div></section>

    <section className="cv-get-started cv-wrap"><div className="cv-section-intro"><h2>A useful first step.<br />Then a workflow that fits.</h2><p>Start with one part. Bring in more of your team’s working context as you go.</p></div><ol className="cv-steps"><li><h3>Bring the part and the question.</h3><p>Upload STL, STEP or IGES. State the material, operating conditions and manufacturing question you need to answer.</p></li><li><h3>Review the result with your team.</h3><p>Inspect the suggested process, open the findings and check the assumptions. Engineering sign-off stays with you.</p></li><li><h3>Keep the evidence with the decision.</h3><p>Save the record, compare alternatives, and bring actual costs and outcomes back into the next review.</p></li></ol><div className="cv-fit-note"><span>Need to evaluate your own machines, rates or deployment requirements?</span><Link href="/company#pilot" className="cv-text-link">Plan a pilot with us <ArrowUpRight size={17} aria-hidden="true" /></Link></div></section>

    <section className="cv-faq cv-wrap"><h2>Before you bring<br />your first part.</h2><div>{[
      ["Can I explore before creating an account?", "Yes. The sample is public and uses a recorded example. You can inspect the manufacturing route, design findings and estimate sources without signing in. Uploading your own files requires an account. Your account includes 10 lifetime single-part checks, with no card or subscription required. Request paid access for more checks or advanced tools."],
      ["Is this a supplier quote or a production approval?", "Neither. CadVerify provides manufacturing and resource-cost evidence. Your team still reviews machine setup, material suitability, supplier qualification and engineering sign-off."],
      ["What if my team needs a different deployment?", "Use the pilot discussion to review hosted or self-hosted requirements with us. Confirm data boundaries, security expectations and system fit before sharing sensitive CAD."],
      ["What happens when the inputs aren’t complete?", "Assumptions remain visible, and missing information is called out. You can review the inputs, add your own machine or rate data, and rerun the analysis rather than treating a default as a fact."],
    ].map(([question,answer]) => <details key={question}><summary>{question}</summary><p>{answer}</p></details>)}</div></section>
    <section className="cv-close cv-wrap"><div><h2>Start with one part.<br />See what becomes clearer.</h2><p>The sample is ready when you are.</p></div><Link href="/sample" className="cv-button">Explore a sample part <ArrowUpRight size={19} aria-hidden="true" /></Link></section>
  </SiteShell>;
}
