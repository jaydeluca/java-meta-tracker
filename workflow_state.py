"""
State management for workflow run deduplication.

Tracks which workflow runs have been processed to prevent double-counting
when using overlapping lookback windows.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Set


DEFAULT_STATE_FILE = "/app/state/processed_workflow_runs.json"
MAX_STORED_RUN_IDS = 2000  # Prevent unbounded growth


def load_processed_runs(state_file: str = DEFAULT_STATE_FILE) -> Set[int]:
    """
    Load previously processed workflow run IDs from state file.
    
    Args:
        state_file: Path to the JSON state file
        
    Returns:
        Set of workflow run IDs that have been processed
    """
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                data = json.load(f)
                run_ids = set(data.get('run_ids', []))
                last_updated = data.get('last_updated', 'unknown')
                print(f"  Loaded {len(run_ids)} previously processed runs (last updated: {last_updated})")
                return run_ids
        except (json.JSONDecodeError, IOError) as e:
            print(f"  Warning: Could not load state file: {e}")
            return set()
    
    print("  No previous state found, starting fresh")
    return set()


def save_processed_runs(processed_runs: Set[int], state_file: str = DEFAULT_STATE_FILE) -> None:
    """
    Save processed workflow run IDs to state file.
    
    Args:
        processed_runs: Set of workflow run IDs that have been processed
        state_file: Path to the JSON state file
    """
    try:
        Path(state_file).parent.mkdir(parents=True, exist_ok=True)
        
        # Keep only the most recent run IDs to prevent unbounded growth
        runs_to_save = sorted(processed_runs, reverse=True)[:MAX_STORED_RUN_IDS]
        
        data = {
            'run_ids': runs_to_save,
            'last_updated': datetime.now().isoformat(),
            'count': len(runs_to_save)
        }
        
        with open(state_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"  Saved {len(runs_to_save)} processed run IDs to state file")
        
        if len(processed_runs) > MAX_STORED_RUN_IDS:
            print(f"  Note: Trimmed to {MAX_STORED_RUN_IDS} most recent runs to prevent unbounded growth")
            
    except IOError as e:
        print(f"  Warning: Could not save state file: {e}")


def get_state_file_path() -> str:
    """
    Get the state file path from environment or use default.
    
    Returns:
        Path to the state file
    """
    return os.environ.get("WORKFLOW_STATE_FILE", DEFAULT_STATE_FILE)

