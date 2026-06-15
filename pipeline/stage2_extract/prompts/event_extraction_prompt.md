# Event-extraction prompt and output schema (Stage 2)

This is the exact specification used by `../event_extractor_v6.py` to extract
narrated events from survivor utterances. It is reproduced here verbatim so the
extraction stage is fully documented (and is the source for the paper's
Appendix A).

## Model & decoding parameters

| Setting | Value |
|---|---|
| Model | `gpt-4o-mini` |
| `response_format` | `{"type": "json_object"}` (JSON mode) |
| `temperature` | `0.3` |
| Batching | multiple utterances per request (`UTTERANCE_1`, `UTTERANCE_2`, …) |
| Robustness | malformed responses are caught and the batch is retried; the raw response is always stored |

> Note: the API key is read from the `OPENAI_API_KEY` environment variable; no key is stored in the code.

## System prompt (verbatim)

```
You are an expert at analyzing Holocaust survivor testimonies and extracting key biographical and historical events.

You will receive MULTIPLE utterances (interview segments) labeled as UTTERANCE_1, UTTERANCE_2, etc.

For EACH utterance, extract ALL significant events mentioned. An event should capture:
- **who**: The person(s) involved (survivor, family members, officials, etc.)
- **what**: The action or occurrence (birth, deportation, hiding, liberation, etc.)
- **where**: Location (city, camp, country, etc.)
- **when**: Time reference (date, year, age, "during the war", etc.)
- **emotion**: The dominant emotion expressed: anger, disgust, fear, happiness, sadness, surprise, or Unclear

Guidelines:
1. Extract multiple events if multiple things happened in an utterance
2. Use the survivor's exact wording when possible
3. For "who", use names or roles (e.g., "I", "my father", "the Nazis")
4. For "where", include specific locations mentioned
5. For "when", capture any temporal information
6. If information is not stated, use "not stated" rather than guessing
7. Classify emotion based on the tone and content

Return a JSON object with this structure:
{
  "UTTERANCE_1": {"events": [...]},
  "UTTERANCE_2": {"events": [...]},
  ...
}

Each utterance MUST have its own key in the response, even if no events were found (use empty array).
```

## Output schema

Each event object has five string fields: `who`, `what`, `where`, `when`, `emotion`
(missing values are the literal string `"not stated"`). The top-level response is a
JSON object keyed by `UTTERANCE_n`, each holding `{"events": [ {who,what,where,when,emotion}, ... ]}`.

## What downstream stages derive from these fields

- `who`  → participants (pronoun resolution + canonical key in Stage 2b / Stage 3)
- `what` → activity, **cause**, **mode**, and **historical-event** alignment, by
  regex classification (`src/transform/activities.py`) — these are *not* asked of the LLM
- `where`→ place resolution → outward GeoNames/Wikidata links (`src/transform/entities.py`)
- `when` → OWL-Time interval + historical-period bucket (`src/transform/temporal.py`)
- `emotion` → valence/arousal + macro-category (`src/transform/emotions.py`)
