"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import Image from "next/image";
import { SiteShell, SiteCta, useSiteSession } from "./site-shell";
import { HeroUpload } from "./hero-upload";
import { SignupEmailForm } from "./signup-email-form";

// Content and illustrative values ported from Main.dc.html, direction A · Precise.
export function PreciseHome() {
 const session = useSiteSession();
 const [s, update] = useState({tab: "inhouse", shop: "a", term: 0, phase: 6});
 const setState = (patch: Partial<typeof s>) => update(value => ({...value, ...patch}));
 const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
 useEffect(() => () => timers.current.forEach(clearTimeout), []);
 const onReplay = () => {
   timers.current.forEach(clearTimeout);
   if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
   setState({phase: 0});
   timers.current = Array.from({length: 6}, (_, i) => setTimeout(() => setState({phase: i + 1}), 200 + (i + 1) * 460));
 };
 const on = (n: number) => s.phase >= n ? "is-on" : "";
 const envOn=on(1), g1=on(1), g2=on(2), g3=on(3), g4=on(4), g5=on(5);
 const scanning=s.phase >= 1 && s.phase <= 4, walking=s.phase < 6;
 const replayLabel=walking ? "Checking the sample part…" : "Watch it again";
 const { freeChecks: { work: workChecks, personal: personalChecks } } = session;
 const startTitle=session.user ? "Open ScaleCAD." : "Try ScaleCAD free.";
    const tab = s.tab || 'inhouse';
    const tabDefs = [
      { id: 'inhouse', label: 'Can we make it ourselves?' },
      { id: 'design', label: 'What’s wrong with the design?' },
      { id: 'cost', label: 'What will it cost?' }
    ];
    const tabs = tabDefs.map((t) => ({
      label: t.label,
      on: t.id === tab ? 'is-on' : '',
      pressed: t.id === tab,
      pick: () => setState({ tab: t.id })
    }));

    const shop = s.shop || 'a';
    const scale = 75;
    const data = [
      { blocked: false, name: '3D printing (MJF)', note: 'Could be 40% higher or lower', a: 10.45, b: 2.68, h: 0.4 },
      { blocked: false, name: '3D printing (SLS)', note: 'Could be 40% higher or lower', a: 10.64, b: 2.86, h: 0.4 },
      { blocked: false, name: 'Lathe (CNC turning)', note: 'Best fit for the shape', a: 26.92, b: 5.96, h: 0.5 },
      { blocked: false, name: '5-axis milling', note: 'Could be 50% higher or lower', a: 47.36, b: 10.95, h: 0.5 },
      { name: 'Injection molding', note: 'Needs a design fix first', a: 14.25, b: 4.65, h: 0.6, blocked: true }
    ];
    const rows = data.map((d, i) => {
      const v = shop === 'a' ? d.a : d.b;
      const low = v * (1 - d.h);
      const high = v * (1 + d.h);
      return {
        name: d.name,
        note: d.note,
        price: '$' + v.toFixed(2),
        pointPct: (v / scale * 100).toFixed(2),
        lowPct: (low / scale * 100).toFixed(2),
        bandPct: ((high - low) / scale * 100).toFixed(2),
        cls: d.blocked ? 'is-blocked' : (i === 0 ? 'is-best' : '')
      };
    });

    const termDefs = [
      { v: '0.0682 hr', tag: 'Default', chip: 'c-default', label: 'Machine time per part', source: 'One full print run takes 15.2 hours and fits 223 parts, so each part gets about 4 minutes. The 223 is our standard guess at how many fit, so it stays marked as a guess until you give us real numbers.' },
      { v: '× $30/hr', tag: 'Shop', chip: 'c-shop', label: 'Hourly machine rate', source: 'What the example shop charges per hour for this printer. On your account, it’s your own rate.' },
      { v: '÷ 0.8', tag: 'Shop', chip: 'c-shop', label: 'Uptime', source: 'Machines run about 80% of the time. Dividing by 0.8 covers the hours they sit idle.' },
      { v: '× 1.3', tag: 'Shop', chip: 'c-shop', label: 'Margin', source: 'The shop’s 30% profit margin.' },
      { v: '× 1.15', tag: 'Shop', chip: 'c-shop', label: 'Overhead', source: 'An extra 15% for rent, power and other running costs.' },
      { v: '= $3.82', tag: '±40%', chip: 'c-default', label: 'Machine cost per part', source: 'Multiply it all out and you get $3.82 a part. It could be 40% higher or lower until real jobs confirm it.' }
    ];
    const termIdx = s.term ?? 0;
    const terms = termDefs.map((t, i) => ({
      v: t.v, tag: t.tag, chip: t.chip, label: t.label, source: t.source,
      on: i === termIdx ? 'is-on' : '',
      isOn: i === termIdx,
      pressed: i === termIdx,
      pick: () => setState({ term: i })
    }));


 const isInhouse=tab === "inhouse", isDesign=tab === "design", isCost=tab === "cost";
 const segPos=shop === "b" ? "is-b" : "";
 const shopAOn=shop === "a" ? "is-on" : "", shopBOn=shop === "b" ? "is-on" : "";
 const shopAPressed=shop === "a", shopBPressed=shop === "b";
 const pickA=()=>setState({shop:"a"}), pickB=()=>setState({shop:"b"});

return <SiteShell><div className="precise">
<section className="studio" style={{"overflow": "hidden"}}>
<div className="wrap" style={{"display": "flex", "flexWrap": "wrap", "alignItems": "center", "gap": "48px 40px", "paddingTop": "72px", "paddingBottom": "120px"}}>
<div style={{"flex": "1 1 440px", "minWidth": 0, "position": "relative", "zIndex": 2, "display": "flex", "flexDirection": "column", "gap": "32px"}}>
<h1 className="display rise" style={{"margin": 0, "fontWeight": 500, "fontSize": "clamp(64px, 8vw, 96px)", "lineHeight": 0.92, "letterSpacing": "-0.04em"}}>Can you<br />make it?</h1>
<p className="rise d1" style={{"margin": 0, "maxWidth": "500px", "fontSize": "20px", "lineHeight": 1.55, "color": "#3A3F3C", "textWrap": "pretty"}}>Upload a 3D model of a part. ScaleCAD tells you whether your machines can make it, which materials will hold up, how long it takes and what it costs. Every number shows where it came from.</p>
<div className="rise d2" style={{"display": "flex", "flexDirection": "column", "gap": "16px", "alignItems": "flex-start"}}>
<div style={{"display": "flex", "flexWrap": "wrap", "gap": "12px"}}>
<SiteCta className="btn btn-signal">Try ScaleCAD free <svg className="arr" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"></path></svg></SiteCta>
<a className="btn btn-ghost" href="#desk">View sample output</a>
</div>
<p style={{"margin": 0, "fontSize": "14px", "color": "#5A605D"}}>{workChecks} free checks with a work email, {personalChecks} with a personal email. No credit card.</p>
</div>
</div>

<div className="stage" style={{"flex": "1.45 1 560px", "minWidth": 0}}>
<HeroUpload><figure className="fig">
<span aria-hidden="true" style={{"position": "absolute", "left": "33%", "top": "73%", "width": "34%", "height": "9%", "background": "radial-gradient(closest-side, rgba(13,15,14,0.2), rgba(13,15,14,0))"}}></span>
<Image src="/site/sample-part.png" alt="The sample part, a small round fitting about 2 cm across, inside a box showing its measured size" style={{"position": "absolute", "inset": 0, "width": "100%", "height": "100%", "objectFit": "cover"}} width="1200" height="1000" priority sizes="(max-width: 900px) 100vw, 60vw" />
<svg viewBox="0 0 1200 1000" preserveAspectRatio="xMidYMid slice" aria-hidden="true" style={{"position": "absolute", "inset": 0, "width": "100%", "height": "100%"}}>
<path className={`env ${envOn}`} pathLength="1" d="M602 200 L862 350 L862 650 L602 800 L342 650 L342 350 Z" fill="none" stroke="#0D0F0E" strokeOpacity="0.55" strokeWidth="1.2" vectorEffect="non-scaling-stroke"></path>
<path className={`env ${envOn}`} pathLength="1" d="M342 350 L602 500 L862 350 M602 500 L602 800" fill="none" stroke="#0D0F0E" strokeOpacity="0.3" strokeWidth="1" vectorEffect="non-scaling-stroke"></path>
<g className={`reveal ${envOn}`}>
<path d="M322 685 L582 835 M330 678 L314 692 M590 828 L574 842 M622 835 L882 685 M614 828 L630 842 M874 678 L890 692 M910 650 L910 350 M900 650 L920 650 M900 350 L920 350" fill="none" stroke="#0D0F0E" strokeWidth="1.2" vectorEffect="non-scaling-stroke"></path>
<g fontFamily="var(--font-martian-mono), monospace" fontSize="19" fill="#0D0F0E">
<text x="430" y="800" transform="rotate(30 430 800)" textAnchor="middle">21.16 mm</text>
<text x="774" y="800" transform="rotate(-30 774 800)" textAnchor="middle">21.48 mm</text>
<text x="944" y="500" transform="rotate(-90 944 500)" textAnchor="middle">21.43 mm</text>
</g>
</g>
<g className={`reveal ${g3}`}>
<circle cx="486" cy="640" r="7" fill="#FF5B1F"></circle>
<circle cx="486" cy="640" r="16" fill="none" stroke="#FF5B1F" strokeOpacity="0.45" strokeWidth="1.2" vectorEffect="non-scaling-stroke"></circle>
<path d="M470 640 H250" stroke="#FF5B1F" strokeWidth="1.2" vectorEffect="non-scaling-stroke"></path>
</g>
</svg>
<span className={`reveal callout ${g3}`} style={{"position": "absolute", "left": "6%", "top": "61.6%", "display": "flex", "flexDirection": "column", "gap": "3px", "padding": "8px 11px", "borderRadius": "10px", "background": "#FFFFFF", "boxShadow": "0 0 0 1px rgba(194,65,12,0.25), 0 8px 20px -12px rgba(13,15,14,0.4)"}}>
<span style={{"fontSize": "11.5px", "fontWeight": 600, "color": "#9A3A0E"}}>Can’t be molded as drawn</span>
<span style={{"fontSize": "13px", "fontWeight": 600, "maxWidth": "190px"}}>This wall is too straight to slide out of a mold</span>
</span>
{scanning && <>
<div className="scan" aria-hidden="true" style={{"position": "absolute", "left": "26%", "right": "26%", "top": "18%", "height": "66%", "pointerEvents": "none"}}>
<div style={{"height": "1.5px", "background": "linear-gradient(90deg, rgba(255,91,31,0), #FF5B1F 20%, #FF5B1F 80%, rgba(255,91,31,0))"}}></div>
</div>
</> }
<figcaption className="mono" style={{"position": "absolute", "left": "22%", "top": "5%", "fontSize": "11px", "color": "#474D4A"}}>Sample part · about 2 cm across</figcaption>



</figure>

<div className="rail rise d2">
<div className="rail-grid">
<div className={`gcell ${g1}`}><span className="mono num" style={{"fontSize": "11px", "color": "#5A605D"}}>01</span><span style={{"fontSize": "15px", "fontWeight": 600}}>Fits your machines?</span><span className="pill c-wait" style={{"alignSelf": "flex-start"}}>Add your machines</span></div>
<div className={`gcell ${g2}`}><span className="mono num" style={{"fontSize": "11px", "color": "#5A605D"}}>02</span><span style={{"fontSize": "15px", "fontWeight": 600}}>Right material?</span><span className="pill c-wait" style={{"alignSelf": "flex-start"}}>Add where it’s used</span></div>
<div className={`gcell ${g3}`}><span className="mono num" style={{"fontSize": "11px", "color": "#5A605D"}}>03</span><span style={{"fontSize": "15px", "fontWeight": 600}}>Can it be made?</span><span className="pill c-warn" style={{"alignSelf": "flex-start"}}>Yes, on a lathe</span></div>
<div className={`gcell ${g4}`}><span className="mono num" style={{"fontSize": "11px", "color": "#5A605D"}}>04</span><span style={{"fontSize": "15px", "fontWeight": 600}}>How long?</span><span className="pill c-shop" style={{"alignSelf": "flex-start"}}>About 4 min each</span></div>
<div className={`gcell ${g5}`}><span className="mono num" style={{"fontSize": "11px", "color": "#5A605D"}}>05</span><span style={{"fontSize": "15px", "fontWeight": 600}}>What it costs</span><span className="pill c-default" style={{"alignSelf": "flex-start"}}>About $14.14 each</span></div>
</div>
<div style={{"display": "flex", "flexWrap": "wrap", "justifyContent": "space-between", "alignItems": "center", "gap": "10px 20px", "padding": "14px 18px", "borderTop": "1px solid #EEF0EC"}}>

<button className="tlink" type="button" onClick={onReplay} disabled={walking} style={{"fontSize": "14px"}}><svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M2.5 8a5.5 5.5 0 1 0 1.8-4.1M2.5 2.5v3h3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"></path></svg>{replayLabel}</button>
</div>
</div>
</HeroUpload>
</div>
</div>
</section>

<section aria-label="Processes ScaleCAD checks" className="marquee-wrap" style={{"background": "#0D0F0E", "color": "#F4F5F2", "overflow": "hidden"}}>
<div style={{"display": "flex", "alignItems": "center", "gap": 0, "height": "84px"}}>
<div style={{"flex": "none", "position": "relative", "zIndex": 1, "height": "100%", "display": "flex", "alignItems": "center", "padding": "0 28px 0 40px", "background": "#0D0F0E", "boxShadow": "24px 0 24px -8px #0D0F0E"}}><span className="display" style={{"fontSize": "20px", "fontWeight": 500, "letterSpacing": "-0.02em", "whiteSpace": "nowrap"}}>Checks 21 ways to make a part</span></div>
<div style={{"flex": 1, "minWidth": 0, "overflow": "hidden"}}>
<div className="marquee">
<ul style={{"display": "flex", "alignItems": "center", "gap": "36px", "margin": 0, "padding": "0 36px 0 0", "listStyle": "none", "fontSize": "17px", "color": "#B9BEBA", "whiteSpace": "nowrap"}}>
<li>CNC turning</li><li>CNC 3-axis</li><li>CNC 5-axis</li><li>Wire EDM</li><li>MJF</li><li>SLS</li><li>DMLS</li><li>SLM</li><li>EBM</li><li>FDM</li><li>SLA</li><li>DLP</li><li>Binder jetting</li><li>DED</li><li>WAAM</li><li>Injection molding</li><li>Die casting</li><li>Investment casting</li><li>Sand casting</li><li>Sheet metal</li><li>Forging</li>
</ul>
<ul aria-hidden="true" style={{"display": "flex", "alignItems": "center", "gap": "36px", "margin": 0, "padding": "0 36px 0 0", "listStyle": "none", "fontSize": "17px", "color": "#B9BEBA", "whiteSpace": "nowrap"}}>
<li>CNC turning</li><li>CNC 3-axis</li><li>CNC 5-axis</li><li>Wire EDM</li><li>MJF</li><li>SLS</li><li>DMLS</li><li>SLM</li><li>EBM</li><li>FDM</li><li>SLA</li><li>DLP</li><li>Binder jetting</li><li>DED</li><li>WAAM</li><li>Injection molding</li><li>Die casting</li><li>Investment casting</li><li>Sand casting</li><li>Sheet metal</li><li>Forging</li>
</ul>
</div>
</div>
</div>
</section>

<section id="desk" className="sec" style={{"scrollMarginTop": "72px"}}>
<div className="wrap">
<div style={{"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(min(460px, 100%), 1fr))", "gap": "28px 80px", "alignItems": "end"}}>
<h2 className="h2">What do you need to know?</h2>
<p className="lede" style={{"maxWidth": "520px"}}>Pick a question. The answers come from a real run on the sample part, using an example shop’s prices.</p>
</div>
<div className="inview" role="group" aria-label="Choose a question" style={{"display": "flex", "flexWrap": "wrap", "gap": "10px", "marginTop": "56px"}}>
{tabs.map((tab, index) => <Fragment key={index}>
<button type="button" className={`qtab ${tab.on}`} aria-pressed={tab.pressed} onClick={tab.pick}>{tab.label}</button>
</Fragment>)}
</div>
<div className="inview" style={{"marginTop": "20px", "background": "#FFFFFF", "borderRadius": "28px", "boxShadow": "0 0 0 1px #E2E4E0, 0 40px 80px -60px rgba(13,15,14,0.35)", "padding": "clamp(28px, 4vw, 56px)", "minHeight": "460px"}} aria-live="polite">

{isInhouse && <>
<div className="panel-in" style={{"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(min(400px, 100%), 1fr))", "gap": "48px 72px"}}>
<div style={{"display": "flex", "flexDirection": "column", "gap": "20px"}}>
<h3 className="display" style={{"margin": 0, "fontSize": "clamp(30px, 3vw, 44px)", "fontWeight": 500, "letterSpacing": "-0.035em", "lineHeight": 1.05, "textWrap": "balance"}}>A lathe can make it. Can yours?</h3>
<p className="lede" style={{"fontSize": "17px"}}>The part is round, so the best way to make it is on a lathe. Tell ScaleCAD which machines you have and it checks the part’s size, about 2 cm each way, against every one. If it’s missing information, it says “unknown” instead of guessing yes.</p>
<SiteCta className="tlink">Check it against your machines <svg className="arr" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"></path></svg></SiteCta>
</div>
<div style={{"display": "flex", "flexDirection": "column"}}>
<span className="label" style={{"paddingBottom": "12px"}}>How well each method suits this shape</span>
<div style={{"display": "grid", "gridTemplateColumns": "minmax(0, 1fr) 140px auto", "gap": "16px", "alignItems": "center", "padding": "14px 0", "borderTop": "1px solid #EEF0EC"}}><span style={{"fontWeight": 600}}>Lathe (CNC turning)</span><span style={{"height": "6px", "borderRadius": "6px", "background": "#EEF0EC", "overflow": "hidden"}}><span className="grow" style={{"display": "block", "height": "100%", "width": "90%", "background": "#0D0F0E"}}></span></span><span className="pill c-warn">Works, with notes</span></div>
<div style={{"display": "grid", "gridTemplateColumns": "minmax(0, 1fr) 140px auto", "gap": "16px", "alignItems": "center", "padding": "14px 0", "borderTop": "1px solid #EEF0EC"}}><span style={{"fontWeight": 600}}>3D printing (MJF)</span><span style={{"height": "6px", "borderRadius": "6px", "background": "#EEF0EC", "overflow": "hidden"}}><span className="grow" style={{"display": "block", "height": "100%", "width": "90%", "background": "#0D0F0E"}}></span></span><span className="pill c-warn">Works, with notes</span></div>
<div style={{"display": "grid", "gridTemplateColumns": "minmax(0, 1fr) 140px auto", "gap": "16px", "alignItems": "center", "padding": "14px 0", "borderTop": "1px solid #EEF0EC"}}><span style={{"fontWeight": 600}}>5-axis milling</span><span style={{"height": "6px", "borderRadius": "6px", "background": "#EEF0EC", "overflow": "hidden"}}><span className="grow" style={{"display": "block", "height": "100%", "width": "80%", "background": "#0D0F0E"}}></span></span><span className="pill c-warn">Works, with notes</span></div>
<div style={{"display": "grid", "gridTemplateColumns": "minmax(0, 1fr) 140px auto", "gap": "16px", "alignItems": "center", "padding": "14px 0", "borderTop": "1px solid #EEF0EC"}}><span style={{"fontWeight": 600}}>3-axis milling</span><span style={{"height": "6px", "borderRadius": "6px", "background": "#EEF0EC"}}></span><span className="pill c-block">No: tool can’t reach</span></div>
<div style={{"display": "grid", "gridTemplateColumns": "minmax(0, 1fr) 140px auto", "gap": "16px", "alignItems": "center", "padding": "14px 0", "borderTop": "1px solid #EEF0EC", "borderBottom": "1px solid #EEF0EC"}}><span style={{"fontWeight": 600}}>Injection molding</span><span style={{"height": "6px", "borderRadius": "6px", "background": "#EEF0EC"}}></span><span className="pill c-block">No: wall too straight</span></div>
<span style={{"paddingTop": "12px", "fontSize": "13.5px", "color": "#5A605D"}}>Longer bar, better fit. Scores run from 0 to 1.</span>
</div>
</div>
</> }

{isDesign && <>
<div className="panel-in" style={{"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(min(400px, 100%), 1fr))", "gap": "48px 72px"}}>
<div style={{"display": "flex", "flexDirection": "column", "gap": "20px"}}>
<h3 className="display" style={{"margin": 0, "fontSize": "clamp(30px, 3vw, 44px)", "fontWeight": 500, "letterSpacing": "-0.035em", "lineHeight": 1.05, "textWrap": "balance"}}>Two problems. Neither one stops a lathe.</h3>
<p className="lede" style={{"fontSize": "17px"}}>ScaleCAD checks the design against each way of making it. A problem for one method doesn’t rule out the others. Fix the design or pick another method, then check again.</p>
</div>
<div style={{"display": "flex", "flexDirection": "column", "gap": "12px"}}>
<div style={{"padding": "22px 24px", "borderRadius": "18px", "background": "#FBF6EC", "display": "flex", "flexDirection": "column", "gap": "8px"}}>
<span style={{"display": "flex", "justifyContent": "space-between", "gap": "12px", "alignItems": "center"}}><span style={{"fontWeight": 600, "fontSize": "17px"}}>Injection molding</span><span className="pill c-block">Stops molding</span></span>
<span style={{"fontSize": "16px", "color": "#3A3F3C"}}>One wall is too straight to slide out of a mold. It needs at least a 1° angle.</span>
<span style={{"fontSize": "14.5px", "color": "#5A605D"}}>Fix: angle that wall slightly, or don’t mold it.</span>
</div>
<div style={{"padding": "22px 24px", "borderRadius": "18px", "background": "#FBF6EC", "display": "flex", "flexDirection": "column", "gap": "8px"}}>
<span style={{"display": "flex", "justifyContent": "space-between", "gap": "12px", "alignItems": "center"}}><span style={{"fontWeight": 600, "fontSize": "17px"}}>3-axis milling</span><span className="pill c-block">Stops 3-axis</span></span>
<span style={{"fontSize": "16px", "color": "#3A3F3C"}}>The cutting tool can’t reach about 6 in 10 of the part’s surfaces from above.</span>
<span style={{"fontSize": "14.5px", "color": "#5A605D"}}>Fix: use a lathe or a 5-axis mill.</span>
</div>
</div>
</div>
</> }

{isCost && <>
<div className="panel-in" style={{"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(min(400px, 100%), 1fr))", "gap": "48px 72px"}}>
<div style={{"display": "flex", "flexDirection": "column", "gap": "20px"}}>
<h3 className="display" style={{"margin": 0, "fontSize": "clamp(30px, 3vw, 44px)", "fontWeight": 500, "letterSpacing": "-0.035em", "lineHeight": 1.05, "textWrap": "balance"}}>$14.14 a part. Here’s where it goes.</h3>
<p className="lede" style={{"fontSize": "17px"}}>3D-printed in plastic, 10 at a time: about 4 minutes of machine time and 4 grams of material each. Until it’s checked against real jobs, the true cost could land anywhere from $8.49 to $19.80.</p>
</div>
<div style={{"display": "flex", "flexDirection": "column", "gap": "18px"}}>
<div style={{"display": "flex", "height": "16px", "borderRadius": "999px", "overflow": "hidden", "background": "#EEF0EC"}} role="img" aria-label="Where the money goes: labor 45%, setup 27%, machine time 27%, material under 1%">
<span className="grow" style={{"width": "45.2%", "background": "#0D0F0E"}}></span>
<span className="grow" style={{"width": "27.5%", "background": "#5A605D", "animationDelay": "220ms"}}></span>
<span className="grow" style={{"width": "27%", "background": "#A9AEAA", "animationDelay": "320ms"}}></span>
<span className="grow" style={{"width": "0.3%", "background": "#FF5B1F", "animationDelay": "420ms"}}></span>
</div>
<dl style={{"margin": 0, "display": "flex", "flexDirection": "column"}}>
<div style={{"display": "grid", "gridTemplateColumns": "14px minmax(0, 1fr) auto auto", "gap": "14px", "alignItems": "center", "padding": "13px 0", "borderTop": "1px solid #EEF0EC"}}><span style={{"width": "10px", "height": "10px", "borderRadius": "3px", "background": "#0D0F0E"}}></span><dt style={{"fontSize": "15.5px"}}>Labor</dt><dd style={{"margin": 0}}><span className="chip c-shop">Shop</span></dd><dd className="num" style={{"margin": 0, "fontWeight": 600, "minWidth": "56px", "textAlign": "right"}}>$6.39</dd></div>
<div style={{"display": "grid", "gridTemplateColumns": "14px minmax(0, 1fr) auto auto", "gap": "14px", "alignItems": "center", "padding": "13px 0", "borderTop": "1px solid #EEF0EC"}}><span style={{"width": "10px", "height": "10px", "borderRadius": "3px", "background": "#5A605D"}}></span><dt style={{"fontSize": "15.5px"}}>Setup, shared across 10 parts</dt><dd style={{"margin": 0}}><span className="chip c-shop">Shop</span></dd><dd className="num" style={{"margin": 0, "fontWeight": 600, "minWidth": "56px", "textAlign": "right"}}>$3.89</dd></div>
<div style={{"display": "grid", "gridTemplateColumns": "14px minmax(0, 1fr) auto auto", "gap": "14px", "alignItems": "center", "padding": "13px 0", "borderTop": "1px solid #EEF0EC"}}><span style={{"width": "10px", "height": "10px", "borderRadius": "3px", "background": "#A9AEAA"}}></span><dt style={{"fontSize": "15.5px"}}>Machine time</dt><dd style={{"margin": 0}}><span className="chip c-shop">Shop</span></dd><dd className="num" style={{"margin": 0, "fontWeight": 600, "minWidth": "56px", "textAlign": "right"}}>$3.82</dd></div>
<div style={{"display": "grid", "gridTemplateColumns": "14px minmax(0, 1fr) auto auto", "gap": "14px", "alignItems": "center", "padding": "13px 0", "borderTop": "1px solid #EEF0EC", "borderBottom": "1px solid #EEF0EC"}}><span style={{"width": "10px", "height": "10px", "borderRadius": "3px", "background": "#FF5B1F"}}></span><dt style={{"fontSize": "15.5px"}}>Material</dt><dd style={{"margin": 0}}><span className="chip c-shop">Shop</span></dd><dd className="num" style={{"margin": 0, "fontWeight": 600, "minWidth": "56px", "textAlign": "right"}}>$0.04</dd></div>
</dl>
</div>
</div>
</> }
</div>
</div>
</section>

<section style={{"background": "#FFFFFF", "borderTop": "1px solid #E6E8E4", "borderBottom": "1px solid #E6E8E4"}}>
<div className="wrap sec">
<div style={{"display": "flex", "flexDirection": "column", "gap": "28px"}}>
<h2 className="h2">Same part. Two shops.<br />Up to 4.5 times the price.</h2>
<p className="lede" style={{"maxWidth": "640px"}}>The shape decides how a part can be made. Who makes it decides the price. Flip between two example price lists, both for an order of 1,000. That’s why ScaleCAD uses your prices, not an average.</p>
</div>
<div className="inview" style={{"marginTop": "56px", "display": "flex", "flexDirection": "column", "gap": "32px"}}>
<div className="seg" role="group" aria-label="Price list">
<span className={`seg-ind ${segPos}`} aria-hidden="true"></span>
<button type="button" className={shopAOn} aria-pressed={shopAPressed} onClick={pickA}>US Midwest example prices</button>
<button type="button" className={shopBOn} aria-pressed={shopBPressed} onClick={pickB}>Shenzhen example prices</button>
</div>
<div>
{rows.map((r, index) => <Fragment key={index}>
<div className={`rp-row ${r.cls}`}>
<span style={{"display": "flex", "flexDirection": "column", "gap": "4px"}}><span style={{"fontWeight": 600, "fontSize": "16px"}}>{r.name}</span><span style={{"fontSize": "13.5px", "color": "#5A605D"}}>{r.note}</span></span>
<span className="rp-track" aria-hidden="true"><span className="rp-axis"></span><span className="rp-band" style={{"left": `${r.lowPct}%`, "width": `${r.bandPct}%`}}></span><span className="rp-dot" style={{"left": `${r.pointPct}%`}}></span></span>
<span className="display num" style={{"fontSize": "26px", "fontWeight": 500, "letterSpacing": "-0.02em", "textAlign": "right"}}>{r.price}</span>
</div>
</Fragment>)}
<div style={{"display": "grid", "gridTemplateColumns": "200px minmax(0, 1fr) 96px", "gap": "28px", "borderTop": "1px solid #E6E8E4", "paddingTop": "10px"}} aria-hidden="true" className="hide-sm">
<span></span>
<span className="mono num" style={{"display": "flex", "justifyContent": "space-between", "fontSize": "11px", "color": "#5A605D"}}><span>$0</span><span>$25</span><span>$50</span><span>$75</span></span>
<span></span>
</div>
</div>
<p style={{"margin": 0, "fontSize": "14.5px", "lineHeight": 1.55, "color": "#5A605D", "maxWidth": "760px"}}>Each dot is the best estimate for one part. The bar shows how far off it could be until real jobs confirm it. Orange marks the cheapest option that works today.</p>
</div>
</div>
</section>

<section className="sec">
<div className="wrap">
<div style={{"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(min(460px, 100%), 1fr))", "gap": "28px 80px", "alignItems": "end"}}>
<h2 className="h2">Every number shows its work.</h2>
<p className="lede" style={{"maxWidth": "520px"}}>No mystery totals. Tap any piece of this sum to see where it came from, so your team can question the inputs, not just the answer.</p>
</div>
<div className="inview" style={{"marginTop": "56px", "background": "#FFFFFF", "borderRadius": "28px", "boxShadow": "0 0 0 1px #E2E4E0", "padding": "clamp(16px, 2.4vw, 28px)"}}>
<div style={{"display": "flex", "flexWrap": "wrap", "justifyContent": "space-between", "gap": "8px 24px", "padding": "8px 16px 20px"}}>
<span style={{"fontSize": "14.5px", "fontWeight": 600}}>Machine cost for one sample part, 3D-printed 10 at a time</span>
<span style={{"fontSize": "14.5px", "color": "#5A605D"}}>Not yet checked against real jobs</span>
</div>
<div role="group" aria-label="Pieces of the sum" style={{"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(min(176px, 100%), 1fr))", "gap": "6px"}}>
{terms.map((t, index) => <Fragment key={index}>
<button type="button" className={`term ${t.on}`} aria-pressed={t.pressed} onClick={t.pick}>
<span className="term-v num">{t.v}</span>
<span className="term-bar"></span>
<span style={{"display": "flex", "alignItems": "center", "gap": "8px", "flexWrap": "wrap"}}><span className={`chip ${t.chip}`}>{t.tag}</span><span style={{"fontSize": "14px", "color": "#474D4A"}}>{t.label}</span></span>
</button>
</Fragment>)}
</div>
<div aria-live="polite" style={{"marginTop": "8px", "padding": "22px 16px 10px", "borderTop": "1px solid #EEF0EC", "minHeight": "96px"}}>
{terms.map((t, index) => <Fragment key={index}>
{t.isOn && <>
<div className="panel-in" style={{"display": "flex", "flexDirection": "column", "gap": "8px", "maxWidth": "820px"}}>
<span style={{"fontSize": "17px", "fontWeight": 600}}>{t.label} · {t.v}</span>
<span style={{"fontSize": "16px", "lineHeight": 1.6, "color": "#474D4A"}}>{t.source}</span>
</div>
</> }
</Fragment>)}
</div>
</div>
<div className="inview" style={{"marginTop": "56px", "display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(min(200px, 100%), 1fr))", "gap": "24px"}}>
<div style={{"display": "flex", "flexDirection": "column", "gap": "12px", "paddingTop": "20px", "borderTop": "1px solid #DDE0DB"}}><span className="chip c-measured" style={{"alignSelf": "flex-start"}}>Measured</span><span style={{"fontSize": "15px", "lineHeight": 1.5, "color": "#474D4A"}}>Measured straight from the 3D file</span></div>
<div style={{"display": "flex", "flexDirection": "column", "gap": "12px", "paddingTop": "20px", "borderTop": "1px solid #DDE0DB"}}><span className="chip c-cad" style={{"alignSelf": "flex-start"}}>CAD</span><span style={{"fontSize": "15px", "lineHeight": 1.5, "color": "#474D4A"}}>Read from details saved in the CAD file</span></div>
<div style={{"display": "flex", "flexDirection": "column", "gap": "12px", "paddingTop": "20px", "borderTop": "1px solid #DDE0DB"}}><span className="chip c-shop" style={{"alignSelf": "flex-start"}}>Shop</span><span style={{"fontSize": "15px", "lineHeight": 1.5, "color": "#474D4A"}}>From your shop’s machines, prices and materials</span></div>
<div style={{"display": "flex", "flexDirection": "column", "gap": "12px", "paddingTop": "20px", "borderTop": "1px solid #DDE0DB"}}><span className="chip c-user" style={{"alignSelf": "flex-start"}}>User</span><span style={{"fontSize": "15px", "lineHeight": 1.5, "color": "#474D4A"}}>Something you typed in for this check</span></div>
<div style={{"display": "flex", "flexDirection": "column", "gap": "12px", "paddingTop": "20px", "borderTop": "1px solid #DDE0DB"}}><span className="chip c-default" style={{"alignSelf": "flex-start"}}>Default</span><span style={{"fontSize": "15px", "lineHeight": 1.5, "color": "#474D4A"}}>A standard guess, clearly marked until you replace it</span></div>
</div>
</div>
</section>

<section id="platform" className="sec" style={{"paddingTop": 0, "scrollMarginTop": "72px"}}>
<div className="wrap" style={{"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(min(420px, 100%), 1fr))", "gap": "48px 96px", "alignItems": "start"}}>
<div className="sticky" style={{"position": "sticky", "top": "120px", "display": "flex", "flexDirection": "column", "gap": "22px", "maxWidth": "560px"}}>
<h2 className="h2">One part today.<br />Every part next.</h2>
<p className="lede">Run the same check on your whole parts list, and keep every answer on file.</p>
</div>
<div style={{"borderBottom": "1px solid #DDE0DB"}}>
<a className="prow inview" href="/platform">
<span style={{"display": "flex", "flexDirection": "column", "gap": "10px"}}><span className="display prow-t" style={{"fontSize": "26px", "fontWeight": 600, "letterSpacing": "-0.025em", "lineHeight": 1.15}}>Sort up to 10,000 parts at once</span><span style={{"fontSize": "16px", "lineHeight": 1.6, "color": "#474D4A"}}>Upload a zip file. Each part lands in a pile: make it ourselves, buy it, needs new equipment, can’t be made, or not enough info.</span></span>
<svg className="prow-art" width="120" height="64" viewBox="0 0 120 64" fill="none" aria-hidden="true"><rect x="1" y="1" width="22" height="62" rx="3" stroke="#0D0F0E" strokeWidth="1.4"></rect><rect x="25" y="17" width="22" height="46" rx="3" stroke="#0D0F0E" strokeWidth="1.4"></rect><rect x="49" y="29" width="22" height="34" rx="3" stroke="#FF5B1F" strokeWidth="1.4"></rect><rect x="73" y="41" width="22" height="22" rx="3" stroke="#0D0F0E" strokeWidth="1.4"></rect><rect x="97" y="49" width="22" height="14" rx="3" stroke="#0D0F0E" strokeWidth="1.4" strokeDasharray="3 3"></rect></svg>
</a>
<a className="prow inview" href="/platform">
<span style={{"display": "flex", "flexDirection": "column", "gap": "10px"}}><span className="display prow-t" style={{"fontSize": "26px", "fontWeight": 600, "letterSpacing": "-0.025em", "lineHeight": 1.15}}>See what each product line is worth</span><span style={{"fontSize": "16px", "lineHeight": 1.6, "color": "#474D4A"}}>Group parts by product, add how many you build a year, and see the money riding on each make-or-buy call.</span></span>
<svg className="prow-art" width="120" height="64" viewBox="0 0 120 64" fill="none" aria-hidden="true"><circle cx="12" cy="32" r="10" stroke="#0D0F0E" strokeWidth="1.4"></circle><path d="M22 32h22M44 12v40M44 12h20M44 32h20M44 52h20" stroke="#0D0F0E" strokeWidth="1.4"></path><rect x="64" y="4" width="54" height="16" rx="3" stroke="#0D0F0E" strokeWidth="1.4"></rect><rect x="64" y="24" width="54" height="16" rx="3" stroke="#FF5B1F" strokeWidth="1.4"></rect><rect x="64" y="44" width="54" height="16" rx="3" stroke="#0D0F0E" strokeWidth="1.4"></rect></svg>
</a>
<a className="prow inview" href="/platform">
<span style={{"display": "flex", "flexDirection": "column", "gap": "10px"}}><span className="display prow-t" style={{"fontSize": "26px", "fontWeight": 600, "letterSpacing": "-0.025em", "lineHeight": 1.15}}>Keep every answer on file</span><span style={{"fontSize": "16px", "lineHeight": 1.6, "color": "#474D4A"}}>Every check is saved and shareable. Compare decisions side by side, and feed back real costs to make future estimates sharper.</span></span>
<svg className="prow-art" width="120" height="64" viewBox="0 0 120 64" fill="none" aria-hidden="true"><rect x="22" y="2" width="76" height="44" rx="4" stroke="#0D0F0E" strokeWidth="1.4" strokeOpacity="0.35"></rect><rect x="14" y="10" width="76" height="44" rx="4" stroke="#0D0F0E" strokeWidth="1.4" strokeOpacity="0.6" fill="#F4F5F2"></rect><rect x="6" y="18" width="76" height="44" rx="4" stroke="#0D0F0E" strokeWidth="1.4" fill="#F4F5F2"></rect><path d="M16 46h56" stroke="#0D0F0E" strokeWidth="1.4" strokeDasharray="3 3"></path><path d="M16 36h40" stroke="#FF5B1F" strokeWidth="2.4" strokeLinecap="round"></path></svg>
</a>
<a className="prow inview" href="/platform">
<span style={{"display": "flex", "flexDirection": "column", "gap": "10px"}}><span className="display prow-t" style={{"fontSize": "26px", "fontWeight": 600, "letterSpacing": "-0.025em", "lineHeight": 1.15}}>Fits your IT setup</span><span style={{"fontSize": "16px", "lineHeight": 1.6, "color": "#474D4A"}}>Connect through an API, let people sign in with their company login (SAML or OIDC), and add or remove users automatically (SCIM).</span></span>
<svg className="prow-art" width="120" height="64" viewBox="0 0 120 64" fill="none" aria-hidden="true"><rect x="30" y="26" width="60" height="36" rx="6" stroke="#0D0F0E" strokeWidth="1.4"></rect><path d="M42 26v-8a18 18 0 0 1 36 0v8" stroke="#0D0F0E" strokeWidth="1.4"></path><circle cx="60" cy="42" r="4" stroke="#FF5B1F" strokeWidth="1.4"></circle><path d="M60 46v6" stroke="#FF5B1F" strokeWidth="1.4" strokeLinecap="round"></path></svg>
</a>
</div>
</div>
</section>

<section className="sec" style={{"paddingTop": 0}}>
<div className="wrap">
<div className="inview" style={{"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(min(260px, 100%), 1fr))", "borderRadius": "28px", "overflow": "hidden", "background": "#FFFFFF", "boxShadow": "0 0 0 1px #E2E4E0"}}>
<div style={{"padding": "40px", "display": "flex", "flexDirection": "column", "gap": "24px", "justifyContent": "space-between", "background": "#E9EBE7"}}>
<h2 className="display" style={{"margin": 0, "fontSize": "34px", "fontWeight": 500, "letterSpacing": "-0.035em", "lineHeight": 1.05, "textWrap": "balance"}}>Start free.<br />Pay when it pays off.</h2>
<a className="tlink" href="/pricing">Compare plans <svg className="arr" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"></path></svg></a>
</div>
<div style={{"padding": "40px", "display": "flex", "flexDirection": "column", "gap": "12px", "boxShadow": "inset 1px 0 0 #E6E8E4"}}>
<span style={{"fontWeight": 600, "fontSize": "17px"}}>Free</span>
<span className="display num" style={{"fontSize": "56px", "fontWeight": 500, "letterSpacing": "-0.04em", "lineHeight": 1}}>$0</span>
<span style={{"fontSize": "15px", "lineHeight": 1.55, "color": "#474D4A"}}>{workChecks} checks with a work email, {personalChecks} with a personal email. The full answer every time.</span>
</div>
<div style={{"padding": "40px", "display": "flex", "flexDirection": "column", "gap": "12px", "boxShadow": "inset 1px 0 0 #E6E8E4"}}>
<span style={{"display": "flex", "alignItems": "center", "gap": "10px", "fontWeight": 600, "fontSize": "17px"}}>Pro </span>
<span className="display num" style={{"fontSize": "56px", "fontWeight": 500, "letterSpacing": "-0.04em", "lineHeight": 1}}>Contact us</span>
<span style={{"fontSize": "15px", "lineHeight": 1.55, "color": "#474D4A"}}>Uses your own machines and prices.</span>
</div>
<div style={{"padding": "40px", "display": "flex", "flexDirection": "column", "gap": "12px", "boxShadow": "inset 1px 0 0 #E6E8E4"}}>
<span style={{"fontWeight": 600, "fontSize": "17px"}}>Pilot</span>
<span className="display num" style={{"fontSize": "56px", "fontWeight": 500, "letterSpacing": "-0.04em", "lineHeight": 1}}>$7,500</span>
<span style={{"fontSize": "15px", "lineHeight": 1.55, "color": "#474D4A"}}>We set it up for one factory: up to 500 parts over 4–6 weeks. The fee counts toward your first year.</span>
</div>
</div>
</div>
</section>

<section id="start" style={{"background": "#0D0F0E", "color": "#F4F5F2", "position": "relative", "overflow": "hidden", "scrollMarginTop": "72px"}}>
<svg aria-hidden="true" viewBox="0 0 1200 1000" style={{"position": "absolute", "right": "-180px", "top": "-120px", "width": "900px", "height": "750px"}}>
<path d="M602 200 L862 350 L862 650 L602 800 L342 650 L342 350 Z M342 350 L602 500 L862 350 M602 500 L602 800" fill="none" stroke="#232724" strokeWidth="2"></path>
<path d="M602 120 L942 316 L942 704 L602 900 L262 704 L262 316 Z" fill="none" stroke="#1B1E1C" strokeWidth="2"></path>
</svg>
<div className="wrap sec" style={{"position": "relative", "display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(min(480px, 100%), 1fr))", "gap": "56px 96px", "alignItems": "center"}}>
<div style={{"display": "flex", "flexDirection": "column", "gap": "32px"}}>
<h2 className="display" style={{"margin": 0, "fontWeight": 500, "fontSize": "clamp(56px, 6.6vw, 96px)", "lineHeight": 0.94, "letterSpacing": "-0.04em"}}>{startTitle}</h2>
<p style={{"margin": 0, "maxWidth": "480px", "fontSize": "20px", "lineHeight": 1.5, "color": "#B9BEBA"}}>Enter your email and we’ll send you a link to sign in. No password needed. Then upload a part and see the answer.</p>
<div style={{"display": "flex", "flexDirection": "column", "maxWidth": "520px"}}>
<div style={{"display": "grid", "gridTemplateColumns": "96px minmax(0, 1fr)", "gap": "22px", "alignItems": "center", "padding": "22px 0", "borderTop": "1px solid #2A2E2C"}}>
<span className="display num" style={{"fontSize": "60px", "fontWeight": 400, "letterSpacing": "-0.04em", "lineHeight": 1, "color": "#FF5B1F"}}>{workChecks}</span>
<span style={{"display": "flex", "flexDirection": "column", "gap": "4px"}}><span style={{"fontWeight": 600, "fontSize": "17px"}}>checks with a work email</span><span style={{"fontSize": "15px", "color": "#9BA19D"}}>Enough to try it on several real parts.</span></span>
</div>
<div style={{"display": "grid", "gridTemplateColumns": "96px minmax(0, 1fr)", "gap": "22px", "alignItems": "center", "padding": "22px 0", "borderTop": "1px solid #2A2E2C", "borderBottom": "1px solid #2A2E2C"}}>
<span className="display num" style={{"fontSize": "60px", "fontWeight": 400, "letterSpacing": "-0.04em", "lineHeight": 1, "color": "#F4F5F2"}}>{personalChecks}</span>
<span style={{"display": "flex", "flexDirection": "column", "gap": "4px"}}><span style={{"fontWeight": 600, "fontSize": "17px"}}>checks with a personal email</span><span style={{"fontSize": "15px", "color": "#9BA19D"}}>Gmail, Outlook, iCloud and similar.</span></span>
</div>
</div>
</div>

<div style={{"background": "#FFFFFF", "color": "#0D0F0E", "borderRadius": "28px", "padding": "clamp(26px, 3.4vw, 44px)", "boxShadow": "0 40px 80px -40px rgba(0,0,0,0.6)"}}>
<SignupEmailForm />
</div>
</div>
</section>

<section className="sec faq">
<div className="wrap" style={{"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(min(380px, 100%), 1fr))", "gap": "40px 96px"}}>
<h2 className="h2" style={{"fontSize": "clamp(36px, 3.8vw, 56px)"}}>Before your first part.</h2>
<div>
<details>
<summary>What counts as a check?<span className="plus"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"></path></svg></span></summary>
<p style={{"margin": "0 0 26px", "maxWidth": "620px", "fontSize": "16.5px", "lineHeight": 1.65, "color": "#474D4A"}}>Each part you upload is one check. You get the full answer every time: can it be made, what’s wrong with it, how long it takes and what it costs.</p>
</details>
<details>
<summary>What files can I upload?<span className="plus"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"></path></svg></span></summary>
<p style={{"margin": "0 0 26px", "maxWidth": "620px", "fontSize": "16.5px", "lineHeight": 1.65, "color": "#474D4A"}}>STEP, STL or IGES, the 3D formats almost every CAD program can save. Using SolidWorks, CATIA, NX or Creo? Save a copy as STEP first.</p>
</details>
<details>
<summary>Is this a quote from a supplier?<span className="plus"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"></path></svg></span></summary>
<p style={{"margin": "0 0 26px", "maxWidth": "620px", "fontSize": "16.5px", "lineHeight": 1.65, "color": "#474D4A"}}>No. It’s an estimate built from the part and your shop’s numbers. Use it to decide and to negotiate. Your team still signs off before anything gets made.</p>
</details>
<details>
<summary>What if I don’t have all the details?<span className="plus"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"></path></svg></span></summary>
<p style={{"margin": "0 0 26px", "maxWidth": "620px", "fontSize": "16.5px", "lineHeight": 1.65, "color": "#474D4A"}}>ScaleCAD fills the gaps with standard guesses and marks every one. It never treats missing information as a yes. Add your own machines or prices anytime and check again.</p>
</details>
<details style={{"borderBottom": "1px solid #DDE0DB"}}>
<summary>Can it run on our own servers?<span className="plus"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="M6 1v10M1 6h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"></path></svg></span></summary>
<p style={{"margin": "0 0 26px", "maxWidth": "620px", "fontSize": "16.5px", "lineHeight": 1.65, "color": "#474D4A"}}>Yes, as part of a pilot. We work through your security and data rules with you before you share any sensitive files.</p>
</details>
</div>
</div>
</section>
</div></SiteShell>;
}
