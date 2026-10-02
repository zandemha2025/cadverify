"use client";

import { useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { PILOT_WORKFLOWS } from "@/lib/site/navigation";

export function PilotForm({ initialWorkflow }: { initialWorkflow?: string }) {
  const [prepared, setPrepared] = useState(false);
  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const subject = `CadVerify pilot — ${data.get("company")}`;
    const body = `Work email: ${data.get("email")}\nCompany: ${data.get("company")}\nWorkflow: ${data.get("workflow")}\n\n${data.get("question")}`;
    window.location.href = `mailto:nazeemahmed2023@gmail.com?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    setPrepared(true);
  }
  return <form className="cv-pilot-form" onSubmit={onSubmit} aria-label="Plan a pilot"><h3>Tell us what you need to decide.</h3><p>We’ll prepare an email for your team’s workflow. You can review it in your email app before sending.</p><div className="cv-form-fields">
    <label>Work email<input name="email" type="email" autoComplete="email" required maxLength={254} placeholder="you@company.com" /></label>
    <label>Company<input name="company" autoComplete="organization" required maxLength={120} placeholder="Your company" /></label>
    <label>What are you working on?<select name="workflow" defaultValue={PILOT_WORKFLOWS.includes(initialWorkflow ?? "") ? initialWorkflow : PILOT_WORKFLOWS[0]}>{PILOT_WORKFLOWS.map(workflow => <option key={workflow}>{workflow}</option>)}</select></label>
    <label>Your question<textarea name="question" required maxLength={2000} placeholder="Tell us about the parts, the decision, and any requirements we should understand." /></label>
  </div><button className="cv-button" type="submit">Prepare pilot email <ArrowUpRight size={17} aria-hidden="true" /></button><p className="cv-form-note" role="status">{prepared ? "Your email draft is ready to open. It has not been sent. If your email app didn’t open, write to nazeemahmed2023@gmail.com." : "Prefer to write directly? Email nazeemahmed2023@gmail.com. Please don’t attach sensitive CAD before agreeing on data handling."}</p><a className="cv-text-link" href="mailto:nazeemahmed2023@gmail.com">Email nazeemahmed2023@gmail.com</a></form>;
}
