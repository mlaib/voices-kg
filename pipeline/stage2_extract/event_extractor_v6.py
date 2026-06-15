#!/usr/bin/env python3
"""
Event Extractor V6 - Interactive OpenAI with User Validation

Features:
- 4-worker multiprocessing (CPU-friendly)
- User-in-the-loop validation with 10-second auto-continue
- Dynamic rate limiting based on API response times
- Saves ALL responses (even malformed JSON)
- Interactive controls: continue/skip/quit
- Non-blocking keyboard input

 
Date: 2025-11-03
"""

import os
import sys
import json
import time
import sqlite3
import logging
import argparse
import hashlib
import select
import termios
import tty
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from multiprocessing import Pool, Manager, Lock
from collections import deque

import pandas as pd
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================================
# Configuration
# ============================================================================

MODEL_NAME = "gpt-4o-mini"
UTTERANCES_PER_API_CALL = 5     # Send 5 utterances per API call (batched)
BATCH_SIZE = 50                 # Process 50 batches in parallel (10 batches × 5 utterances = 250 utterances at once)
NUM_WORKERS = 10                # 10 concurrent API calls (each handling 5 utterances)
MIN_WORD_COUNT = 10             # Skip very short utterances

# Cost configuration (gpt-4o-mini pricing per 1M tokens)
INPUT_COST_PER_1M = 0.15
OUTPUT_COST_PER_1M = 0.60
DEFAULT_BUDGET_LIMIT = 50.0

# Rate limiting configuration
RESPONSE_TIME_WINDOW = 10       # Monitor last 10 API calls
SLOWDOWN_THRESHOLD = 1.5        # Pause if response time increases by 50%
PAUSE_DURATION = 60             # Pause for 60 seconds when rate limited

# User interaction configuration
VALIDATION_TIMEOUT = 0          # No validation delay for speed test
TEXT_TRUNCATE_LENGTH = 200      # Show first 200 chars of utterance

# System prompt for batched processing
SYSTEM_PROMPT = """You are an expert at analyzing Holocaust survivor testimonies and extracting key biographical and historical events.

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

Each utterance MUST have its own key in the response, even if no events were found (use empty array)."""


# ============================================================================
# Logging Setup
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('v6_production.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# Checkpoint Database (with raw response storage)
# ============================================================================

class CheckpointDB:
    """SQLite database for tracking processed utterances with raw responses."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.lock = Lock()
        self._init_tables()

    def _init_tables(self):
        """Create tables if they don't exist."""
        cursor = self.conn.cursor()

        # Enable WAL mode for better concurrent write performance
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_utterances (
                utterance_hash TEXT PRIMARY KEY,
                utterance_id TEXT,
                interview_id INTEGER,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                event_count INTEGER,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cost_usd REAL,
                response_time_ms INTEGER,
                raw_response TEXT,
                parsed_successfully INTEGER DEFAULT 1,
                status TEXT DEFAULT 'success',
                user_validated INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS extraction_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_processed INTEGER,
                total_events INTEGER,
                total_cost_usd REAL,
                avg_response_time_ms REAL,
                parse_success_rate REAL
            )
        """)

        self.conn.commit()

    def is_processed(self, utterance_hash: str) -> bool:
        """Check if utterance already processed successfully."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT 1 FROM processed_utterances WHERE utterance_hash = ? AND status = 'success'",
                (utterance_hash,)
            )
            return cursor.fetchone() is not None

    def mark_processed(self, utterance_hash: str, utterance_id: str, interview_id: int,
                      event_count: int, input_tokens: int, output_tokens: int,
                      cost_usd: float, response_time_ms: int, raw_response: str,
                      parsed_successfully: bool, user_validated: bool = False):
        """Save processing record with raw response."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO processed_utterances
                (utterance_hash, utterance_id, interview_id, event_count,
                 input_tokens, output_tokens, cost_usd, response_time_ms,
                 raw_response, parsed_successfully, user_validated, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'success')
            """, (utterance_hash, utterance_id, interview_id, event_count,
                  input_tokens, output_tokens, cost_usd, response_time_ms,
                  raw_response, 1 if parsed_successfully else 0, 1 if user_validated else 0))
            self.conn.commit()

    def mark_processed_bulk(self, records: List[Tuple]) -> None:
        """Bulk insert processing records - 10x faster than individual inserts."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO processed_utterances
                (utterance_hash, utterance_id, interview_id, event_count,
                 input_tokens, output_tokens, cost_usd, response_time_ms,
                 raw_response, parsed_successfully, user_validated, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'success')
            """, records)
            self.conn.commit()

    def get_processed_hashes(self) -> set:
        """Get all processed utterance hashes at once - for fast filtering."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT utterance_hash FROM processed_utterances WHERE status = 'success'")
            return {row[0] for row in cursor.fetchall()}

    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics."""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(*) as processed,
                    SUM(event_count) as total_events,
                    SUM(cost_usd) as total_cost,
                    AVG(response_time_ms) as avg_response_time,
                    AVG(parsed_successfully) as parse_success_rate
                FROM processed_utterances
                WHERE status = 'success'
            """)
            row = cursor.fetchone()

            if row and row[0]:
                return {
                    'total_processed': row[0],
                    'total_events': row[1] or 0,
                    'total_cost_usd': row[2] or 0.0,
                    'avg_response_time_ms': row[3] or 0.0,
                    'parse_success_rate': row[4] or 0.0
                }

            return {
                'total_processed': 0,
                'total_events': 0,
                'total_cost_usd': 0.0,
                'avg_response_time_ms': 0.0,
                'parse_success_rate': 0.0
            }

    def close(self):
        """Close database connection."""
        self.conn.close()


# ============================================================================
# Response Time Monitor (for dynamic rate limiting)
# ============================================================================

class ResponseTimeMonitor:
    """Monitor API response times and detect slowdowns."""

    def __init__(self, window_size: int = RESPONSE_TIME_WINDOW):
        self.window_size = window_size
        self.response_times = deque(maxlen=window_size)
        self.baseline_time = None

    def add_response_time(self, response_time_ms: int):
        """Add a response time measurement."""
        self.response_times.append(response_time_ms)

        # Set baseline after first few calls
        if self.baseline_time is None and len(self.response_times) >= 3:
            self.baseline_time = sum(self.response_times) / len(self.response_times)

    def should_pause(self) -> bool:
        """Check if we should pause due to slowdown."""
        if not self.baseline_time or len(self.response_times) < self.window_size:
            return False

        current_avg = sum(self.response_times) / len(self.response_times)
        slowdown_ratio = current_avg / self.baseline_time

        return slowdown_ratio >= SLOWDOWN_THRESHOLD

    def get_current_avg(self) -> float:
        """Get current average response time."""
        if not self.response_times:
            return 0.0
        return sum(self.response_times) / len(self.response_times)


# ============================================================================
# Keyboard Input Handler (non-blocking with timeout)
# ============================================================================

def get_key_with_timeout(timeout_seconds: int) -> Optional[str]:
    """
    Wait for keyboard input with timeout.
    Returns the key pressed, or None if timeout.
    """
    # Check if stdin is a terminal (interactive mode)
    if not sys.stdin.isatty():
        # Non-interactive mode (background, pipe, etc.) - just sleep
        time.sleep(timeout_seconds)
        return None

    # Save terminal settings
    old_settings = termios.tcgetattr(sys.stdin)

    try:
        # Set terminal to raw mode
        tty.setraw(sys.stdin.fileno())

        # Wait for input with timeout
        rlist, _, _ = select.select([sys.stdin], [], [], timeout_seconds)

        if rlist:
            key = sys.stdin.read(1)
            return key
        else:
            return None

    finally:
        # Restore terminal settings
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


def display_validation(utterance_text: str, events: List[Dict[str, str]],
                      stats: Dict[str, Any], parsed_ok: bool):
    """Display utterance and extracted events for user validation."""
    print("\n" + "=" * 80)
    print("VALIDATION WINDOW (10 seconds)")
    print("=" * 80)

    # Show truncated text
    truncated_text = utterance_text[:TEXT_TRUNCATE_LENGTH]
    if len(utterance_text) > TEXT_TRUNCATE_LENGTH:
        truncated_text += "..."

    print(f"\n📝 UTTERANCE TEXT:")
    print(f"   {truncated_text}")

    # Show extracted events
    print(f"\n🎯 EXTRACTED EVENTS ({len(events)}):")
    if parsed_ok and events:
        for idx, event in enumerate(events, 1):
            print(f"   [{idx}] Who: {event.get('who', 'N/A')}")
            print(f"       What: {event.get('what', 'N/A')}")
            print(f"       Where: {event.get('where', 'N/A')}")
            print(f"       When: {event.get('when', 'N/A')}")
            print(f"       Emotion: {event.get('emotion', 'N/A')}")
    elif not parsed_ok:
        print("   ⚠️  JSON parsing failed - raw response saved to database")
    else:
        print("   (No events extracted)")

    # Show processing stats
    print(f"\n📊 PROGRESS:")
    print(f"   Processed: {stats['total_processed']:,} | Events: {stats['total_events']:,}")
    print(f"   Cost: ${stats['total_cost_usd']:.4f} | Avg response: {stats['avg_response_time_ms']:.0f}ms")
    print(f"   Parse success rate: {stats['parse_success_rate']*100:.1f}%")

    print("\n⏳ Auto-continuing in 10 seconds...")
    print("   Press ANY KEY to pause and choose action")
    print("=" * 80)


def handle_user_interrupt() -> str:
    """Handle user interrupt and get action choice."""
    print("\n" + "=" * 80)
    print("⏸️  PAUSED")
    print("=" * 80)
    print("\nChoose action:")
    print("  [c] Continue processing")
    print("  [s] Skip this utterance")
    print("  [q] Quit and save progress")
    print()

    while True:
        choice = input("Your choice (c/s/q): ").strip().lower()
        if choice in ['c', 's', 'q']:
            return choice
        print("Invalid choice. Please enter c, s, or q.")


# ============================================================================
# OpenAI Event Extractor (Worker Function)
# ============================================================================

# Global client instance (created once per worker process)
_worker_client = None

def _init_worker():
    """Initialize worker process with reusable OpenAI client."""
    global _worker_client
    _worker_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

def extract_events_worker(utterances_batch: List[Dict[str, Any]], shared_monitor: Dict,
                         shared_stats: Dict, db_path: str) -> List[Dict[str, Any]]:
    """
    Worker function to extract events from a BATCH of utterances.
    Sends 5 utterances per API call for efficiency.
    This runs in a separate process.
    """
    global _worker_client
    client = _worker_client

    # Build batched prompt with all utterances
    user_message_parts = []
    for idx, utterance in enumerate(utterances_batch, 1):
        user_message_parts.append(f"UTTERANCE_{idx} (ID: {utterance['utterance_id']}):\n{utterance['text']}\n")

    user_message = "\n".join(user_message_parts)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message}
    ]

    # Call OpenAI API (one call for all utterances in batch)
    start_time = time.time()
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.3
        )

        response_time_ms = int((time.time() - start_time) * 1000)

        # Extract response data
        raw_response = response.choices[0].message.content
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens

        # Calculate cost (total for batch)
        input_cost = (input_tokens / 1_000_000) * INPUT_COST_PER_1M
        output_cost = (output_tokens / 1_000_000) * OUTPUT_COST_PER_1M
        total_cost_usd = input_cost + output_cost

        # Distribute cost evenly across utterances
        cost_per_utterance = total_cost_usd / len(utterances_batch)

        # Try to parse JSON and extract events for each utterance
        results = []
        try:
            data = json.loads(raw_response)

            # Process each utterance in the batch
            for idx, utterance in enumerate(utterances_batch, 1):
                utterance_key = f"UTTERANCE_{idx}"
                utterance_data = data.get(utterance_key, {"events": []})

                # Handle case where OpenAI returns wrong format (list instead of dict)
                if isinstance(utterance_data, list):
                    # OpenAI returned events as a list directly instead of {"events": [...]}
                    events = utterance_data
                elif isinstance(utterance_data, dict):
                    events = utterance_data.get("events", [])
                else:
                    # Unknown format - skip
                    events = []

                results.append({
                    'utterance_hash': utterance['utterance_hash'],
                    'utterance_id': utterance['utterance_id'],
                    'interview_id': utterance['interview_id'],
                    'text': utterance['text'],
                    'events': events,
                    'event_count': len(events),
                    'input_tokens': input_tokens // len(utterances_batch),  # Approximate split
                    'output_tokens': output_tokens // len(utterances_batch),  # Approximate split
                    'cost_usd': cost_per_utterance,
                    'response_time_ms': response_time_ms,
                    'raw_response': json.dumps(utterance_data),  # Store just this utterance's portion
                    'parsed_successfully': True,
                    'success': True
                })

        except json.JSONDecodeError:
            # If parsing fails, create error results for all utterances in batch
            logger.warning(f"JSON parsing failed for batch - saving raw response")
            for utterance in utterances_batch:
                results.append({
                    'utterance_hash': utterance['utterance_hash'],
                    'utterance_id': utterance['utterance_id'],
                    'interview_id': utterance['interview_id'],
                    'text': utterance['text'],
                    'events': [],
                    'event_count': 0,
                    'input_tokens': input_tokens // len(utterances_batch),
                    'output_tokens': output_tokens // len(utterances_batch),
                    'cost_usd': cost_per_utterance,
                    'response_time_ms': response_time_ms,
                    'raw_response': raw_response,  # Store full raw response
                    'parsed_successfully': False,
                    'success': True
                })

        return results

    except Exception as e:
        logger.error(f"Error processing batch: {str(e)}")
        # Return error for all utterances in batch
        return [{
            'utterance_hash': utt['utterance_hash'],
            'utterance_id': utt['utterance_id'],
            'success': False,
            'error': str(e)
        } for utt in utterances_batch]


# ============================================================================
# Main Processing Logic
# ============================================================================

def main(args):
    """Main extraction pipeline with user interaction."""
    start_time = time.time()

    # Initialize components
    checkpoint_db = CheckpointDB(args.checkpoint_db)
    response_monitor = ResponseTimeMonitor()

    logger.info("=" * 80)
    logger.info("EVENT EXTRACTION V6 - Interactive OpenAI")
    logger.info("=" * 80)
    logger.info(f"Model: {MODEL_NAME}")
    logger.info(f"Workers: {NUM_WORKERS}")
    logger.info(f"Budget limit: ${args.budget:.2f}")
    logger.info(f"Validation timeout: {VALIDATION_TIMEOUT}s")
    logger.info("=" * 80)

    # Load data
    logger.info("Loading utterances...")
    df = pd.read_parquet(args.input)

    # Filter out short utterances
    df = df[df['word_count'] >= MIN_WORD_COUNT].copy()

    # Add utterance_id and hash
    df['utterance_id'] = df['interview_id'].astype(str) + '_' + df.index.astype(str)
    df['utterance_hash'] = df.apply(
        lambda row: hashlib.md5(f"{row['interview_id']}_{row['text']}".encode()).hexdigest(),
        axis=1
    )

    if args.sample:
        df = df.head(args.sample)

    logger.info(f"Loaded {len(df):,} utterances")

    # OPTIMIZED: Filter out already processed (fast set lookup instead of DB queries)
    logger.info("Checking already processed utterances...")
    processed_hashes = checkpoint_db.get_processed_hashes()
    logger.info(f"Found {len(processed_hashes):,} already processed")
    df_remaining = df[~df['utterance_hash'].isin(processed_hashes)].copy()
    logger.info(f"Remaining to process: {len(df_remaining):,}")

    if len(df_remaining) == 0:
        logger.info("✅ All utterances already processed!")
        return

    # Process utterances in batched API calls
    # Each worker gets UTTERANCES_PER_API_CALL utterances
    # We submit BATCH_SIZE jobs to NUM_WORKERS in parallel
    total_processed = 0
    user_quit = False

    # Create worker pool with initializer for reusable OpenAI clients
    with Pool(processes=NUM_WORKERS, initializer=_init_worker) as pool:
        # Convert to list for batch processing
        utterances_list = [row.to_dict() for idx, row in df_remaining.iterrows()]

        # Group utterances into mini-batches for API calls
        # Each mini-batch contains UTTERANCES_PER_API_CALL utterances
        api_call_batches = []
        for i in range(0, len(utterances_list), UTTERANCES_PER_API_CALL):
            api_call_batches.append(utterances_list[i:i + UTTERANCES_PER_API_CALL])

        # Process BATCH_SIZE api_call_batches at a time in parallel
        for batch_start in range(0, len(api_call_batches), BATCH_SIZE):
            if user_quit:
                break

            batch_end = min(batch_start + BATCH_SIZE, len(api_call_batches))
            parallel_batches = api_call_batches[batch_start:batch_end]

            # Submit all batches in parallel (each worker processes one batch of 5 utterances)
            async_results = []
            for utterances_batch in parallel_batches:
                result = pool.apply_async(extract_events_worker,
                                         (utterances_batch, {}, {}, args.checkpoint_db))
                async_results.append((utterances_batch, result))

            # Collect results from all parallel batches
            batch_records = []
            for utterances_batch, result in async_results:
                results_list = result.get()  # Returns list of results (one per utterance)

                # Process each result in the batch
                for result_data in results_list:
                    if not result_data['success']:
                        logger.error(f"Failed to process {result_data['utterance_id']}")
                        continue

                    # Add response time to monitor
                    response_monitor.add_response_time(result_data['response_time_ms'])

                    # Prepare record for bulk insert
                    batch_records.append((
                        result_data['utterance_hash'],
                        result_data['utterance_id'],
                        result_data['interview_id'],
                        result_data['event_count'],
                        result_data['input_tokens'],
                        result_data['output_tokens'],
                        result_data['cost_usd'],
                        result_data['response_time_ms'],
                        result_data['raw_response'],
                        1 if result_data['parsed_successfully'] else 0,
                        0  # user_validated
                    ))

                    total_processed += 1

            # OPTIMIZED: Bulk database write (10x faster than individual writes)
            if batch_records:
                checkpoint_db.mark_processed_bulk(batch_records)

            # OPTIMIZED: Only query stats every 5 batches (reduces DB load)
            batch_num = batch_start // BATCH_SIZE
            if batch_num % 5 == 0:
                stats = checkpoint_db.get_stats()
                logger.info(f"Batch {batch_num} | Progress: {stats['total_processed']:,} | Events: {stats['total_events']:,} | Cost: ${stats['total_cost_usd']:.4f} | Parse: {stats['parse_success_rate']*100:.1f}%")

            # Check if we should pause for rate limiting
            if response_monitor.should_pause():
                logger.warning(f"⚠️  API slowdown detected - pausing for {PAUSE_DURATION}s...")
                time.sleep(PAUSE_DURATION)
                response_monitor.baseline_time = None  # Reset baseline after pause

            # Budget check (get stats if not already retrieved)
            if batch_num % 5 != 0:
                stats = checkpoint_db.get_stats()
            if stats['total_cost_usd'] >= args.budget:
                logger.warning(f"💰 Budget limit reached: ${stats['total_cost_usd']:.2f}")
                break

    # Final stats
    final_stats = checkpoint_db.get_stats()
    elapsed_time = time.time() - start_time

    logger.info("\n" + "=" * 80)
    logger.info("EXTRACTION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"⏱️  Time elapsed: {elapsed_time/60:.1f} minutes")
    logger.info(f"📊 Utterances processed: {final_stats['total_processed']:,}")
    logger.info(f"🎯 Events extracted: {final_stats['total_events']:,}")
    logger.info(f"💰 Total cost: ${final_stats['total_cost_usd']:.4f}")
    logger.info(f"⚡ Avg response time: {final_stats['avg_response_time_ms']:.0f}ms")
    logger.info(f"✅ Parse success rate: {final_stats['parse_success_rate']*100:.1f}%")
    logger.info("=" * 80)

    checkpoint_db.close()


# ============================================================================
# CLI Entry Point
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Event Extractor V6 - Interactive OpenAI")

    parser.add_argument("--input", default="data/processed/utterances_v2.parquet",
                       help="Input parquet file")
    parser.add_argument("--checkpoint-db", default="data/processed/.checkpoints/event_extraction_v6.db",
                       help="Checkpoint database path")
    parser.add_argument("--sample", type=int, default=None,
                       help="Process only N utterances (for testing)")
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET_LIMIT,
                       help="Budget limit in USD")

    args = parser.parse_args()

    main(args)
