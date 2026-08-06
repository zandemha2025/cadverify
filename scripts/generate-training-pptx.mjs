import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const frontendRequire = createRequire(path.join(repoRoot, "frontend", "package.json"));
const runtimeRequire = createRequire(import.meta.url);

let PptxGenJS;
let sharp;
try {
  PptxGenJS = runtimeRequire("pptxgenjs");
  sharp = runtimeRequire("sharp");
} catch (error) {
  throw new Error(
    "pptxgenjs and sharp are required. Set NODE_PATH to the bundled workspace node_modules or install them locally.",
    { cause: error },
  );
}
const { chromium } = frontendRequire("playwright-core");

const guidePath = path.join(repoRoot, "docs", "training", "proofshape-platform-guide.html");
const assetRoot = path.join(repoRoot, "docs", "training", "assets");
const outputPath = process.env.PPTX_OUTPUT
  ? path.resolve(process.env.PPTX_OUTPUT)
  : path.join(repoRoot, "outputs", "proofshape-platform-zero-to-production.pptx");

const W = 13.333;
const H = 7.5;
const C = {
  ink: "15171A",
  muted: "666B73",
  faint: "E9E9EC",
  paper: "F8F8F6",
  white: "FFFFFF",
  red: "C93C3C",
  amber: "AA721C",
  blue: "2859A8",
  green: "297A56",
};
const F = { display: "Aptos Display", body: "Aptos", mono: "Aptos Mono" };

function safeText(value) {
  return String(value ?? "").replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");
}

function fontForLength(text, preferred, minimum, thresholds) {
  const length = safeText(text).length;
  let size = preferred;
  for (const [limit, candidate] of thresholds) {
    if (length > limit) size = Math.min(size, candidate);
  }
  return Math.max(minimum, size);
}

function badge(slide) {
  if (slide.validation === "partial") return { text: "PARTIAL · EXTERNAL GATE", color: C.amber };
  if (slide.validation === "validated") return { text: "TEST CONTRACT · BUILD EVIDENCE REQUIRED", color: C.blue };
  return { text: "EVIDENCE SCREEN", color: C.muted };
}

function actionLabel(action) {
  const [label, _target, kind] = action;
  if (kind === "app") return `${label}  ↗`;
  return `${label}  ↓`;
}

async function guideData() {
  const browser = await chromium.launch({ channel: "chrome", headless: true }).catch(() => chromium.launch({ headless: true }));
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    await page.goto(pathToFileURL(guidePath).href, { waitUntil: "load" });
    await page.waitForFunction(() => Boolean(window.__proofshapeGuide?.slides?.length));
    return await page.evaluate(() => ({
      slides: JSON.parse(JSON.stringify(window.__proofshapeGuide.slides)),
      rolePaths: JSON.parse(JSON.stringify(window.__proofshapeGuide.rolePaths)),
    }));
  } finally {
    await browser.close();
  }
}

async function containImage(imagePath, x, y, w, h) {
  const meta = await sharp(imagePath).metadata();
  const iw = meta.width || 1;
  const ih = meta.height || 1;
  const scale = Math.min(w / iw, h / ih);
  const rw = iw * scale;
  const rh = ih * scale;
  return { path: imagePath, x: x + (w - rw) / 2, y: y + (h - rh) / 2, w: rw, h: rh };
}

function addChrome(pptx, slide, source, index, total, sections, sectionFirst, isDark) {
  const fg = isDark ? C.white : C.ink;
  const muted = isDark ? "B9BDC5" : C.muted;
  slide.addText("P", {
    x: 0.42, y: 0.23, w: 0.28, h: 0.28,
    fontFace: F.display, fontSize: 13, bold: true, color: isDark ? C.ink : C.white,
    fill: { color: isDark ? C.white : C.ink }, margin: 0, align: "center", valign: "mid",
    hyperlink: { slide: 1 },
  });
  slide.addText("PROOFSHAPE · PLATFORM WALKTHROUGH", {
    x: 0.82, y: 0.22, w: 3.4, h: 0.25, fontFace: F.mono, fontSize: 7.5,
    bold: true, charSpacing: 1.35, color: muted, margin: 0,
  });
  let tabX = 4.45;
  const shortSection = {
    Start: "START", Access: "ACCESS", "Verify CAD": "VERIFY", "Design CAD": "DESIGN",
    "Cost & Governance": "COST", Manufacturing: "MFG", "Batch & Sourcing": "BATCH",
    Administration: "ADMIN", Recovery: "RECOVERY", "Whole journey": "JOURNEY", Finish: "FINISH",
  };
  for (const section of sections) {
    const selected = section === source.section;
    const label = shortSection[section] || section.toUpperCase();
    const tabW = Math.max(0.5, 0.31 + label.length * 0.047);
    slide.addText(label, {
      x: tabX, y: 0.22, w: tabW, h: 0.24,
      fontFace: F.mono, fontSize: 5.3, bold: selected, align: "center", margin: 0,
      color: selected ? (isDark ? C.white : C.ink) : muted,
      hyperlink: { slide: sectionFirst[section] + 1 },
    });
    if (selected) slide.addShape(pptx.ShapeType.line, { x: tabX + 0.06, y: 0.48, w: tabW - 0.12, h: 0, line: { color: isDark ? C.white : C.ink, width: 1.4 } });
    tabX += tabW + 0.03;
  }
  slide.addShape(pptx.ShapeType.line, { x: 0.42, y: 0.59, w: 12.49, h: 0, line: { color: isDark ? "3A3D42" : "D9DADD", width: 0.8 } });

  slide.addText(index > 0 ? "← PREVIOUS" : "", {
    x: 0.45, y: 7.17, w: 1.15, h: 0.18, fontFace: F.mono, fontSize: 6.5, color: muted, margin: 0,
    hyperlink: index > 0 ? { slide: index } : undefined,
  });
  slide.addText(`${String(index + 1).padStart(2, "0")} / ${String(total).padStart(2, "0")}`, {
    x: 6.08, y: 7.17, w: 1.15, h: 0.18, fontFace: F.mono, fontSize: 6.5, color: muted, margin: 0, align: "center",
  });
  slide.addText(index < total - 1 ? "NEXT →" : "", {
    x: 11.75, y: 7.17, w: 1.1, h: 0.18, fontFace: F.mono, fontSize: 6.5, color: muted, margin: 0, align: "right",
    hyperlink: index < total - 1 ? { slide: index + 2 } : undefined,
  });
}

function addExpected(pptx, slide, source, x, y, w, h, isDark) {
  if (!source.expected) return;
  const text = safeText(source.expected);
  slide.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.05,
    fill: { color: isDark ? "202329" : "F1F1EF" },
    line: { color: isDark ? "42464D" : "D8D8D4", width: 0.8 },
  });
  slide.addText(source.validation === "partial" ? "VALIDATED SCOPE / REMAINING GATE" : "EXPECTED OUTCOME", {
    x: x + 0.16, y: y + 0.12, w: w - 0.32, h: 0.19,
    fontFace: F.mono, fontSize: 6.8, bold: true, charSpacing: 1.05,
    color: source.validation === "partial" ? C.amber : (isDark ? "C9CDD4" : C.muted), margin: 0,
  });
  slide.addText(text, {
    x: x + 0.16, y: y + 0.37, w: w - 0.32, h: h - 0.49,
    fontFace: F.body,
    fontSize: fontForLength(text, 10.2, 7.3, [[250, 9.2], [420, 8.3], [610, 7.3]]),
    color: isDark ? C.white : C.ink, margin: 0, breakLine: false, valign: "top", fit: "shrink",
  });
}

async function addSlide(pptx, source, index, allSlides, sections, sectionFirst, rolePaths) {
  const slide = pptx.addSlide();
  const isDark = Boolean(source.dark);
  const bg = isDark ? C.ink : C.paper;
  const fg = isDark ? C.white : C.ink;
  const muted = isDark ? "B8BDC6" : C.muted;
  slide.background = { color: bg };
  slide.addNotes([
    `Source route: ${source.id}`,
    `Evidence: ${safeText(source.evidence)}`,
    `Expected: ${safeText(source.expected)}`,
  ]);
  addChrome(pptx, slide, source, index, allSlides.length, sections, sectionFirst, isDark);

  const b = badge(source);
  slide.addText(b.text, {
    x: 0.52, y: 0.83, w: 3.5, h: 0.22, fontFace: F.mono, fontSize: 6.6,
    bold: true, charSpacing: 0.8, color: b.color, margin: 0,
  });
  slide.addText(safeText(source.kicker || source.section).toUpperCase(), {
    x: 0.52, y: 1.13, w: 5.9, h: 0.22, fontFace: F.mono, fontSize: 7.2,
    bold: true, charSpacing: 1.25, color: muted, margin: 0,
  });
  const title = safeText(source.title);
  slide.addText(title, {
    x: 0.5, y: 1.42, w: 7.38, h: 0.9,
    fontFace: F.display, fontSize: fontForLength(title, 25, 18, [[50, 22], [76, 19.5], [100, 18]]),
    bold: true, color: fg, margin: 0, breakLine: false, valign: "top", fit: "shrink",
  });
  const summary = safeText(source.summary);
  slide.addText(summary, {
    x: 0.52, y: 2.32, w: 7.25, h: 0.72,
    fontFace: F.body, fontSize: fontForLength(summary, 12, 9.2, [[170, 10.8], [260, 9.6]]),
    color: muted, margin: 0, valign: "top", fit: "shrink",
  });

  const steps = Array.isArray(source.steps) ? source.steps : [];
  const actions = Array.isArray(source.actions) ? source.actions : [];
  let stepTop = 3.18;
  if (actions.length) {
    const shown = actions.slice(0, 4);
    let x = 0.52;
    for (const action of shown) {
      const label = actionLabel(action);
      const w = Math.min(2.25, Math.max(1.28, 0.56 + label.length * 0.037));
      const options = {
        x, y: 3.1, w, h: 0.39, fontFace: F.mono, fontSize: 6.3, bold: true,
        color: isDark ? C.white : C.ink, fill: { color: isDark ? "272B31" : C.white },
        line: { color: isDark ? "4A4E56" : "C9CACD", width: 0.8 }, margin: 0.08,
        valign: "mid", fit: "shrink",
      };
      if (action[2] === "app") options.hyperlink = { url: `http://localhost:3000${action[1]}` };
      slide.addText(label, options);
      x += w + 0.1;
      if (x > 6.95) break;
    }
    stepTop = 3.63;
  }

  const availableStepH = 6.68 - stepTop;
  if (steps.length) {
    const each = Math.min(0.76, Math.max(0.49, availableStepH / steps.length));
    const totalChars = steps.reduce((sum, item) => sum + safeText(item).length, 0);
    const stepFont = fontForLength("x".repeat(totalChars), 10.2, 7.8, [[310, 9.3], [500, 8.5], [700, 7.8]]);
    steps.forEach((item, stepIndex) => {
      const y = stepTop + stepIndex * each;
      slide.addShape(pptx.ShapeType.ellipse, {
        x: 0.53, y: y + 0.04, w: 0.28, h: 0.28,
        fill: { color: stepIndex === 0 ? C.red : (isDark ? "2D3138" : C.white) },
        line: { color: stepIndex === 0 ? C.red : (isDark ? "5A5F68" : "BFC1C5"), width: 0.8 },
      });
      slide.addText(String(stepIndex + 1), {
        x: 0.53, y: y + 0.045, w: 0.28, h: 0.27, fontFace: F.mono, fontSize: 7,
        bold: true, color: stepIndex === 0 ? C.white : fg, margin: 0, align: "center", valign: "mid",
      });
      slide.addText(safeText(item), {
        x: 0.93, y, w: 6.83, h: each - 0.02, fontFace: F.body, fontSize: stepFont,
        color: fg, margin: 0, valign: "top", fit: "shrink",
      });
    });
  } else if (source.metrics) {
    source.metrics.slice(0, 4).forEach((metric, metricIndex) => {
      const x = 0.52 + (metricIndex % 2) * 3.6;
      const y = 3.28 + Math.floor(metricIndex / 2) * 1.22;
      slide.addText(safeText(metric[0]), { x, y, w: 3.35, h: 0.48, fontFace: F.display, fontSize: 22, bold: true, color: fg, margin: 0 });
      slide.addText(safeText(metric[1]).toUpperCase(), { x, y: y + 0.53, w: 3.35, h: 0.23, fontFace: F.mono, fontSize: 7, color: muted, margin: 0, charSpacing: 0.9 });
    });
  } else if (source.flow) {
    source.flow.slice(0, 5).forEach((item, itemIndex) => {
      const y = 3.22 + itemIndex * 0.63;
      slide.addText(safeText(item[0]), { x: 0.54, y, w: 1.75, h: 0.24, fontFace: F.mono, fontSize: 8, bold: true, color: fg, margin: 0 });
      slide.addText(safeText(item[1]), { x: 2.18, y, w: 5.45, h: 0.42, fontFace: F.body, fontSize: 9.2, color: muted, margin: 0, fit: "shrink" });
    });
  } else if (source.roles) {
    source.roles.slice(0, 8).forEach((role, roleIndex) => {
      const col = roleIndex % 2;
      const row = Math.floor(roleIndex / 2);
      const x = 0.52 + col * 3.62;
      const y = 3.13 + row * 0.72;
      const firstRoleSlide = rolePaths?.[role[2]]?.slides?.[0];
      const firstRoleIndex = allSlides.findIndex((item) => item.id === firstRoleSlide);
      slide.addText(`${safeText(role[0])}\n${safeText(role[1])}`, {
        x, y, w: 3.4, h: 0.6, fontFace: F.body, fontSize: 8.2, bold: true,
        color: fg, fill: { color: isDark ? "22262C" : C.white }, line: { color: isDark ? "3D424A" : "D5D6D8" }, margin: 0.12,
        hyperlink: firstRoleIndex >= 0 ? { slide: firstRoleIndex + 1 } : undefined,
      });
    });
  }

  const imageNames = source.images || (source.image ? [source.image] : []);
  if (imageNames.length) {
    const frameY = 1.13;
    const frameH = 3.55;
    slide.addShape(pptx.ShapeType.roundRect, {
      x: 8.15, y: frameY, w: 4.66, h: frameH,
      fill: { color: isDark ? "0E0F11" : C.white },
      line: { color: isDark ? "34373D" : "D5D6D8", width: 0.8 },
    });
    if (imageNames.length === 1) {
      const imagePath = path.join(assetRoot, imageNames[0]);
      slide.addImage({ ...(await containImage(imagePath, 8.28, frameY + 0.13, 4.4, frameH - 0.26)), altText: `${title} platform evidence` });
    } else {
      for (let i = 0; i < Math.min(2, imageNames.length); i += 1) {
        const imagePath = path.join(assetRoot, imageNames[i]);
        slide.addImage({ ...(await containImage(imagePath, 8.28, frameY + 0.12 + i * 1.69, 4.4, 1.54)), altText: `${title} platform evidence ${i + 1}` });
      }
    }
    addExpected(pptx, slide, source, 8.15, 4.88, 4.66, 1.73, isDark);
  } else {
    addExpected(pptx, slide, source, 8.15, 1.4, 4.66, 3.0, isDark);
    slide.addShape(pptx.ShapeType.roundRect, {
      x: 8.15, y: 4.62, w: 4.66, h: 1.42,
      fill: { color: isDark ? "202329" : C.white },
      line: { color: isDark ? "42464D" : "D8D8D4", width: 0.8 },
    });
    slide.addText("EVIDENCE", { x: 8.31, y: 4.78, w: 1.1, h: 0.18, fontFace: F.mono, fontSize: 6.8, bold: true, charSpacing: 1.1, color: muted, margin: 0 });
    slide.addText(safeText(source.evidence), { x: 8.31, y: 5.08, w: 4.32, h: 0.72, fontFace: F.body, fontSize: 9.1, color: fg, margin: 0, fit: "shrink" });
  }
  slide.addText(`EVIDENCE · ${safeText(source.evidence)}`, {
    x: 0.52, y: 6.83, w: 11.9, h: 0.18, fontFace: F.mono, fontSize: 5.9,
    color: muted, margin: 0, fit: "shrink",
  });
}

async function main() {
  const { slides, rolePaths } = await guideData();
  if (slides.length !== 53) throw new Error(`Expected 53 source slides, got ${slides.length}`);
  const sections = [...new Set(slides.map((slide) => slide.section))];
  const sectionFirst = Object.fromEntries(sections.map((section) => [section, slides.findIndex((slide) => slide.section === section)]));
  const guideHash = createHash("sha256").update(await readFile(guidePath)).digest("hex");

  const pptx = new PptxGenJS();
  pptx.defineLayout({ name: "PROOFSHAPE_WIDE", width: W, height: H });
  pptx.layout = "PROOFSHAPE_WIDE";
  pptx.author = "ProofShape";
  pptx.company = "ProofShape";
  pptx.subject = `Zero-to-production platform guide · source ${guideHash}`;
  pptx.title = "ProofShape Platform — Zero to a Defensible Result";
  pptx.lang = "en-US";
  pptx.theme = {
    headFontFace: F.display,
    bodyFontFace: F.body,
    lang: "en-US",
  };
  pptx.defineSlideMaster({
    title: "PROOFSHAPE",
    background: { color: C.paper },
    objects: [],
    slideNumber: { x: 12.7, y: 7.16, w: 0.2, h: 0.16, color: C.muted, fontFace: F.mono, fontSize: 5.5 },
  });

  for (let index = 0; index < slides.length; index += 1) {
    await addSlide(pptx, slides[index], index, slides, sections, sectionFirst, rolePaths);
  }
  await mkdir(path.dirname(outputPath), { recursive: true });
  await pptx.writeFile({ fileName: outputPath, compression: true });
  process.stdout.write(`${JSON.stringify({ outputPath, slides: slides.length, roles: Object.keys(rolePaths).length, guideHash }, null, 2)}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
