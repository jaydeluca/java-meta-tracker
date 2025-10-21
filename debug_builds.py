#!/usr/bin/env python3
"""
Debug script to analyze workflow run durations.
Useful for finding cancelled runs and understanding build duration patterns.
"""

import os
from datetime import datetime, timedelta
from github import Github, Auth


if __name__ == "__main__":
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        raise ValueError("GITHUB_TOKEN environment variable not set.")

    auth = Auth.Token(github_token)
    g = Github(auth=auth)

    repo = g.get_repo("open-telemetry/opentelemetry-java-instrumentation")

    # Find both Build workflows
    workflows = repo.get_workflows()
    build_workflows = []
    for wf in workflows:
        if wf.name == "Build" or "build.yml" in wf.path:
            build_workflows.append(wf)
            print(f"Found workflow: {wf.name} ({wf.path})")
        elif wf.name == "Build pull request" or "build-pull-request.yml" in wf.path:
            build_workflows.append(wf)
            print(f"Found workflow: {wf.name} ({wf.path})")

    # Look back 12 hours by default, or use environment variable
    lookback_hours = int(os.environ.get("DEBUG_LOOKBACK_HOURS", "12"))
    since = datetime.now() - timedelta(hours=lookback_hours)
    date_filter = since.strftime("%Y-%m-%dT%H:%M:%S")

    print("\n" + "="*100)
    print(f"Analyzing workflow runs from the last {lookback_hours} hours")
    print("="*100)

    all_runs = []

    for build_workflow in build_workflows:
        print(f"\nProcessing workflow: {build_workflow.name}")

        runs = build_workflow.get_runs(created=f">={date_filter}")

        for run in runs:
            # Filter to match collect_workflow_metrics.py logic
            if run.event == "pull_request":
                pass
            elif run.event == "push" and run.head_branch == "main":
                pass
            else:
                continue

            if run.status != "completed":
                continue

            try:
                timing = run.timing()
                if timing and hasattr(timing, 'run_duration_ms'):
                    duration_minutes = timing.run_duration_ms / 1000 / 60
                else:
                    duration_minutes = 0

                all_runs.append({
                    'run': run,
                    'duration': duration_minutes,
                    'workflow': build_workflow.name
                })
            except Exception as e:
                print(f"  Error getting timing for run {run.id}: {e}")
                continue

    # Sort by duration
    all_runs.sort(key=lambda x: x['duration'])

    print(f"\n{'='*100}")
    print(f"Total completed runs found: {len(all_runs)}")
    print(f"{'='*100}\n")

    # Show shortest runs first (likely cancelled or failed early)
    print("SHORTEST DURATION RUNS (First 20):")
    print("-" * 100)
    print(f"{'Run #':<10} {'Conclusion':<12} {'Duration':<12} {'Workflow':<25} {'Event':<15} {'Branch':<30}")
    print("-" * 100)

    for item in all_runs[:20]:
        run = item['run']
        duration = item['duration']
        workflow = item['workflow']

        # Color-code conclusion for readability
        conclusion_display = run.conclusion or "unknown"
        if run.conclusion == "cancelled":
            conclusion_display = f"🚫 {run.conclusion}"
        elif run.conclusion == "failure":
            conclusion_display = f"❌ {run.conclusion}"
        elif run.conclusion == "success":
            conclusion_display = f"✅ {run.conclusion}"

        print(f"{run.run_number:<10} {conclusion_display:<20} {duration:>6.1f} min   {workflow:<25} {run.event:<15} {run.head_branch[:28]:<30}")

    print(f"\n{'='*100}")
    print("DETAILED VIEW OF SHORT-DURATION RUNS:")
    print("-" * 100)

    for item in all_runs[:10]:
        run = item['run']
        duration = item['duration']
        workflow = item['workflow']

        print(f"\n📊 Run #{run.run_number} (ID: {run.id})")
        print(f"   Workflow:   {workflow}")
        print(f"   Conclusion: {run.conclusion} {'🚫 CANCELLED' if run.conclusion == 'cancelled' else '❌ FAILED' if run.conclusion == 'failure' else '✅ SUCCESS'}")
        print(f"   Duration:   {duration:.1f} minutes")
        print(f"   Status:     {run.status}")
        print(f"   Event:      {run.event}")
        print(f"   Branch:     {run.head_branch}")
        print(f"   Created:    {run.created_at}")
        print(f"   URL:        {run.html_url}")

    # Show statistics
    print(f"\n{'='*100}")
    print("DURATION STATISTICS BY CONCLUSION:")
    print("-" * 100)

    durations_by_conclusion = {}
    for item in all_runs:
        conclusion = item['run'].conclusion or "unknown"
        if conclusion not in durations_by_conclusion:
            durations_by_conclusion[conclusion] = []
        durations_by_conclusion[conclusion].append(item['duration'])

    for conclusion, durations in sorted(durations_by_conclusion.items()):
        avg = sum(durations) / len(durations)
        min_dur = min(durations)
        max_dur = max(durations)
        count = len(durations)

        icon = "🚫" if conclusion == "cancelled" else "❌" if conclusion == "failure" else "✅" if conclusion == "success" else "❓"
        print(f"{icon} {conclusion:<12} {count:>3} runs | avg: {avg:>6.1f} min | min: {min_dur:>6.1f} min | max: {max_dur:>6.1f} min")

    # Show runs that would be filtered
    print(f"\n{'='*100}")
    print("FILTERING SUMMARY:")
    print("-" * 100)

    cancelled_count = sum(1 for item in all_runs if item['run'].conclusion == "cancelled")
    would_process = len(all_runs) - cancelled_count

    print(f"Total runs found:              {len(all_runs)}")
    print(f"Cancelled runs (filtered):     {cancelled_count} 🚫")
    print(f"Runs that would be processed:  {would_process} ✅")

    if cancelled_count > 0:
        cancelled_durations = [item['duration'] for item in all_runs if item['run'].conclusion == "cancelled"]
        avg_cancelled = sum(cancelled_durations) / len(cancelled_durations)
        print(f"\nCancelled runs average duration: {avg_cancelled:.1f} minutes")
        print(f"These cancelled runs would have skewed your metrics!")

    print(f"\n{'='*100}")
