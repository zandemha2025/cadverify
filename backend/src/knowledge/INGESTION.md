# Ingestion — how outside knowledge enters this corpus

**Not legal advice.** This is an engineering policy that encodes a
conservative reading of copyright. Before building any pipeline that processes
licensed material, get an actual lawyer. What follows is how the corpus is
built, and why the loader enforces what it enforces.

---

## The distinction everything rests on

> **Facts are not copyrightable. Expression is. And the act of copying is
> reproduction regardless of what you do with the copy afterwards.**

The first half is why this corpus can exist: "22 HRC for sour service" is a
fact, and stating it with attribution is legitimate no matter which book you
learned it from. Reading, understanding, and writing your own explanation is
how knowledge has always moved.

The second half is the part that catches people. "We'll interpret it, not copy
it verbatim" describes the *output*. The legal exposure is in the *input* —
machine-ingesting a licensed work makes an unlicensed copy at the moment of
ingestion, and paraphrasing downstream does not cure it.

Three things compound it:

1. **Compilations carry their own protection.** A handbook's selection and
   arrangement of data tables is protectable even where the individual numbers
   are not. Wholesale table extraction is the classic risky case, and in the EU
   the *sui generis* database right protects substantial extraction of even pure
   facts.
2. **Contract, not just copyright.** Most digital editions carry terms banning
   scraping, text and data mining, and commercial reuse. That binds
   independently of copyright, and it is how publishers actually enforce.
3. **Diligence.** "Where did the knowledge come from?" is asked during
   fundraising and acquisition. A pipeline that ingested licensed handbooks is a
   material disclosure, not a technicality.

---

## The three policies

Every source in `packs/sources.yaml` declares an `ingestion` policy. The
default is the restrictive one; loosening it requires a decision and a written
basis.

| Policy | Means | Applies to |
|---|---|---|
| `full` | The text may be downloaded, parsed, stored and quoted | Public-domain and openly-licensed works only |
| `facts_only` | **Default.** State facts with attribution; never copy or machine-ingest the text | Everything we have legitimate access to — standards we own, handbooks we've read, vendor guides |
| `reference_only` | Cite that it exists and what it requires; no content | Works we have not obtained |

And a `licence` field, deliberately separate from `access`:

| Licence | Means |
|---|---|
| `public_domain` | Not subject to copyright — chiefly US Government works under 17 USC 105 |
| `open` | An explicit licence permitting reuse (e.g. EU legislative text with attribution) |
| `proprietary` | **Default.** All rights reserved |
| `unknown` | Not yet determined — treated as proprietary |

**Price is not licence.** A freely-readable standard is still copyrighted. A
paid US Government document is still public domain. Conflating the two is
exactly how an ingestion pipeline gets built on material that cannot carry it.

### What the loader enforces

- `ingestion: full` is **rejected** unless `licence` is `public_domain` or
  `open`. Hoping does not make a work free.
- Any source claiming `public_domain` or `open` must carry a `licence_note`
  stating the basis. A claim without a reason is not a claim.
- Both fields default to the restrictive value, so a source added carelessly is
  safe by default.

---

## The public-domain corpus

This is larger than most engineers expect, and it is the corpus's legitimate
bulk-ingestion target. Query it with `kb.ingestible_sources()`.

| Source | What it gives you |
|---|---|
| **DOE-HDBK-1017** Material Science | Textbook-grade fundamentals: crystal structure, stress and strain mechanisms, fracture, fatigue, creep, thermal shock, the ductile-to-brittle transition |
| **DOE-HDBK-1018** Mechanical Science | Pumps, valves, heat exchangers, bearings, seals, fits, mechanical drive |
| **MIL-HDBK-5H** | Aerospace metallic materials, and the methodology behind statistical A- and B-basis allowables, joint and fastener analysis |
| **MIL-STD-1629A** | The original FMECA method — the ancestor of every DFMEA and PFMEA in use today |
| **NASA standards + NTRS** | Fastener design, fracture control, workmanship, structural factors, and decades of engineering reports |
| **FAA AC 43.13** | The best free source on what acceptable workmanship actually looks like — inspection, corrosion, welding, fasteners, sheet metal repair |
| **NIST publications** | Measurement uncertainty, dimensional metrology, materials reference data, MBD research |
| **USACE Engineer Manuals** | Protective coatings, welded structural fabrication, corrosion control for long-life outdoor steelwork |
| **NRC regulatory guides and NUREG** | Acceptable methods for nuclear QA, material qualification, welding, NDE, and decades of failure analysis |
| **US CFR** (21 CFR 820, 174–190; ITAR/EAR) | The regulations themselves |
| **EU legislation** (PED) | The directive text — though the harmonised standards it references are CEN documents and are *not* free |

### Free to read is not free to use

The highest-value free sources in this corpus are **not** ingestible, and the
distinction is worth internalising because it is counter-intuitive:

| Source | Costs money? | Ingestible? |
|---|---|---|
| MIL-HDBK-5H | No | **Yes** — US Government work |
| A paid-for print of a US Government report | Yes | **Yes** — the licence follows the work, not the price |
| IMOA duplex fabrication guidelines | No | **No** — all rights reserved |
| Nickel Institute technical guides | No | **No** — all rights reserved |
| ECSS space standards | No (registration) | **No** — licence agreement, not public domain |

IMOA and the Nickel Institute publish genuinely excellent material for free.
That generosity is not a copyright waiver. Both sit at `facts_only`, and the
corpus states what they establish with attribution — which is legitimate, and is
where the duplex fabrication knowledge in `environments.yaml` and `red_flags.yaml`
came from.

### The NonCommercial trap

Open educational resources look like an obvious ingestion target, and many of
them carry a **CC BY-NC** licence — free to use, *except commercially*. A
revenue-generating platform is a commercial use.

- **CC BY** and **CC BY-SA** — usable commercially with attribution (SA obliges
  you to share adaptations alike, which may not suit a proprietary product).
- **CC BY-NC**, **CC BY-NC-SA**, **CC BY-NC-ND** — **not usable here.** This
  covers a great deal of university courseware, including some of the most
  obvious candidates.
- **CC0 / public domain dedication** — usable without restriction.

Check the specific licence on the specific work. "It's open courseware" is not a
licence determination, and the NC clause is easy to miss precisely because
everything about the material feels free.

### Two more traps in that list

**MIL-HDBK-5H is superseded.** MMPDS replaced it, is maintained under paid
membership, and is the version the FAA accepts for showing compliance. Use
MIL-HDBK-5H for methodology and design principles. Do **not** present its
allowables as current — any actual allowable must come from a licensed current
MMPDS edition.

**NTRS is not uniformly public domain.** It hosts contractor and
journal-published material whose rights are not NASA's to grant. Verify per
document rather than assuming the server.

---

## How a document becomes corpus entries

The pipeline is deliberately not "parse it and let the model figure out when to
use it." That is retrieval-augmented generation, and it reintroduces exactly the
failure mode the platform exists to eliminate: paraphrased numbers with no
traceable basis.

```
  1. VERIFY      licence and ingestion policy, recorded in sources.yaml
  2. FETCH       the document, retaining the original bytes and their hash
  3. EXTRACT     candidate claims — each a threshold, requirement or mechanism
  4. NORMALISE   into a DesignRule / Environment / ChecklistItem / RedFlag
  5. ATTRIBUTE   source_id + page or clause, so the claim resolves to a location
  6. TIER        honestly: standard / vendor / handbook / practice / contested
  7. REVIEW      a human confirms the claim survived extraction intact
  8. COMMIT      the structured entry — never the source text
```

**Step 5 is the point of the whole exercise**, and step 8 is the guard.
The corpus stores structured, attributed claims. It does not store the book.

### If retrieved text is ever surfaced

For `full` sources it is legitimate to quote. If that is built, two rules hold:

- Retrieved passages arrive as **quotations with a page or clause citation**,
  visibly distinct from engine-computed values.
- **Retrieved prose never becomes an engine number.** A number entering a
  calculation must come through the structured pipeline above, with a
  `source_id`, a tier and a `why`. A model summarising a passage into a
  threshold is precisely the hallucination path the platform rules out.

---

## Getting the knowledge without buying the book

The knowledge in the commercial handbooks is not owned by them. Minimum bend
radii, the galvanic series and thread geometry are engineering fact, published
in many places. What the publishers own is their particular expression and
arrangement. Four legitimate routes to the same knowledge, none of which costs
anything:

**1. Borrow it.** Lawful acquisition includes borrowing. Machinery's Handbook
sits in every technical and university library, many public library systems
lend digital technical collections, and alumni access often survives
graduation. A person reading a borrowed copy and extracting facts is doing
exactly what libraries exist for. This is the most overlooked route and the
best one.

**2. Military trade training manuals.** These are the massive textbooks people
are usually reaching for, and they are public domain. The Army TM series and
the Navy NAVEDTRA rate training manuals cover machining, welding, foundry and
patternmaking, and sheet-metal layout at genuine teaching depth — written to
take a reader from nothing to competent, which makes them unusually good source
material for a curriculum. Dated on speeds, feeds and specific alloys; not
dated on geometry, mechanism or practice.

**3. Pre-1930 editions.** US copyright has expired on works published before
1930, so the earliest editions of several still-current handbooks are public
domain and available in full from library scanning projects. Thread forms, gear
geometry, mechanics and fits were settled a century ago and have not moved.
**The licence attaches to the edition, never to the title** — a current edition
of the same book is fully protected.

**4. Patents.** Published by governments specifically to teach the invention,
free in full text, and containing process detail rarely published elsewhere:
parameter windows, tooling arrangements, and the failure modes the applicant had
to design around. The patent restricts *practising* the invention, not reading
or describing it. Treat each as one practitioner's account rather than as
consensus.

### What does not count

Downloading a pirated copy of the handbook. Same copy, same problem, and it
poisons everything downstream — under the AI-training decisions to date, the
lawfulness of how the material was obtained is treated separately from what was
done with it afterwards. A clean process on an unlawfully obtained copy is not
clean.

## The licensed works, and what to do about them

Machinery's Handbook, the ASM Handbook, Shigley, Kalpakjian, Roark, Peterson,
Bralla, Campbell, the AWS Welding Handbook. These are the field's canonical
references and there is no free substitute for several of them.

The legitimate route is to **buy access**. Publishers license digitally to
enterprises; Industrial Press and ASM both do. Two reasons it is worth it beyond
staying clean:

1. **Clause-level citation is a differentiator.** Competitors will not bother.
   Auditors notice immediately.
2. **It converts a liability into a moat.** Licensed content you may cite is an
   asset. Scraped content you must not admit to is the opposite.

Until then, those sources sit at `facts_only`: read them, understand them, state
what they establish with attribution — which is what a well-taught engineer does
anyway, and what this corpus already is.
