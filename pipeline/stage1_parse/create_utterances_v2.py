import argparse
from pathlib import Path

import pandas as pd


def fill_speakers_with_forward_fill(df: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill missing speakers within each interview and add an `ID` column."""
    required_cols = {"interview_id", "start_timestamp", "end_timestamp", "speakers"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Input is missing required columns: {sorted(missing)}")

    result = df.copy()
    result["_original_order"] = range(len(result))

    sort_cols = [
        "interview_id",
        "part_number",
        "start_timestamp",
        "end_timestamp",
        "_original_order",
    ]
    sort_cols = [col for col in sort_cols if col in result.columns]
    result = result.sort_values(sort_cols, kind="mergesort")

    result["speakers"] = result["speakers"].replace("None", pd.NA)
    result["speakers"] = result.groupby("interview_id")["speakers"].ffill()
    result["speakers"] = result["speakers"].fillna("None")

    result["ID"] = (
        result["interview_id"].astype(str)
        + "_"
        + result["start_timestamp"].astype(str)
        + "_"
        + result["end_timestamp"].astype(str)
    )

    result = result.sort_values("_original_order", kind="mergesort")
    return result.drop(columns="_original_order")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create utterances_v2 parquet with forward-filled speakers."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/processed/utterances.parquet"),
        help="Path to the source utterances parquet.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("data/processed/utterances_v2.parquet"),
        help="Path to the output utterances_v2 parquet.",
    )
    args = parser.parse_args()

    df = pd.read_parquet(args.source)
    transformed = fill_speakers_with_forward_fill(df)
    args.target.parent.mkdir(parents=True, exist_ok=True)
    transformed.to_parquet(args.target, index=False)
    print(f"Saved {len(transformed):,} rows → {args.target}")


if __name__ == "__main__":
    main()
