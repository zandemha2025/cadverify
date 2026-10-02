---
name: CadVerify public website
description: An engineering field manual for manufacturing decisions and their evidence.
colors:
  site-ink: "#183d32"
  site-lime: "#ddebaf"
  site-paper: "#fbfcfa"
  site-body: "#53635a"
  site-line: "#dbe1da"
  site-soft: "#f0f3ec"
  white: "#fff"
  action-hover: "#2f5745"
  field-stroke: "#aab8a8"
typography:
  display:
    fontFamily: "Archivo, sans-serif"
    fontSize: "clamp(44px, 4.5vw, 66px)"
    fontWeight: 500
    lineHeight: 1.08
    letterSpacing: "-.035em"
  headline:
    fontFamily: "Archivo, sans-serif"
    fontSize: "clamp(32px, 3.25vw, 46px)"
    fontWeight: 500
    lineHeight: 1.08
    letterSpacing: "-.035em"
  title:
    fontFamily: "Geist, sans-serif"
    fontSize: "20px"
    fontWeight: 500
    lineHeight: 1.35
    letterSpacing: "-.02em"
  body:
    fontFamily: "Geist, sans-serif"
    fontSize: "16px"
    lineHeight: 1.6
  body-small:
    fontFamily: "Geist, sans-serif"
    fontSize: "14px"
    lineHeight: 1.6
  label:
    fontFamily: "Geist, sans-serif"
    fontSize: "14px"
    fontWeight: 500
  button:
    fontFamily: "Geist, sans-serif"
    fontSize: "15px"
    fontWeight: 500
    lineHeight: 1.3
  evidence:
    fontFamily: "Geist Mono, monospace"
    fontSize: "12px"
    lineHeight: 1.6
rounded:
  field: "5px"
  button: "6px"
  panel: "12px"
spacing:
  control-gap: "12px"
  form-gap: "20px"
  group-gap: "24px"
  section-gap: "48px"
components:
  button-primary:
    backgroundColor: "{colors.site-ink}"
    textColor: "{colors.white}"
    typography: "{typography.button}"
    rounded: "{rounded.button}"
    padding: "14px 23px"
  button-primary-hover:
    backgroundColor: "{colors.action-hover}"
  button-compact:
    backgroundColor: "{colors.site-ink}"
    textColor: "{colors.white}"
    typography: "{typography.label}"
    rounded: "{rounded.button}"
    padding: "11px 16px"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.site-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.button}"
    padding: "14px 23px"
  button-secondary-hover:
    backgroundColor: "{colors.site-soft}"
  input:
    backgroundColor: "{colors.white}"
    textColor: "{colors.site-ink}"
    rounded: "{rounded.field}"
    padding: "12px"
    width: "100%"
  navigation:
    backgroundColor: "{colors.site-paper}"
    textColor: "{colors.site-ink}"
    typography: "{typography.label}"
    padding: "20px 56px"
  sample-record:
    backgroundColor: "{colors.white}"
    textColor: "{colors.site-ink}"
    rounded: "{rounded.panel}"
  supporting-panel:
    backgroundColor: "{colors.site-soft}"
    textColor: "{colors.site-ink}"
    rounded: "{rounded.panel}"
---

# Design System: CadVerify public website

## Overview

**Creative North Star: "The Engineering Field Manual"**

White paper, pine ink and pale lime object fields frame manufacturing decisions as work that can be inspected. Large, tightly set headings establish the question; quiet rules, explanatory text and source rows make the evidence readable. The visual character is practical, open and precise.

This document records the implemented public website under the site route group and its shared site components. Its authority is the scoped public stylesheet, not the authenticated product's global tokens. The public system stays light even when the authenticated product uses a dark theme. The separate authentication token bridge and authenticated product are outside this specification.

**Key Characteristics:**
- Paper surfaces, pine headings and restrained lime emphasis.
- Archivo headlines, Geist reading text and Geist Mono evidence values.
- Ruled information groups and softly rounded object or evidence panels.
- Visible source distinctions, limitations and semantic controls.

Source files: `frontend/src/app/(site)/site.css`, `frontend/src/app/(site)/layout.tsx`, `frontend/src/app/layout.tsx`, `frontend/src/app/(site)/page.tsx`, `frontend/src/components/site/site-shell.tsx`, `frontend/src/components/site/sample-explorer.tsx`, `frontend/src/components/site/document-page.tsx`, and `frontend/src/app/(site)/company/pilot-form.tsx`. The direction record identifies FORM as engineering field manual, candidate 7, seed `67fb2e42`; implemented code governs this document.

## Colors

Pine carries meaning and hierarchy, pale lime marks the object and invitation, and green-tinted neutrals keep the page quiet.

### Primary
- **Pine Ink** (`site-ink`): headings, primary actions, active controls and the provenance band.
- **Action Pine** (`action-hover`): the primary action's hover fill.

### Secondary
- **Pale Lime** (`site-lime`): illustrated geometry fields, closing invitations, selection and emphasis within the dark provenance band.

### Neutral
- **Paper** (`site-paper`): the public page and navigation canvas.
- **Reading Gray-Green** (`site-body`): explanatory copy and secondary labels.
- **Rule Gray-Green** (`site-line`): dividers and panel boundaries.
- **Soft Paper** (`site-soft`): supporting panels, the sample illustration field and secondary-action hover.
- **White** (`white`): fields, sample records and primary-button text.
- **Field Stroke** (`field-stroke`): visible form boundaries.

**The Evidence First Rule.** Color supports a written distinction; it never substitutes for a finding, source label or limitation. The sample pairs process and warning states with text and SVG icons.

## Typography

**Display Font:** Archivo with sans-serif fallback. **Body Font:** Geist with sans-serif fallback. **Evidence Font:** Geist Mono with monospace fallback. The root layout loads these fonts; site styles assign their roles.

Archivo supplies compact, balanced headings. Geist carries navigation, questions, controls and readable prose. Monospace is reserved for values, measurements and source/code strings rather than becoming the headline voice.

### Hierarchy
- **Display:** the default public page title from the frontmatter. The home headline is a local heavier composition, not a second global display family.
- **Headline:** section headings, with page-specific size adjustments for document and sample surfaces.
- **Title:** short subheads and step names.
- **Body:** normal public copy; long document paragraphs increase line height to (1.8).
- **Body small:** supporting descriptions, FAQ answers and footer introduction.
- **Label:** navigation and compact controls in normal sentence case.
- **Button:** primary and secondary action text.
- **Evidence:** source/code strings and cost values; preserve complete units and provenance.

**The Two Reading Voices Rule.** Use Archivo for page and section headings, Geist for interface and prose, and Geist Mono only where the content is data or source material.

## Layout

The main content container is centered with a maximum width of (1280px) and desktop side space of (56px). At widths up to (1100px), side space becomes (32px); up to (600px), it becomes (20px). Desktop navigation has its own maximum width of (1392px).

The home composition uses a question/action column beside a large geometry field, then ruled workflow links and evidence. Shared multi-column groups reflow instead of shrinking their contents indefinitely. Navigation becomes a menu at (820px); the sample's object and evidence stack at that same breakpoint. At (600px), the hero, workflow links, steps, provenance, FAQ and pilot fields become single-column arrangements.

Read surfaces pair a (235px) contents rail with article sections and a (74px) gap. The rail narrows at (1100px); at (600px), it becomes a normal-flow list above the article. Document text sections are at most (800px) wide, with a (740px) introductory measure. Use the established recurring gaps in frontmatter as reference values; the implementation has context-specific spacing, not a rigid universal scale.

**The Reading Order Rule.** Responsive reflow preserves the order of the question, explanation, action and evidence; narrow screens retain the controls and disclosures.

## Elevation & Depth

The public page is flat at rest. Paper, soft paper, lime and pine bands establish depth through tone; thin rules define groups. Ordinary panels have no box shadow. The mobile navigation alone uses a diffuse separation shadow (`0 16px 24px -22px #183d3255`) when it overlays page content.

**The Paper Surface Rule.** Use tone and rules for normal grouping. Reserve the existing separation shadow for the navigation overlay; do not turn each information group into a floating card.

## Shapes

Buttons have modest round corners, fields use a slightly tighter corner, and large evidence or object panels share the panel radius. These three repeated roles are recorded in frontmatter. Workflows, evidence rows and FAQ entries remain open, ruled groups instead of individual rounded tiles.

Circular source markers distinguish measured, declared and assumed inputs in the provenance band. The assumed marker is hollow with a dashed stroke. These shapes support adjacent source labels; they are not badges of certification. Icons are inline Lucide SVGs, while the FAQ chevron is a small CSS-drawn stroke.

## Components

### Buttons

Solid pine actions are compact and direct. The primary and secondary variants share the button geometry and type; the secondary has a transparent fill and a rule-colored border. Desktop actions have a minimum height of (52px); the compact navigation variant uses (44px). At (600px) and below, the shared button minimum becomes (49px), with (13px 18px) padding and (14px) text.

Hover changes fill and moves the control upward (1px) over (160ms ease). Secondary hover uses soft paper. Every keyboard-focusable public control uses a (2px) green outline (`#276742`) offset by (5px). Reduced-motion preferences remove transitions. Text actions use a small inline SVG arrow and underline on hover.

### Cards / Containers

The sample record is white with a thin rule-colored outline and the shared panel corner. Its header separates the file identity and recorded status from the evidence. The illustration has a soft-paper background; the neighboring evidence retains white. Supporting form and document-close panels use soft paper and the same panel corner without shadow.

### Inputs / Fields

Native input, select and textarea controls use white, the field stroke and the field corner with frontmatter padding. Labels stay visibly above the fields. Fields use (15px) text and the shared visible-focus outline. The textarea has a minimum height of (120px) and can resize vertically. Required/email validation is native; no custom public error or disabled style is established.

### Navigation

The brand sits opposite horizontal sentence-case links and a compact sample action. Current-page and hover states underline links. The mobile menu button is (44px) square and exposes its expanded state. Its navigation closes after selection; Escape closes it and returns focus to the toggle. Keep the skip link and landmark labels.

### Sample view controls and evidence

Process fit, design review and resource estimate are real buttons grouped under a visible sample-view context. The selected view has a pine bottom rule and heavier text; `aria-pressed` carries selection and the evidence area announces updates politely. Treat these as view selectors, not decorative chips. Preserve the record header, figure description, definition-list rows, qualifier text and source disclosures together.

### Disclosures

FAQ and detailed source content use native `details` and `summary`. Thin rules separate entries; the FAQ chevron rotates with open state. Content remains regular reading text, while source strings use the evidence face and wrap. Disclosure controls inherit the shared visible-focus treatment.

## Do's and Don'ts

### Do:
- **Do** keep this system scoped to the public website and reuse its existing components.
- **Do** use the three established font roles and preserve readable prose measures.
- **Do** keep source labels, units and limitations next to the evidence they qualify.
- **Do** preserve visible keyboard focus, semantic labels, native disclosure behavior and reduced motion.
- **Do** reflow groups into the established mobile reading order.

### Don't:
- **Don't** apply these public tokens to authenticated product screens by default.
- **Don't** replace ruled information groups with repeated floating cards.
- **Don't** make color, a source marker or an icon the sole carrier of meaning.
- **Don't** turn small illustration annotations, one-off size overrides or heading eyebrows into reusable type roles.
- **Don't** present the schematic part render or recorded sample as a newly executed analysis.

Not canonized: the build's tiny illustration captions and annotation sizes remain local legibility debt, not a reusable caption scale. No eyebrow/kicker style is established. The home headline's local weight and layout-specific size overrides are composition details, not new global tokens.
