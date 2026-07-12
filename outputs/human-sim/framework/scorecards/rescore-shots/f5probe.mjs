import { createRequire } from "node:module";
import path from "node:path";
import fs from "node:fs";
const require = createRequire("/home/user/cadverify/.claude/worktrees/hsim-rescore/frontend/package.json");
const pw = require("playwright-core");
const SHOTS = "/home/user/cadverify/outputs/human-sim/framework/scorecards/rescore-shots";
const STATE = path.join(SHOTS, "storage-state.json");
const EXEC = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const BASE = "http://localhost:3042";
const CUBE = "/home/user/cadverify/.claude/worktrees/hsim-rescore/backend/tests/assets/cube.step";
const browser = await pw.chromium.launch({ headless: true, executablePath: EXEC, args: ["--no-sandbox","--disable-dev-shm-usage"] });
const ctx = await browser.newContext({ viewport:{width:1440,height:960}, baseURL:BASE, reducedMotion:"reduce", storageState: STATE });
const page = await ctx.newPage();
await page.goto("/verify",{waitUntil:"domcontentloaded"});
await page.waitForTimeout(1000);
await page.locator('button[title="Verify"]').click({timeout:8000});
await page.waitForTimeout(600);
await page.locator('input[type="file"]').first().setInputFiles(CUBE);
await page.waitForFunction(()=>/should-cost|unit cost/i.test(document.body.innerText)&&!/measuring geometry/i.test(document.body.innerText),null,{timeout:120000}).catch(()=>{});
await page.waitForTimeout(2500);
// scroll right panel to SETUP driver
await page.evaluate(()=>{
  const el=[...document.querySelectorAll("*")].find(n=>/^SETUP$/.test((n.textContent||"").trim()));
  el?.scrollIntoView({block:"center"});
});
await page.waitForTimeout(1000);
await page.screenshot({path:path.join(SHOTS,"f5-drivers-panel.png"),fullPage:false});
console.log("shot f5-drivers-panel");
// also capture headline together: scroll to should-cost verdict
await page.evaluate(()=>{
  const el=[...document.querySelectorAll("*")].find(n=>/Should-cost/.test((n.textContent||""))&&n.children.length<6);
  el?.scrollIntoView({block:"start"});
});
await page.waitForTimeout(800);
await page.screenshot({path:path.join(SHOTS,"f5-headline.png"),fullPage:false});
console.log("shot f5-headline");
// dump exact driver panel text
const driverText = await page.evaluate(()=>{
  const setup=[...document.querySelectorAll("*")].find(n=>/^SETUP$/.test((n.textContent||"").trim()));
  let node=setup; for(let i=0;i<6&&node;i++) node=node.parentElement;
  return node?.innerText||"NOTFOUND";
});
fs.writeFileSync(path.join(SHOTS,"f5-driver-panel-text.txt"),driverText);
await browser.close();
