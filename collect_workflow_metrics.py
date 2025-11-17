"""
Collects workflow run duration metrics from GitHub.

This script tracks workflow run durations using deduplication to prevent
double-counting when using overlapping lookback windows. This allows catching
builds that take longer than the collection interval to complete.
"""

import os
import time
from datetime import datetime, timedelta
from github import Github, Auth

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider, Histogram
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, AggregationTemporality
from opentelemetry.sdk.metrics.view import View
from opentelemetry.sdk.metrics._internal.aggregation import ExplicitBucketHistogramAggregation
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource

from workflow_state import load_processed_runs, save_processed_runs, get_state_file_path


# OpenTelemetry setup
resource = Resource.create({"service.name": "github-workflow-metrics"})

workflow_duration_view = View(
    instrument_name="workflow.run.duration",
    aggregation=ExplicitBucketHistogramAggregation(
        boundaries=(5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 75, 90, 120, 180)
    )
)

job_duration_view = View(
    instrument_name="workflow.job.duration",
    aggregation=ExplicitBucketHistogramAggregation(
        boundaries=(1, 2, 3, 5, 7, 10, 15, 20, 25, 30, 40, 50, 60, 90, 120)
    )
)

# OTLP exporter with cumulative temporality for Prometheus/Mimir in Grafana
otlp_exporter = OTLPMetricExporter(
    preferred_temporality={
        Histogram: AggregationTemporality.CUMULATIVE,
    }
)
otlp_reader = PeriodicExportingMetricReader(otlp_exporter, export_interval_millis=5000)

provider = MeterProvider(
    resource=resource,
    metric_readers=[otlp_reader],
    views=[workflow_duration_view, job_duration_view]
)
metrics.set_meter_provider(provider)

meter = metrics.get_meter("github.workflow.metrics.meter")

workflow_duration_histogram = meter.create_histogram(
    name="workflow.run.duration",
    description="Duration of workflow runs in minutes",
    unit="minutes"
)

job_duration_histogram = meter.create_histogram(
    name="workflow.job.duration",
    description="Duration of individual workflow jobs in minutes",
    unit="minutes"
)


def fetch_job_metrics(run, base_attributes: dict):
    """
    Fetches and records metrics for individual jobs within a workflow run.

    Args:
        run: WorkflowRun object from GitHub API
        base_attributes: Base attributes to include with each job metric (repo, workflow, event, etc.)
    """
    try:
        jobs = run.jobs()
        jobs_recorded = 0

        for job in jobs:
            # Skip jobs that haven't completed
            if job.status != "completed":
                continue

            # Calculate job duration
            if job.started_at and job.completed_at:
                duration_seconds = (job.completed_at - job.started_at).total_seconds()
                duration_minutes = duration_seconds / 60

                # Create attributes for this job
                job_attributes = base_attributes.copy()
                job_attributes["job_name"] = job.name
                job_attributes["job_conclusion"] = job.conclusion or "unknown"

                # Record the metric
                job_duration_histogram.record(duration_minutes, job_attributes)
                jobs_recorded += 1

        return jobs_recorded

    except Exception as e:
        print(f"    Warning: Could not fetch jobs for run {run.id}: {e}")
        return 0


def fetch_workflow_run_metrics(github_client: Github, lookback_hours: int = 3):
    """
    Fetches workflow run duration metrics for main branch builds and PR builds.
    Uses deduplication to avoid counting the same run multiple times.

    Args:
        github_client: Authenticated GitHub client
        lookback_hours: Number of hours to look back for workflow runs
    """
    print(f"Fetching workflow run metrics (last {lookback_hours} hours)...")

    # Load previously processed runs
    state_file = get_state_file_path()
    processed_runs = load_processed_runs(state_file)
    repo_name = "open-telemetry/opentelemetry-java-instrumentation"

    try:
        repo = github_client.get_repo(repo_name)

        since_date = datetime.now() - timedelta(hours=lookback_hours)
        date_filter = since_date.strftime("%Y-%m-%dT%H:%M:%S")

        # Find both "Build" and "Build pull request" workflows
        workflows = repo.get_workflows()
        build_workflows = []
        for wf in workflows:
            if wf.name == "Build" or "build.yml" in wf.path:
                build_workflows.append(wf)
                print(f"  Found workflow: {wf.name} ({wf.path})")
            elif wf.name == "Build pull request" or "build-pull-request.yml" in wf.path:
                build_workflows.append(wf)
                print(f"  Found workflow: {wf.name} ({wf.path})")

        if not build_workflows:
            print("  Warning: No build workflows found")
            return

        runs_processed = 0
        runs_total = 0
        runs_incomplete = 0
        runs_skipped_branch = 0
        runs_skipped_duplicate = 0
        runs_skipped_cancelled = 0
        jobs_recorded = 0
        newly_processed = set()

        for build_workflow in build_workflows:
            print(f"  Processing workflow: {build_workflow.name}")

            # Get workflow runs (both push and pull_request events)
            runs = build_workflow.get_runs(
                created=f">={date_filter}"
            )

            for run in runs:
                runs_total += 1

                if run.id in processed_runs:
                    runs_skipped_duplicate += 1
                    continue

                # Track main branch builds (push events) and all PR builds (pull_request events)
                is_test_pr = False

                if run.event == "pull_request":
                    # Track all PR builds, but mark PR #15213 specially
                    try:
                        if hasattr(run, 'pull_requests') and len(run.pull_requests) > 0:
                            pr_number = run.pull_requests[0].number
                            if pr_number == 15213:
                                is_test_pr = True
                    except Exception:
                        pass
                elif run.event == "push" and run.head_branch == "main":
                    # Main branch builds
                    pass
                else:
                    # Skip all other events/branches (e.g., release branches, scheduled runs)
                    runs_skipped_branch += 1
                    continue

                # Only process completed runs
                if run.status != "completed":
                    runs_incomplete += 1
                    continue

                # Skip cancelled runs - they didn't complete the full build
                if run.conclusion == "cancelled":
                    runs_skipped_cancelled += 1
                    continue

                try:
                    timing_data = run.timing()

                    if not timing_data:
                        continue

                    if not hasattr(timing_data, 'run_duration_ms'):
                        continue

                    duration_ms = timing_data.run_duration_ms
                    duration_minutes = duration_ms / 1000 / 60

                    attributes = {
                        "repo": "opentelemetry-java-instrumentation",
                        "workflow": "build",
                        "conclusion": run.conclusion or "unknown",
                        "event": run.event,
                        "is_build_test": "true" if is_test_pr else "false"
                    }

                    workflow_duration_histogram.record(duration_minutes, attributes)

                    if runs_processed == 0:
                        print(f"  Debug: Recording histogram value {duration_minutes} minutes with attributes {attributes}")

                    # Fetch and record job-level metrics
                    jobs_count = fetch_job_metrics(run, attributes)
                    jobs_recorded += jobs_count

                    # Mark this run as processed
                    newly_processed.add(run.id)
                    runs_processed += 1

                    if runs_processed <= 5:  # Print first 5 for debugging
                        print(f"  - Run #{run.run_number} (event={run.event}): {duration_minutes:.1f} minutes, conclusion={run.conclusion}")

                except Exception as e:
                    print(f"  Warning: Could not fetch timing for run {run.id}: {e}")
                    continue

        print(f"  Total runs found: {runs_total}")
        print(f"  Duplicate runs skipped: {runs_skipped_duplicate}")
        print(f"  Non-main branch runs skipped: {runs_skipped_branch}")
        print(f"  Incomplete runs skipped: {runs_incomplete}")
        print(f"  Cancelled runs skipped: {runs_skipped_cancelled}")
        print(f"  Processed {runs_processed} new workflow runs")
        print(f"  Recorded {jobs_recorded} job-level metrics")

        # Update and save state
        all_processed = processed_runs.union(newly_processed)
        save_processed_runs(all_processed, state_file)

    except Exception as e:
        print(f"Error fetching workflow run metrics for {repo_name}: {e}")


if __name__ == "__main__":
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        raise ValueError("GITHUB_TOKEN environment variable not set.")

    auth = Auth.Token(github_token)
    g = Github(auth=auth)

    # Get lookback period for workflow metrics (default 3 hours)
    workflow_lookback_hours = int(os.environ.get("WORKFLOW_LOOKBACK_HOURS", "3"))

    print("=" * 60)
    print("GitHub Workflow Metrics Collection")
    print("=" * 60)

    fetch_workflow_run_metrics(g, lookback_hours=workflow_lookback_hours)

    print("\nAll workflow metrics collected. Flushing metrics before exit...")
    provider.force_flush()

    print("Metrics flushed. The script will exit after 5 seconds.")
    time.sleep(5)
