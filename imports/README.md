# Import modules

This directory holds **minimal import modules** for the external ontologies reused
by the VOICES ontology (`schema/voices_ontology_v2.ttl`).

## Why

A reviewer noted that importing external ontologies *in full* (`owl:imports` of the
whole ontology) is not good practice — it is preferable to import only the parts and
axioms relevant to the application/domain. These modules implement that: each one
contains only the reused terms (plus the relevant context), instead of the thousands
of axioms in the source ontologies.

The VOICES ontology imports these module IRIs (not the upstream ontologies):

| Import IRI | Module file | Source | Reused terms |
|---|---|---|---|
| `…/imports/cidoc-crm` | `cidoc-crm-module.ttl` | CIDOC-CRM 7.1.3 | 6 classes, 8 properties |
| `…/imports/time`      | `time-module.ttl`      | OWL-Time         | `time:Interval` |
| `…/imports/ma-ont`    | `ma-ont-module.ttl`    | W3C Media Ontology | `ma:MediaResource`, `ma:MediaFragment` |
| `…/imports/oa`        | `oa-module.ttl`        | W3C Web Annotation | `oa:Annotation`, `oa:hasBody` |
| `…/imports/mfoem`     | `mfoem-module.ttl`     | MFOEM (Emotion Ontology) | `MFOEM_000001` (emotion process) |

`…` = `https://w3id.org/voices/ontology`.

**PROV-O was removed**: it was imported but no `prov:` term is actually used.

## How the modules were built

See [`../scripts/extract-import-modules.sh`](../scripts/extract-import-modules.sh).
Built with [ROBOT](https://github.com/ontodev/robot):

- **CRM, OWL-Time, OA, MA** — `robot extract --method MIREOT` (Minimum Information to
  Reference an External Ontology Term): keeps each reused term, its ancestor hierarchy
  and labels/definitions — nothing else.
- **MFOEM** — `robot filter` keeping only `MFOEM_000001` and its own annotations. Its
  MIREOT ancestor chain is pure BFO/IAO upper-ontology scaffolding, not relevant to the
  VOICES domain, so it is deliberately excluded.

The exact reused IRIs per source are listed in [`terms/`](terms/).

## How imports resolve

`schema/catalog-v001.xml` (an OASIS XML catalog) maps each module IRI to its local file.
Protégé, the OWL API, ROBOT and WIDOCO all honour this catalog, so the ontology loads
offline with no network dereferencing.

## Rebuilding

```bash
ROBOT="java -jar /path/to/robot.jar" scripts/extract-import-modules.sh
```
