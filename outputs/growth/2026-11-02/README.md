# ScaleCAD organic growth launch

Prepared November 2, 2026 for **https://scalecad.ai**. Implementation branch: `codex/scalecad-organic-growth`, based on `origin/main` at `bcba00eb`. The starting checkout was 709 commits behind main; findings from that old checkout were discarded. This package is an implementation and operating plan, not a claim of traffic growth or completed publication.

## The choice

Start with manufacturing engineers and in-house manufacturing teams deciding whether an existing CAD part can be made on their equipment. Use the concrete question **“Can our machines make this part, and what assumptions drive the answer?”** to connect acquisition to the product. Sourcing and cost engineering are adjacent audiences.

Traffic is an intermediate measure. The outcome is qualified visitors who complete a real part check and return, then become paid users or qualified pilot opportunities. No keyword-volume provider, Search Console export, paid acquisition data or revenue attribution was available for this work. Do not interpret the priority scores as measured search volume, difficulty or revenue forecasts.

## Implemented in this branch

| Page | Job | Next step |
|---|---|---|
| `/solutions/dfm-software` | Commercial DFM evaluation, tied to machine capabilities | Recorded sample / signup |
| `/guides/step-file-manufacturability-check` | Resolve the file-validity vs manufacturability question | DFM workflow / sample |
| `/guides/cnc-dfm-checklist` | Prepare an engineering review and RFQ | STEP guide / in-house workflow |
| `/guides/make-vs-buy-analysis` | Explain scope, equations and a reproducible example | Free calculator / DFM workflow |
| `/compare/scalecad-vs-apriori` | Fair buyer comparison with primary-source links and evaluation protocol | Sample / pilot |
| `/tools/make-vs-buy-calculator` | No-account calculation of fixed/variable cost alternatives | Guide / product signup |
| `/resources` | One discoverable hub for the above | Relevant resource |

All new pages have self-canonical URLs, specific title/description and social metadata, server-rendered content and crawlable links. The content pages include WebPage and BreadcrumbList JSON-LD with the existing CSP nonce. This does not promise a rich result. Sources and comparison limitations are visible beside the content. The sitemap lists the new routes, and no longer gives every old page a fictitious modification date on every generation. The footer links to the hub, product page and calculator. `/llms.txt` indexes public resources; it is not a ranking guarantee.

Pricing now receives the backend’s public Pro plan data. It displays the returned price when available, “Contact us” when it is not, and the monthly check allowance instead of “Keeps going.” Free-check terms on the new CTAs reuse the existing site session’s plan allowances. No discounts, guarantees, customer testimonials or certifications have been invented.

The calculator runs locally. Equal rates, identical alternatives, reversed and nonpositive crossovers, empty inputs and invalid values are covered. Cost inputs and results are neither persisted nor emitted in the new events. The exact editorial routes survive analytics URL sanitization; arbitrary slugs stay redacted. New routes do not enable session replay or visitor identification.

## Starting evidence

Connected PostHog project **654164**, named “Default project,” returned the following for October 5–November 1, 2026 (project timezone UTC), filtered to `$current_url` beginning `https://scalecad.ai/`, with configured internal/test-account exclusion enabled:

| Metric | Observed |
|---|---:|
| Visitors | 12 |
| Sessions | 28 |
| Pageviews | 226 |
| Bounce rate | 32.14% |
| Average session duration | 495.07 seconds |

This is a **consent-limited, noncanonical analytics baseline**, not total site traffic, verified human-only traffic, organic traffic, customers or market demand. At this sample size, rates are unstable. Internal-account exclusion depends on the project’s configuration. Attribution to organic search and sales still needs a separate verified report. [Open the project](https://us.posthog.com/project/654164).

The public homepage was fetched successfully at scalecad.ai. It already offers a recorded sample, free checks, a pricing page and pilot terms. The generic web reader could not access the domain, so the live site was verified through HTTP and the agent-reach Jina reader instead.

A connected Gmail search for ScaleCAD/CadVerify plus support, demo, pricing, trial or feedback, excluding the user’s sent mail and Linear notifications, returned no matching messages. That does not prove there are no customer conversations. It means this work has no first-party sales-call corpus to quote.

## Demand and page-format research

See [keyword-map.csv](keyword-map.csv) for clustered priorities. Searches were sampled on November 2; this was not a complete top-ten audit for every term or a localized rank-tracking run.

Google autocomplete returned:

- `dfm software`: software, solutions, tools, free, download and PCB variations. Explicitly exclude PCB and downloads from ScaleCAD targeting.
- `manufacturability analysis`: design-for-manufacturability analysis and “what is dfm analysis.” Group related definitions with the commercial workflow instead of making near-duplicate pages.
- `make vs buy manufacturing`: analysis, decision and strategy variations. Serve a guide plus a distinct interactive calculator.
- `cnc machining cost`: calculation, estimator, Excel and hourly-rate variations, including location-specific searches. Do not create city pages or invent shop rates.

Observed search formats and primary examples:

| Cluster | Observed format | Evidence / implication |
|---|---|---|
| DFM / manufacturability software | Product page and feature demonstration | [aPriori manufacturability](https://www.apriori.com/product-manufacturability/), [DFM Studio](https://www.dfmanalysis.com/). Lead with a concrete review workflow and sample. |
| STEP-file check | Viewer/analyzer or upload workflow | [NIST STEP analyzer](https://www.nist.gov/services-resources/software/step-file-analyzer-and-viewer), [Proto&Go STEP viewer](https://protoandgo.com/en/online-step-viewer/). Distinguish interchange validation from manufacturing review. |
| Make vs buy calculator | Interactive calculator with equations | [MFG Calcs](https://www.mfgcalcs.com/calculators/lean-manufacturing-operations/make-vs-buy), [Netray](https://netray.co/tools/make-vs-buy-calculator). Provide useful calculation before requiring an account. |
| CNC machining cost | Calculator and input explanation | [Kostira](https://kostira.com/en/tools/cnc-machining-cost-calculator). A later tool needs scope, rates and cycle-time assumptions, not invented dollar-per-part promises. |
| Costing alternatives | Comparison with named criteria | [Boothroyd Dewhurst cost modeling](https://www.dfma.com/software/cost-modeling-software-for-manufacturing.html). Source vendor claims and test identical parts before publishing performance conclusions. |

The word ScaleCAD also identifies an unrelated Jidea product in [buildingSMART’s directory](https://technical.buildingsmart.org/view/software-implementations/entry/417/). Do not claim or edit that listing. Use the scalecad.ai domain and manufacturing positioning consistently.

## 90-day execution plan

These are execution targets, not traffic forecasts. Day 1 begins at publication.

| Window | Work | Definition of done |
|---|---|---|
| Days 1–7 | Review and publish this batch; verify live metadata, mobile interactions, signup and pricing. Verify the scalecad.ai Search Console property, submit sitemap once, inspect the seven URLs. | Live 200 responses, correct canonical and rendered copy; actual indexing status recorded rather than assumed. |
| Days 8–14 | Collect five buyer interviews or real support conversations. Record exact wording, role, trigger, objection and outcome with permission. Validate the first three keyword clusters against Search Console. | Five evidence records; each query assigned to one canonical answer. |
| Days 15–30 | Record three product demos: STEP import and finding; machine capability input; calculator-to-part review. Publish one measured workflow example with file rights and limitations. Prepare five individually relevant resource pitches. | Demo completes the stated task; measurements are reproducible; outreach has a named destination and exact proposed addition. |
| Days 31–60 | Review query/page performance; improve pages with relevant impressions and positions 8–20. Add one adjacent topic only if buyer evidence supports it. Run the same task across shortlisted tools if access is available. | Edits tied to actual queries; comparison observations and input files retained; no unsupported winner claims. |
| Days 61–90 | Publish a permissioned benchmark or pilot case study if enough real outcomes exist. Repeat the most effective distribution format. Recheck comparison sources and links. | Sample, method, exclusions and results public; conversions and repeat usage measured by landing page. |

Operating capacity assumption: one founder/product expert plus a writer/operator, roughly 6–8 hours per week after the initial build. If capacity is lower, reduce cadence before reducing evidence quality.

## Measurement contract

Existing events include `$pageview`, `signup_completed`, and product events. New events are `resource_link_clicked`, `resource_signup_clicked`, and `calculator_started`. They use the current `track()` consent gate. For link clicks `$pathname` is the source and `$current_url` is the sanitized destination. Calculator starts contain only tool name and route, not inputs or computed results.

Weekly, compare the last 28 complete days with the preceding 28; use year-over-year periods when enough history exists to assess seasonality. Keep raw exports with dates, filters and timezone.

1. Search Console: non-brand impressions, clicks, CTR and position, split by query and canonical page. Brand exclusion should cover `scalecad`, `scale cad`, and legacy `cadverify` queries, reviewed manually for ambiguity.
2. PostHog: consented resource visits → sample or signup click → completed signup. Establish the real successful-analysis event before adding activation to a funnel. Do not equate an upload click with a completed useful result.
3. Commercial: reconcile paid subscriptions and qualified pilot opportunities with the originating account/landing page where consent and existing data permit. Do not treat a contact click as revenue.
4. Keep totals for impressions and visitors separate from conversion rates. Report counts beside every rate.

Decision rules: relevant impressions but few clicks → investigate title and SERP promise; visits but no product action → improve demonstration/CTA fit; signups but no successful part check → fix onboarding before expanding content; irrelevant queries → narrow the page, not more of the same traffic.

For distribution, use links such as `https://scalecad.ai/tools/make-vs-buy-calculator?utm_source=linkedin&utm_medium=organic_social&utm_campaign=make_buy_launch`. Do not tag internal links with UTMs. Existing signup attribution captures campaign fields after consent; it is not yet proof of end-to-end revenue attribution.

## Access and evidence still needed

- Search Console: verified property and query/page exports for the last 3–6 months. No connected Search Console tool was available; indexing, near-page-one terms and declining pages remain unmeasured.
- Customer evidence: real calls/support records, permissioned job actuals and a named domain reviewer. Existing sample data is a recorded product example, not a customer outcome.
- Vendor tests: lawful access to comparator products and identical input data before accuracy/speed claims or detailed migration instructions.
- Distribution: suitable signed-in publisher/company profiles and explicit authorization for messages to editors, customers or journalists. No messages, review requests or social posts were sent.
- Production publication: this branch needs the project’s normal review/release path. No production deployment, backlink acquisition or new traffic is claimed.

## Repeatable editorial job

Use `growthResources` as the current content inventory. Before adding a page, assign a buyer, decision, existing target URL, primary-source evidence and next product action. Update the existing page if the same answer already exists. Use actual revision dates in the sitemap. Keep product limits in backend-derived plan data. Never convert an assumption band into validated accuracy, a cost estimate into a supplier quote, or a missing input into a pass.

After each release: open all changed live URLs, record the release SHA, confirm canonical/OG URLs and links, then log the change against the baseline. Publish a benchmark only with its sample, method, exclusions and reproducible calculations. Do not automate external posts or recurring edits without a separately configured job.

Google’s [scaled-content policy](https://developers.google.com/search/docs/essentials/spam-policies) makes large amounts of unoriginal ranking-focused content a poor foundation. Its [sitemap guidance](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap) supports truthful modification dates. This plan uses a small connected set of useful pages and scales only after evidence of buyer fit.
