# Alignment-quality evaluation — rubric

**Goal:** for each row in `judgments.csv`, decide whether the link from
`place_iri` (a place mentioned in a survivor testimony) to `target_iri`
(its candidate match in GeoNames or Wikidata) is **correct**,
**incorrect**, or **unsure**.

Open the place name in `place_label`, then click `target_browse_url`
to inspect the target authority's page. Fill the `judgment` and
optional `notes` columns.

## Decision rules

### Mark **correct** when
- The target IRI denotes the **same real-world place** the survivor
  was talking about. Town/city names with country qualifiers
  (e.g. `Andresy France` → GeoNames Andrésy, Île-de-France) count as
  correct when the country and region match.
- A camp / ghetto / barracks place name resolves to the canonical
  Wikidata entity for that camp / ghetto / barracks (e.g.
  `Camp Forrest Tennessee USA Military Base` → GeoNames Camp Forrest).
- A historical settlement that has since been renamed or absorbed
  resolves to its modern successor when it is the most specific
  authority entry available.
- The target page describes a **larger administrative entity that
  contains** the place when the place itself has no authority entry
  (e.g. a small village → its commune). Add a note in the `notes`
  column flagging this case.

### Mark **incorrect** when
- The target denotes a **different real-world place** with a similar
  name (e.g. `Camp Lee Virginia USA` matched to `Camp Lee, Tennessee`).
- The target is the **wrong type of entity** (e.g. a person, an event,
  a fictional location) instead of a place.
- The target is a **disambiguation page** without a direct correspondence
  to the survivor's mention.
- The target is **substantially less specific** than the place name
  warrants (e.g. matching `Treblinka` to "Poland" rather than to the
  Treblinka extermination camp).

### Mark **unsure** when
- The place name in `place_label` is so ambiguous that no human
  expert could decide without more context (e.g. `Generic Village`,
  `Unnamed Town`).
- The target authority page is broken / no longer accessible.
- The judgment depends on a controversial interpretation that the
  reviewer wants to flag for discussion.

## Output

Once all 200 rows have a `judgment` value, run:

    python compute_precision.py judgments.csv

This prints overall precision, per-authority precision (geonames vs
wikidata), the unsure rate, and an example list of every `incorrect`
row for follow-up.
