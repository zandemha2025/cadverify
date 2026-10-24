"use client";

/**
 * Your files and data: where uploaded CAD files are kept, who can see them,
 * what share links show, how files are used, connections, keeping and
 * deleting, and every outside service that receives data. Read-only facts from
 * ./facts (what the code does today); the Hosting section is filled from this
 * deployment's configuration (GET /api/v1/deployment), never guessed. The
 * public Security, Privacy and Data processing pages render the same facts.
 */
import * as React from "react";
import { Content, Panel, Sheet } from "../ui";
import { AccountFrame, AccountHead } from "../account/frame";
import { DATA_PAGE, SECTIONS, SERVICES, hostingSection, type DeploymentFacts, type FactSection } from "./facts";
import "./trust.css";

function Section({ s }: { s: FactSection }) {
  return (
    <Panel title={s.title} id={s.id} note={s.note} actions={s.link ? <a href={s.link.href}>{s.link.label}</a> : undefined}>
      <dl className="t-rows">
        {s.rows.map((r) => (
          <div key={r.k} style={{ display: "contents" }}>
            <dt>{r.k}</dt>
            <dd>{r.v}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

export function DataScreen() {
  const [deployment, setDeployment] = React.useState<DeploymentFacts | null>(null);
  React.useEffect(() => {
    let live = true;
    fetch("/api/proxy/deployment", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: DeploymentFacts | null) => live && d && d.file_storage && setDeployment(d))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  const hosting = hostingSection(deployment);
  return (
    <AccountFrame label={DATA_PAGE.title}>
      <AccountHead title={DATA_PAGE.title} meta={DATA_PAGE.meta.map((m) => <span key={m}>{m}</span>)} />
      <Content>
        <div className="t-page">
          {SECTIONS.map((s) => (
            <React.Fragment key={s.id}>
              <Section s={s} />
              {s.id === "transit" ? <Section s={hosting} /> : null}
            </React.Fragment>
          ))}
          <Panel title="Services that receive data" id="services">
            <table className="t-svc">
              <thead>
                <tr>
                  <th scope="col">Service</th>
                  <th scope="col">What it gets</th>
                  <th scope="col">When</th>
                </tr>
              </thead>
              <tbody>
                {SERVICES.map((x) => (
                  <tr key={x.name}>
                    <td>{x.name}</td>
                    <td>{x.gets}</td>
                    <td>{x.when}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="t-foot">
              This is what ScaleCAD’s software does today. A pilot or enterprise agreement can add terms. <a href="/privacy">Privacy</a> · <a href="/security">Security</a> · <a href="/dpa">Data processing</a>
            </p>
          </Panel>
        </div>
      </Content>
      <Sheet label="In short" style={{ bottom: "auto" }}>
        <div className="top">
          <h2 className="stitle">In short</h2>
          <p className="smeta">A CAD file you check</p>
        </div>
        <ul className="t-short">
          {SECTIONS.filter((s) => s.short).map((s) => (
            <li key={s.id}>
              <a href={`#${s.id}`}>{s.title}</a>
              <span>{s.short}</span>
            </li>
          ))}
        </ul>
      </Sheet>
    </AccountFrame>
  );
}
