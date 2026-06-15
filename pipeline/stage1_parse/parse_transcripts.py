import argparse
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


FILENAME_RE = re.compile(r"^(?P<interview_id>\d+)\.(?P<part_number>\d+)\.xml$")
SPEAKER_RE = re.compile(r"^\s*(?P<label>[A-Za-z]{1,10})\s*:")


@dataclass(frozen=True)
class ParsedFilename:
    interview_id: int | None
    part_number: int | None


def parse_filename(filename: str) -> ParsedFilename:
    """Parse filenames like `123.1.xml` into (interview_id, part_number)."""
    match = FILENAME_RE.match(filename)
    if not match:
        return ParsedFilename(interview_id=None, part_number=None)
    return ParsedFilename(
        interview_id=int(match.group("interview_id")),
        part_number=int(match.group("part_number")),
    )


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def iter_children_by_tag(element: ET.Element, tag_name: str) -> Iterable[ET.Element]:
    """Iterate descendants matching `tag_name`, robust to XML namespaces."""
    for child in element.iter():
        if _strip_namespace(child.tag) == tag_name:
            yield child


def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_xml_transcript(xml_path: Path) -> list[dict[str, Any]]:
    """Parse a single XML transcript file into utterance rows."""
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        raise RuntimeError(f"XML parse error in {xml_path}: {exc}") from exc

    root = tree.getroot()
    parsed = parse_filename(xml_path.name)

    utterances: list[dict[str, Any]] = []

    for paragraph in iter_children_by_tag(root, "p"):
        tokens: list[str] = []
        timestamps: list[int] = []
        speaker_labels: set[str] = set()

        spans = list(iter_children_by_tag(paragraph, "span"))
        if not spans:
            raw_text = " ".join(
                text.strip() for text in paragraph.itertext() if text and text.strip()
            )
            if raw_text:
                tokens.append(raw_text)

                speaker_match = SPEAKER_RE.match(raw_text)
                if speaker_match:
                    speaker_labels.add(speaker_match.group("label").strip())
            span_iter: list[ET.Element] = []
        else:
            span_iter = spans

        for span in span_iter:
            timestamp = safe_int(span.attrib.get("m"))
            if timestamp is not None:
                timestamps.append(timestamp)

            for fragment in (span.text, span.tail):
                text = (fragment or "").strip("\n")
                if text:
                    tokens.append(text)

                    speaker_match = SPEAKER_RE.match(text)
                    if speaker_match:
                        speaker_labels.add(speaker_match.group("label").strip())

        utterance_text = " ".join(tokens).strip()
        if not utterance_text:
            continue

        start_ts = min(timestamps) if timestamps else None
        end_ts = max(timestamps) if timestamps else None

        utterances.append(
            {
                "interview_id": parsed.interview_id,
                "part_number": parsed.part_number,
                "filename": xml_path.name,
                "text": utterance_text,
                "start_timestamp": start_ts,
                "end_timestamp": end_ts,
                "speakers": ", ".join(sorted(speaker_labels)) if speaker_labels else None,
                "word_count": len(utterance_text.split()),
                "char_count": len(utterance_text),
            }
        )

    return utterances


def process_transcripts_dir(transcripts_dir: Path, recursive: bool) -> pd.DataFrame:
    pattern = "**/*.xml" if recursive else "*.xml"
    xml_files = sorted(transcripts_dir.glob(pattern))
    if not xml_files:
        raise FileNotFoundError(
            f"No .xml files found in {transcripts_dir} (recursive={recursive})"
        )

    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for i, xml_path in enumerate(xml_files, start=1):
        if i == 1 or i % 100 == 0:
            print(f"Parsing {i}/{len(xml_files)}: {xml_path.name}")

        try:
            rows.extend(parse_xml_transcript(xml_path))
        except Exception as exc:  # noqa: BLE001 - pipeline should continue
            errors.append(f"{xml_path}: {exc}")

    if errors:
        print("\nWarnings: some files could not be parsed")
        for msg in errors[:20]:
            print(f"- {msg}")
        if len(errors) > 20:
            print(f"- ... and {len(errors) - 20} more")

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError("No utterances extracted (output DataFrame is empty)")

    df["duration_ms"] = df["end_timestamp"] - df["start_timestamp"]
    df["duration_minutes"] = df["duration_ms"] / (1000 * 60)
    return df


def create_interview_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    if "interview_id" not in df.columns:
        raise ValueError("Missing expected column 'interview_id'")

    if df["interview_id"].isna().any():
        print(
            "Warning: some interview_id values are missing; interview_summary.parquet "
            "will exclude those rows."
        )

    df_valid = df.dropna(subset=["interview_id"]).copy()
    if df_valid.empty:
        return df_valid

    df_valid["interview_id"] = df_valid["interview_id"].astype(int)

    summary = (
        df_valid.groupby("interview_id")
        .agg(
            max_part_number=("part_number", "max"),
            total_words=("word_count", "sum"),
            total_chars=("char_count", "sum"),
            total_duration_minutes=("duration_minutes", "sum"),
            all_speakers=(
                "speakers",
                lambda series: ", ".join(
                    sorted(
                        {
                            label
                            for speakers in series.dropna().tolist()
                            for label in str(speakers).split(", ")
                            if label
                        }
                    )
                ),
            ),
            parts_count=("part_number", pd.Series.nunique),
        )
        .reset_index()
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse XML transcript files into parquet tables."
    )
    parser.add_argument(
        "--transcripts-dir",
        type=Path,
        required=True,
        help="Directory containing .xml transcript files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
        help="Output directory where parquet files will be written.",
    )
    parser.add_argument(
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Search for XML files recursively under transcripts-dir (default: true).",
    )

    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    df = process_transcripts_dir(args.transcripts_dir, recursive=args.recursive)
    utterances_path = args.output_dir / "utterances.parquet"
    df.to_parquet(utterances_path, index=False)
    print(f"\nSaved {len(df):,} utterances → {utterances_path}")

    interview_summary = create_interview_summary(df)
    if not interview_summary.empty:
        summary_path = args.output_dir / "interview_summary.parquet"
        interview_summary.to_parquet(summary_path, index=False)
        print(f"Saved {len(interview_summary):,} interviews → {summary_path}")


if __name__ == "__main__":
    main()
