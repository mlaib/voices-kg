#!/usr/bin/env python3
"""
Run an OOPS! (OntOlogy Pitfall Scanner) evaluation of the VOICES ontology and
save an HTML report.

Why this exists instead of WIDOCO's built-in ``-oops``:
WIDOCO sends the ontology *with* its owl:imports to the OOPS! web service. OOPS!
cannot dereference the local module IRIs and silently returns an empty result
("Congratulations! OOPS did not find a single pitfall") — a misleading all-clear.
This script instead evaluates the VOICES ontology with its imports stripped, which
is what OOPS! can actually parse, giving the true VOICES-scoped pitfall report.

Note: with imports stripped, the external parent terms (CIDOC-CRM, OA, MFOEM, ...)
appear as P34/P35 "untyped class/property". Those are expected references to
imported terms, not defects in the VOICES schema.

Usage:
    python scripts/oops-check.py [ONTOLOGY.ttl] [OUTPUT.html]
Defaults: schema/voices_ontology_v2.ttl  ->  public/oops.html
Exit code is always 0 (the report is informational); the pitfall summary is printed.
"""
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from rdflib import Graph, OWL

OOPS_ENDPOINT = "https://oops.linkeddata.es/rest"
NS = {"oops": "http://www.oeg-upm.net/oops"}

ROOT = Path(__file__).resolve().parent.parent
ONT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "schema" / "voices_ontology_v2.ttl"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "public" / "oops.html"


def oops_request(rdfxml: str, output_format: str) -> str:
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<OOPSRequest><OntologyURI></OntologyURI>"
        f"<OntologyContent><![CDATA[\n{rdfxml}\n]]></OntologyContent>"
        f"<Pitfalls></Pitfalls><OutputFormat>{output_format}</OutputFormat></OOPSRequest>"
    )
    req = urllib.request.Request(
        OOPS_ENDPOINT, data=body.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
    )
    with urllib.request.urlopen(req, timeout=150) as r:
        return r.read().decode("utf-8", "replace")


def main() -> int:
    g = Graph()
    g.parse(str(ONT), format="turtle")
    g.remove((None, OWL.imports, None))          # OOPS! cannot resolve the local modules
    rdfxml = g.serialize(format="xml")

    # 1) HTML report for publishing
    try:
        html = oops_request(rdfxml, "RDF/XML")    # OOPS returns an HTML page for this endpoint mode
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(html, encoding="utf-8")
        print(f"OOPS! report written to {OUT}")
    except Exception as e:                         # noqa: BLE001 - external service may be down
        print(f"WARNING: could not fetch OOPS! HTML report: {e}", file=sys.stderr)

    # 2) Machine-readable summary for the CI log
    try:
        xml_out = oops_request(rdfxml, "XML")
        root = ET.fromstring(xml_out)
        pitfalls = root.findall("oops:Pitfall", NS)
        if not pitfalls:
            print("OOPS! summary: no pitfalls reported.")
        else:
            print(f"OOPS! summary: {len(pitfalls)} pitfall type(s):")
            for p in pitfalls:
                code = p.findtext("oops:Code", "", NS)
                imp = p.findtext("oops:Importance", "", NS)
                name = p.findtext("oops:Name", "", NS)
                n = p.findtext("oops:NumberAffectedElements", "?", NS)
                note = "  (external refs — expected)" if code in {"P34", "P35"} else ""
                print(f"  {code} [{imp}] {name} -> {n} affected{note}")
    except Exception as e:                         # noqa: BLE001
        print(f"WARNING: could not parse OOPS! XML summary: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
