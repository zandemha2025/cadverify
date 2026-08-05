---
title: "MBD, PMI and drawings — where the product definition actually lives"
domain: cad
audience: "Engineers moving to model-based definition, and anyone auditing one"
sources: [asme_y14_41, asme_y14_5, as9102, iso_gps_1101]
provenance: DEFAULT
---

# MBD, PMI and drawings

## The three states of product definition

**Drawing-authoritative.** The 2D drawing is the legal definition; the model is a
convenience for CAM. Still the majority of the installed base. Slow, but
unambiguous about where authority sits.

**Model-authoritative with a drawing (hybrid).** The model carries the geometry,
a reduced drawing carries the tolerances and notes. The most common transitional
state, and **the most dangerous one**, because when the two disagree it is often
unclear which wins — and they do disagree.

**Full MBD.** The 3D model, annotated with PMI, is the single authoritative
definition. No drawing. Governed by ASME Y14.41 (or the ISO equivalent).

The dangerous state is the middle one. If you are in it, the definition must
state explicitly which artifact is authoritative for which content, and that
statement must be somewhere a manufacturing engineer will actually read.

---

## Graphic PMI vs semantic PMI

The distinction that decides whether MBD works at all.

**Graphic PMI** is annotation stored as lines and text positioned in 3D space. A
human reads it. Software sees decoration. It cannot be extracted, queried,
ballooned, or used to drive inspection.

**Semantic PMI** is annotation stored as structured objects: tolerance type,
value, modifiers, datum references, **and links to the specific faces they apply
to**. Software can extract every characteristic, generate the balloon map, and
drive a CMM programme.

Only semantic PMI delivers MBD's actual benefit. Graphic PMI is a drawing drawn
on a model — with the added disadvantage that it is harder to read than a
drawing.

**Format consequence:** STEP AP203 and AP214 carry PMI as polylines only. STEP
AP242 carries semantic PMI. Choosing AP203 for an MBD workflow silently converts
your semantic definition into pictures.

---

## The expensive failure mode

Worth stating on its own, because it recurs everywhere:

> Characteristics that exist on the authoring model, do not survive the exchange,
> and therefore never appear on the AS9102 balloon map — so they are never
> inspected.

The part ships having never been checked against requirements that were genuinely
specified by a competent engineer. Nobody was careless. The tolerance simply
stopped existing somewhere between two systems, and nothing in the process was
designed to notice.

**The only reliable defence is counting.** Count semantic characteristics in the
source, count them in the received file, and compare. Every other check —
"it looked right", "the viewer showed the annotations" — fails on graphic PMI,
because graphic PMI looks exactly right.

---

## What good MBD looks like

- **Semantic PMI throughout**, with every annotation linked to the faces it
  applies to. No orphan annotations floating in space.
- **Saved views** that organise annotation by purpose — a datum view, a
  machining view, an inspection view — so a user is never looking at every
  annotation at once.
- **A complete definition**: material, finish, general tolerance class, governing
  standard *and edition*, notes. Everything a title block carried, still present
  and still findable.
- **The datum scheme visible and legible** as its own view.
- **A stated authority**: this model is the definition; no drawing exists.
- **Query-only derivative** for suppliers who cannot consume the native model —
  clearly marked as derived, with its source revision recorded.
- **Characteristic count published with the release**, so any downstream
  recipient can verify the exchange.

## What bad MBD looks like

- **Graphic PMI presented as MBD.** Looks identical in a viewer. Delivers none of
  the benefit and removes the drawing that used to work.
- **Annotations not linked to faces**, so extraction produces a list with no idea
  what each tolerance applies to.
- **Every annotation in one view**, unreadable, so people export a drawing anyway
  and the drawing quietly becomes authoritative.
- **A hybrid with no stated authority.** The model says one thing, the drawing
  another, and the shop picks.
- **No governing standard or edition declared.** ASME Rule #1 and ISO independency
  give different acceptance outcomes on the same annotation.
- **Incomplete definition** — geometry annotated, material and finish left in an
  email.
- **Supplier sent AP203** for a definition whose whole value was semantic.

---

## The tolerancing-standard trap in MBD

Under **ASME Y14.5**, Rule #1 means the size tolerance of a feature of size also
controls its form. Under **ISO GPS**, the default is independency — form is not
controlled by size unless (E) is invoked.

On a drawing, the title block declares which applies. On a model, that
declaration has to be somewhere deliberate, and it frequently is not. The result
is a definition that accepts different parts depending on who reads it, with
both readers being correct.

State the standard and its edition. Every time.

---

## Migrating to MBD without breaking things

1. **Semantic PMI from the start.** Graphic PMI is not a stepping stone; it is a
   dead end that costs the same effort.
2. **AP242 as the exchange format**, verified with the receiver on a real part
   before the programme depends on it.
3. **Characteristic counting in the release process**, not as an aspiration.
4. **Saved views designed for readers** — machinists, inspectors, suppliers — not
   for the author.
5. **Explicit authority statements** on every artifact, including derivatives.
6. **Train the receivers.** MBD fails most often on the supplier side, where the
   viewer, the training, or the extraction tooling is not there. A supplier who
   cannot consume the definition will make their own drawing, and it will be
   wrong.
7. **Verify with a first article early**, on a representative part, and treat the
   FAI as a test of the *definition process* rather than of the part.

---

## The auditor's angle

An auditor in an MBD workflow will ask:

- Which artifact is authoritative, and where does it say so?
- Is every characteristic ballooned and reported — and can you demonstrate the
  balloon map is **complete** against the model?
- What is the configuration control on the model, and on every derivative sent to
  a supplier?
- If a supplier received a STEP file, how do you know it matched the released
  revision at the time, and how would you know today?
- Which tolerancing standard and edition governs?

The second question is the one that finds real problems, and the answer is
almost always a count.
