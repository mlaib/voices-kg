# Licensing of VOICES KG v2 components

The VOICES Knowledge Graph release is composed of several artefact types
with different copyright origins. The licence applied to each component
reflects that origin.

| Component | Files / locations | Licence |
|---|---|---|
| **Code** | `src/`, `app/`, `admin/`, `scripts/`, `docker/`, `Makefile`, all `.py` and `.sh` files | **Apache License 2.0** — see [`LICENSE`](LICENSE) |
| **Ontology** | `schema/voices_ontology_v2.ttl` | **CC BY 4.0** |
| **Alignment graph** | `schema/voices-alignment-v2.ttl` | **CC BY 4.0** |
| **Evaluation rubrics, samples, judgments** | `evaluation/**/*.csv`, `evaluation/**/*.md` | **CC BY 4.0** |
| **Evaluation scripts** | `evaluation/**/*.py` | **Apache License 2.0** |
| **Knowledge graph (public dump)** | `output/kg2026_v2_public.nq` | **CC BY 4.0** — derived structured data only; transcript text is excluded (see below) |
| **Knowledge graph (full dump)** | `output/kg2026_v2.nq` | **Not redistributed.** See *Transcript text* below. |

## Transcript text

The full N-Quads dump (`output/kg2026_v2.nq`) embeds the literal transcript
text of the survivor testimonies via the `voices:transcriptText` property.
That text is sourced from the **USC Shoah Foundation Visual History
Archive (VHA)** and remains the property of its rights-holders.

- The publicly downloadable dump (`output/kg2026_v2_public.nq`) **excludes
  all `voices:transcriptText` literals**. It contains every other graph
  (interviews, segments, narrated events, places, emotions, embeddings,
  alignments, provenance, metadata) and is licensed under CC BY 4.0.
- For the original transcript text, please refer directly to the
  **USC Shoah Foundation Visual History Archive**:
  <https://sfi.usc.edu/vha>. Access requires registration with USC SFI.
- Researchers who already hold their own VHA access and wish to obtain
  the full N-Quads dump (with transcripts) for replication purposes may
  contact the maintainer (see below). Distribution of the full dump is
  governed by the user's own agreement with USC SFI, not by the licences
  in this file.

## How to attribute

When reusing the CC BY 4.0 components (ontology, alignment graph,
evaluation rubrics, public KG dump), please cite:

> Pruski, C., Laib, M., Da Silveira, M., Toth, G. M. (2026). VOICES
> Knowledge Graph v2 — Holocaust survivor testimonies encoded as RDF
> events, emotions, places, and temporal alignments.
> Luxembourg Institute of Science and Technology (LIST).

A BibTeX entry is provided in the Streamlit "Downloads" page of the
deployed application.

## Contact

For questions about licensing, requests for the full dump, or to report
attribution issues:

> **Mohamed Laib** — `mohamed.laib@list.lu`
> Luxembourg Institute of Science and Technology (LIST)

## Full licence texts

- Apache License 2.0: <http://www.apache.org/licenses/LICENSE-2.0>
  (also reproduced in [`LICENSE`](LICENSE))
- Creative Commons Attribution 4.0 International (CC BY 4.0):
  <https://creativecommons.org/licenses/by/4.0/>
