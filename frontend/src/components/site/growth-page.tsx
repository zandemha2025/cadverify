import type { Metadata } from "next";
import { headers } from "next/headers";
import { SiteShell } from "./site-shell";
import { GrowthActions, GrowthLink } from "./growth-actions";
import { resourceAt, type GrowthResource } from "@/lib/site/growth-content";
import { SITE_ORIGIN } from "@/lib/site/growth-routes";
import "./growth.css";

export function growthMetadata(path: string, title: string, description: string): Metadata {
  return {
    title: `${title} | ScaleCAD`, description,
    alternates: { canonical: path },
    openGraph: { title, description, url: path, siteName: "ScaleCAD", type: "website", images: [{ url: "/opengraph-image", width: 1200, height: 630 }] },
    twitter: { card: "summary_large_image", title, description, images: ["/opengraph-image"] },
  };
}

export async function ResourceSchema({ resource }: { resource: GrowthResource }) {
  const nonce = (await headers()).get("x-nonce") || undefined;
  const url = `${SITE_ORIGIN}${resource.path}`;
  const schema = {
    "@context": "https://schema.org",
    "@graph": [
      { "@type": "WebPage", "@id": url, url, name: resource.title, description: resource.description, dateModified: resource.updated, publisher: { "@type": "Organization", name: "ScaleCAD", url: SITE_ORIGIN } },
      { "@type": "BreadcrumbList", itemListElement: [
        { "@type": "ListItem", position: 1, name: "Resources", item: `${SITE_ORIGIN}/resources` },
        { "@type": "ListItem", position: 2, name: resource.title, item: url },
      ] },
    ],
  };
  return <script nonce={nonce} type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(schema).replace(/</g, "\\u003c") }} />;
}

export async function GrowthPage({ resource }: { resource: GrowthResource }) {
  return <SiteShell><ResourceSchema resource={resource} /><article className="growth">
    <header className="growth-hero">
      <GrowthLink href="/resources" className="growth-eyebrow">Resources / {resource.category}</GrowthLink>
      <h1>{resource.title}</h1><p className="growth-intro">{resource.intro}</p>
      <p className="growth-byline"><GrowthLink href="/company">ScaleCAD</GrowthLink> · Updated <time dateTime={resource.updated}>{new Intl.DateTimeFormat("en-US", { dateStyle: "long", timeZone: "UTC" }).format(new Date(resource.updated))}</time></p>
      <GrowthActions />
    </header>
    <div className="growth-layout">
      <nav className="growth-toc" aria-label="On this page"><strong>On this page</strong>{resource.sections.map(section => <a href={`#${section.id}`} key={section.id}>{section.title}</a>)}</nav>
      <div className="growth-body">
        {resource.sections.map(section => <section id={section.id} key={section.id}>
          <h2>{section.title}</h2>
          {section.paragraphs.map(paragraph => <p key={paragraph}>{paragraph}</p>)}
          {section.items && <ul>{section.items.map(item => <li key={item}>{item}</li>)}</ul>}
          {section.table && <div className="growth-table" role="region" aria-label={section.title} tabIndex={0}><table><thead><tr>{section.table.headings.map(heading => <th scope="col" key={heading}>{heading}</th>)}</tr></thead><tbody>{section.table.rows.map(row => <tr key={row[0]}>{row.map((cell, index) => index === 0 ? <th scope="row" key={index}>{cell}</th> : <td key={index}>{cell}</td>)}</tr>)}</tbody></table></div>}
          {section.link && <GrowthLink className="growth-next" href={section.link.href}>{section.link.label} →</GrowthLink>}
        </section>)}
        <section><h2>Sources and scope</h2><p>Product details and external references checked November 2, 2026. Examples are identified where used; this page does not report a customer benchmark.</p><ul>{resource.sources.map(source => <li key={source.href}><a href={source.href}>{source.label}</a></li>)}</ul></section>
        <section className="growth-callout"><h2>Put the question to your own part.</h2><p>Inspect the sample first, then bring your CAD file and the requirements behind the decision.</p><GrowthActions /></section>
        <section><h2>Continue your review</h2><ul>{resource.related.map(path => <li key={path}><GrowthLink href={path}>{resourceAt(path)?.title ?? "Free make vs buy calculator"}</GrowthLink></li>)}</ul></section>
      </div>
    </div>
  </article></SiteShell>;
}
