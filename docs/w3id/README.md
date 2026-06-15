# w3id registration for the VOICES ontology namespace

The ontology namespace was re-based from `http://voices.uni.lu/ontology#` (a domain
LIST does not control) to **`https://w3id.org/voices/ontology#`** — a persistent,
dereferenceable identifier we control.

`voices/.htaccess` is the ready-to-submit redirect. To activate it:

1. Fork <https://github.com/perma-id/w3id.org>.
2. Copy the `voices/` directory (with its `.htaccess`) into the fork.
3. Open a pull request. Once merged, `https://w3id.org/voices/ontology` resolves
   (Turtle for RDF clients, the GitHub page for browsers) and the version IRI
   `https://w3id.org/voices/ontology/2.1` works.
4. Verify: `curl -sIL -H "Accept: text/turtle" https://w3id.org/voices/ontology`

To move the canonical copy later (e.g. to `voices.list.lu/ontology`), just edit the
redirect targets in `voices/.htaccess` and open another PR — the IRIs never change.
