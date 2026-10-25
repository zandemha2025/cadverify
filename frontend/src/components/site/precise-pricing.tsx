import { SiteShell, SiteCta } from "./site-shell";

export function PrecisePricing() { return <SiteShell><div className="precise precise-pricing">
<section className="s-dark" style={{"position": "relative", "overflow": "hidden"}}>
<div className="horizon" aria-hidden="true" style={{"height": "600px"}}><div className="hz-glow" style={{"bottom": "-640px"}}></div><div className="hz-arc" style={{"top": "calc(100% - 110px)"}}></div></div>
<div className="wrap" style={{"position": "relative", "zIndex": 2, "paddingTop": "110px", "paddingBottom": "190px", "display": "flex", "flexDirection": "column", "alignItems": "center", "textAlign": "center", "gap": "22px"}}>
<h1 className="disp blurUp" style={{"fontSize": "clamp(52px, 7.4vw, 112px)"}}>Free to start.</h1>
<p className="blurUp b1" style={{"margin": 0, "maxWidth": "560px", "fontSize": "19px", "lineHeight": 1.55, "color": "var(--fg2)", "textWrap": "balance"}}>Try it free on your own parts. Pay monthly once it’s useful. Call us when you want it across a factory.</p>
</div>
</section>
<section className="s-light">
<div className="wrap" style={{"paddingTop": "72px", "paddingBottom": "120px"}}>
<div style={{"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(min(280px, 100%), 1fr))", "gap": "12px", "marginTop": "-150px", "position": "relative", "zIndex": 3}}>
<div className="tier " style={{}}>
<div style={{"display": "flex", "flexDirection": "column", "gap": "10px", "position": "relative"}}><span className="lbl" style={{"color": "var(--fg)"}}>Free</span><span className="disp" style={{"fontSize": "60px", "fontWeight": 200}}>$0</span><span style={{"fontSize": "15.5px", "lineHeight": 1.5, "color": "var(--fg2)", "minHeight": "70px"}}>15 checks with a work email, 3 with a personal one.</span></div>
<SiteCta className="btn btn-cta">Try ScaleCAD free</SiteCta>
<ul className="inc" style={{"position": "relative"}}><li><i></i><span>The full answer on every part</span></li><li><i></i><span>Checks 21 ways to make it</span></li><li><i></i><span>Uses your own machines and prices</span></li><li><i></i><span>Shows where every number came from</span></li></ul>
</div>
<div className="tier s-dark" style={{"position": "relative", "overflow": "hidden"}}><span aria-hidden="true" style={{"position": "absolute", "left": "-30%", "right": "-30%", "bottom": "-70%", "height": "110%", "borderRadius": "50%", "background": "radial-gradient(ellipse 50% 50% at 50% 50%, var(--a2), var(--a1) 25%, transparent 64%)", "opacity": 0.4, "filter": "blur(16px)"}}></span>
<div style={{"display": "flex", "flexDirection": "column", "gap": "10px", "position": "relative"}}><span className="lbl" style={{"color": "var(--fg)"}}>Pro</span><span className="disp" style={{"fontSize": "60px", "fontWeight": 200}}>Contact us</span><span style={{"fontSize": "15.5px", "lineHeight": 1.5, "color": "var(--fg2)", "minHeight": "70px"}}>Uses your own machines and prices.</span></div>
<a className="btn btn-cta" href="/contact" style={{"position": "relative", "width": "100%"}}>Contact us</a>
<ul className="inc" style={{"position": "relative"}}><li><i></i><span>Everything in Free</span></li><li><i></i><span>Parts made of several pieces</span></li><li><i></i><span>Fixes broken 3D files</span></li><li><i></i><span>Learns from your real costs</span></li></ul>
</div>
<div className="tier " style={{}}>
<div style={{"display": "flex", "flexDirection": "column", "gap": "10px", "position": "relative"}}><span className="lbl" style={{"color": "var(--fg)"}}>Pilot</span><span className="disp" style={{"fontSize": "60px", "fontWeight": 200}}>$7,500</span><span style={{"fontSize": "15.5px", "lineHeight": 1.5, "color": "var(--fg2)", "minHeight": "70px"}}>One factory, up to 500 parts, 4–6 weeks. Counts toward your first year.</span></div>
<a className="btn btn-ghost" href="/pilot" style={{"position": "relative", "width": "100%"}}>Plan a pilot</a>
<ul className="inc" style={{"position": "relative"}}><li><i></i><span>Sorts your whole parts list</span></li><li><i></i><span>Compared with what you pay today</span></li><li><i></i><span>Estimates tested on your real jobs</span></li><li><i></i><span>A ranked list of what to make and buy</span></li></ul>
</div>
<div className="tier " style={{}}>
<div style={{"display": "flex", "flexDirection": "column", "gap": "10px", "position": "relative"}}><span className="lbl" style={{"color": "var(--fg)"}}>Enterprise</span><span className="disp" style={{"fontSize": "60px", "fontWeight": 200}}>Custom</span><span style={{"fontSize": "15.5px", "lineHeight": 1.5, "color": "var(--fg2)", "minHeight": "70px"}}>Priced on how many sites and parts you have, after a pilot.</span></div>
<a className="btn btn-ghost" href="/contact" style={{"position": "relative", "width": "100%"}}>Talk to us</a>
<ul className="inc" style={{"position": "relative"}}><li><i></i><span>Up to 10,000 parts at a time</span></li><li><i></i><span>Sign in with your company login</span></li><li><i></i><span>Locked price lists and change history</span></li><li><i></i><span>Can run on your own servers</span></li></ul>
</div>
</div>
<div style={{"marginTop": "14px", "display": "flex", "flexWrap": "wrap", "justifyContent": "space-between", "alignItems": "center", "gap": "12px 24px", "padding": "20px 26px", "borderRadius": "20px", "background": "var(--bg2)"}}>
<span style={{"fontSize": "16px"}}><strong style={{"fontWeight": 600}}>Not sure a pilot is right?</strong> <span style={{"color": "var(--fg2)"}}>Send us 25 typical parts and we’ll tell you, free.</span></span>
<a className="btn btn-ghost btn-sm" href="/pilot">Send us 25 parts</a>
</div>
<h2 className="disp" style={{"marginTop": "120px", "fontSize": "clamp(36px, 4vw, 56px)"}}>Compare plans.</h2>
<div style={{"marginTop": "32px", "overflowX": "auto", "borderRadius": "24px", "background": "var(--card)", "padding": "22px 16px 6px"}}>
<table className="cmp">
<thead><tr><th scope="col" style={{"fontFamily": "'Instrument Sans', system-ui, sans-serif", "fontSize": "14px", "fontWeight": 600, "color": "var(--fg2)"}}>What you get</th><th scope="col">Free</th><th scope="col">Pro</th><th scope="col">Pilot</th><th scope="col">Enterprise</th></tr></thead>
<tbody><tr><th scope="row">Checks</th><td>15 work · 3 personal</td><td>Contact us</td><td>Up to 500 parts</td><td>Sized to you</td></tr><tr><th scope="row">The full answer, 21 ways to make it</th><td>Yes</td><td>Yes</td><td>Yes</td><td>Yes</td></tr><tr><th scope="row">Your own machines and prices</th><td>Yes</td><td>Yes</td><td>Yes</td><td>Yes</td></tr><tr><th scope="row">Checks materials hold up where it’s used</th><td>Yes</td><td>Yes</td><td>Yes</td><td>Yes</td></tr><tr><th scope="row">API access</th><td>Yes</td><td>Yes</td><td>Yes</td><td>Yes</td></tr><tr><th scope="row">Multi-piece parts and broken-file repair</th><td className="no">—</td><td>Yes</td><td>Yes</td><td>Yes</td></tr><tr><th scope="row">Learns from your real costs</th><td className="no">—</td><td>Yes</td><td>Yes</td><td>Yes</td></tr><tr><th scope="row">Sort a whole parts list at once</th><td className="no">—</td><td className="no">—</td><td>Yes</td><td>Up to 10,000</td></tr><tr><th scope="row">Company login and automatic user setup</th><td className="no">—</td><td className="no">—</td><td className="no">—</td><td>Yes</td></tr><tr><th scope="row">Runs on your own servers</th><td className="no">—</td><td className="no">—</td><td>Set up with you</td><td>Yes</td></tr></tbody>
</table>
</div>
</div>
</section>
<section className="s-light faq" style={{"borderTop": "1px solid var(--line)"}}>
<div className="wrap" style={{"paddingTop": "110px", "paddingBottom": "130px", "display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(min(400px, 100%), 1fr))", "gap": "32px 96px"}}>
<h2 className="disp" style={{"fontSize": "clamp(36px, 4vw, 56px)"}}>Pricing questions.</h2>
<div>
<details><summary>What happens when my free checks run out?<span className="plus"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"></path></svg></span></summary><p style={{"margin": "0 0 26px", "maxWidth": "620px", "fontSize": "17px", "lineHeight": 1.65, "color": "var(--fg2)"}}>Everything you checked stays saved. Switch to Pro to keep going, or talk to us about a pilot.</p></details>
<details><summary>Why does a work email get more checks?<span className="plus"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"></path></svg></span></summary><p style={{"margin": "0 0 26px", "maxWidth": "620px", "fontSize": "17px", "lineHeight": 1.65, "color": "var(--fg2)"}}>A personal email gets a taste. A work email gets enough to test it on real parts with your team.</p></details>
<details style={{"borderBottom": "1px solid var(--line)"}}><summary>Is the pilot fee credited?<span className="plus"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"></path></svg></span></summary><p style={{"margin": "0 0 26px", "maxWidth": "620px", "fontSize": "17px", "lineHeight": 1.65, "color": "var(--fg2)"}}>Yes. If you keep going, the $7,500 counts toward your first year.</p></details>
</div>
</div>
</section>
</div></SiteShell>; }
