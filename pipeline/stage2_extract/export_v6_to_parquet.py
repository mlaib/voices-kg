#!/usr/bin/env python3
"""
Export V6 extracted events from SQLite to Parquet format
"""
import sqlite3
import json
import pandas as pd
from pathlib import Path

# Connect to V6 checkpoint database
db_path = "data/processed/.checkpoints/event_extraction_v6.db"
conn = sqlite3.connect(db_path)

print("Loading processed utterances from database...")
df = pd.read_sql_query("""
    SELECT
        utterance_id,
        interview_id,
        utterance_hash,
        event_count,
        input_tokens,
        output_tokens,
        cost_usd,
        response_time_ms,
        raw_response,
        parsed_successfully,
        processed_at
    FROM processed_utterances
    WHERE status = 'success'
    ORDER BY interview_id, utterance_id
""", conn)

print(f"Loaded {len(df):,} utterances")

# Parse events from raw_response
all_events = []

for idx, row in df.iterrows():
    if idx % 10000 == 0:
        print(f"Processing {idx:,}/{len(df):,} utterances...")

    try:
        response_data = json.loads(row['raw_response'])

        # Handle both response formats
        if isinstance(response_data, list):
            events = response_data
        elif isinstance(response_data, dict):
            events = response_data.get('events', [])
        else:
            events = []

        # Add each event with utterance metadata
        for event in events:
            # Ensure event is a dict
            if not isinstance(event, dict):
                continue

            # Convert all fields to strings (handle cases where OpenAI returns lists/other types)
            def to_str(value):
                if isinstance(value, str):
                    return value
                elif isinstance(value, list):
                    return ', '.join(str(v) for v in value)
                elif value is None:
                    return 'not stated'
                else:
                    return str(value)

            all_events.append({
                'utterance_id': row['utterance_id'],
                'interview_id': row['interview_id'],
                'utterance_hash': row['utterance_hash'],
                'who': to_str(event.get('who', 'not stated')),
                'what': to_str(event.get('what', 'not stated')),
                'where': to_str(event.get('where', 'not stated')),
                'when': to_str(event.get('when', 'not stated')),
                'emotion': to_str(event.get('emotion', 'Unclear')),
            })
    except json.JSONDecodeError:
        # Skip malformed responses
        continue

# Create events dataframe
events_df = pd.DataFrame(all_events)

# Save to parquet
output_path = "data/processed/events_v6.parquet"
Path(output_path).parent.mkdir(parents=True, exist_ok=True)
events_df.to_parquet(output_path, index=False)

print(f"\n✅ Exported {len(events_df):,} events to {output_path}")

# Also save utterance-level summary
summary_path = "data/processed/utterances_v6_summary.parquet"
df_summary = df[['utterance_id', 'interview_id', 'utterance_hash',
                  'event_count', 'input_tokens', 'output_tokens',
                  'cost_usd', 'response_time_ms', 'parsed_successfully',
                  'processed_at']].copy()
df_summary.to_parquet(summary_path, index=False)

print(f"✅ Exported utterance summary to {summary_path}")

# Print statistics
print("\n" + "=" * 80)
print("EXPORT SUMMARY")
print("=" * 80)
print(f"Utterances processed: {len(df):,}")
print(f"Events extracted: {len(events_df):,}")
print(f"Events per utterance: {len(events_df)/len(df):.2f}")
print(f"Parse success rate: {df['parsed_successfully'].mean()*100:.2f}%")
print(f"Total cost: ${df['cost_usd'].sum():.4f}")
print("\nEmotion distribution:")
print(events_df['emotion'].value_counts())
print("=" * 80)

conn.close()
