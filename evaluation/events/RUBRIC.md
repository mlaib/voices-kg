# Event-extraction quality - rubric for human review

Goal: for each row in `judgments.csv`, decide for each extracted
dimension whether the LLM-derived value matches what the source
utterance actually says.

Each row carries:
- `segment_text`: the original utterance the survivor spoke
- `participants`, `activities`, `locations`, `causes`, `modes`,
  `temporal`, `emotions`, `historical`: the dimensions the
  extraction pipeline produced for that utterance
- `judgment_<dim>`: the cell you fill — `correct`, `incorrect`, or
  `unsure`

Read the `segment_text`, then for each dimension column decide:

## Decision rules per dimension

### participants
- **correct**: every named participant in the extraction can be
  reasonably inferred from the utterance (including pronoun
  resolution to a known person from earlier context).
- **incorrect**: a participant is fabricated, or an obvious
  participant is missing, or names are mangled.
- **unsure**: the extraction names a "his-younger-brothers" or
  similar derived name that you can neither confirm nor refute
  from the utterance alone.

### activity
- **correct**: the chosen `voices:Activity` instance fits the action
  described in the utterance (e.g. utterance about being put on a
  cattle car → activity = `deportation`).
- **incorrect**: the activity contradicts the utterance, or is
  meaningfully wrong (e.g. activity=`liberation` for an utterance
  about being captured).
- **unsure**: the utterance is too short or abstract to match any
  controlled activity, and the extraction picked a plausible default.

### location
- **correct**: the place mentioned in the extraction is the place
  the utterance actually refers to. For interview-context utterances
  ("I want to thank you for being here today"), an empty/no-place
  extraction is correct.
- **incorrect**: the place is a hallucination, or the wrong place was
  picked from a list of mentioned places.
- **unsure**: the utterance ambiguously references a place.

### temporal
- **correct**: the `temporal` (`whenText`) string captures what the
  utterance says about timing. An empty value when the utterance has
  no temporal reference is also correct.
- **incorrect**: the temporal value is wrong (e.g. "1944" when the
  utterance clearly says "before the war").
- **unsure**: the utterance has implicit temporal context.

### emotion
- **correct**: the macro-category (`positive`, `neutral`,
  `negative_low_arousal`, `negative_high_arousal`) reasonably
  reflects the emotional valence the survivor expresses. Empty
  emotion for descriptive / factual utterances is correct.
- **incorrect**: the emotion is opposite of what the utterance
  conveys.
- **unsure**: ambiguous emotional content.

## Output

Once filled in, run:

    python compute_precision.py judgments.csv

Prints per-dimension precision plus a macro-averaged figure suitable
for direct quotation in §5.3.3 of the paper.
