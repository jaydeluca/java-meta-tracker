import os
import time
import yaml
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from github import Github

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider, Counter, Histogram
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, AggregationTemporality
from opentelemetry.sdk.metrics.view import View
from opentelemetry.sdk.metrics._internal.aggregation import ExplicitBucketHistogramAggregation
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource

resource = Resource.create({"service.name": "github-metrics"})

workflow_duration_view = View(
    instrument_name="workflow_run_duration_minutes",
    aggregation=ExplicitBucketHistogramAggregation(
        boundaries=(5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 75, 90, 120, 180)
    )
)

# OTLP exporter with cumulative temporality is required for Prometheus/Mimir in Grafana
otlp_exporter = OTLPMetricExporter(
    preferred_temporality={
        Histogram: AggregationTemporality.CUMULATIVE,
        Counter: AggregationTemporality.CUMULATIVE,
    }
)
otlp_reader = PeriodicExportingMetricReader(otlp_exporter, export_interval_millis=5000)

provider = MeterProvider(
    resource=resource,
    metric_readers=[otlp_reader],
    views=[workflow_duration_view]
)
metrics.set_meter_provider(provider)

meter = metrics.get_meter("github.metrics.meter")

workflow_duration_histogram = meter.create_histogram(
    name="workflow_run_duration_minutes",
    description="Duration of workflow runs in minutes",
    unit="minutes"
)


def fetch_github_metrics(github_client: Github):
    """
    Fetches GitHub repository metrics (issues, PRs, stars)
    """
    print("Fetching GitHub repository metrics...")

    repos = [
        "open-telemetry/opentelemetry-java-instrumentation",
        "open-telemetry/opentelemetry-java",
        "open-telemetry/opentelemetry-java-contrib",
        "open-telemetry/opentelemetry-java-examples",
        "prometheus/client_java"
    ]

    for repo_name in repos:
        try:
            repo = github_client.get_repo(repo_name)
            open_pulls_count = repo.get_pulls(state='open').totalCount
            # The number of open issues includes PRs, so we subtract them.
            open_issues_count = repo.open_issues_count - open_pulls_count

            print(
                f"  - {repo_name}: Issues={open_issues_count}, PRs={open_pulls_count}, Stars={repo.stargazers_count}")

            repo_tag = repo_name.replace("open-telemetry/", "")

            meter.create_gauge("repo.issues.open").set(open_issues_count,
                                                       {"repo": repo_tag})
            meter.create_gauge("repo.prs.open").set(open_pulls_count,
                                                    {"repo": repo_tag})
            meter.create_gauge("repo.stars.count").set(repo.stargazers_count,
                                                       {"repo": repo_tag})

        except Exception as e:
            print(f"Error fetching data for {repo_name}: {e}")


class GitHubAPIClient:
    def __init__(self, github_client: Github):
        self.github_client = github_client

    def get_file_content(self, repo_name: str, file_path: str) -> Optional[str]:
        try:
            repo = self.github_client.get_repo(repo_name)
            contents = repo.get_contents(file_path)
            if contents.type == "file":
                return contents.decoded_content.decode('utf-8')
            return None
        except Exception as e:
            print(f"Error fetching file content from {repo_name}/{file_path}: {e}")
            return None


class InstrumentationMetricsParser:
    """Parser for OpenTelemetry instrumentation YAML files and metric extraction."""

    def __init__(self):
        self.total_libraries = 0
        self.libraries_with_description = 0
        self.libraries_with_javaagent = 0
        self.libraries_with_library_version = 0
        self.libraries_with_telemetry = 0

    @staticmethod
    def parse_yaml_content(content: str) -> Dict:
        try:
            return yaml.safe_load(content)
        except yaml.YAMLError as e:
            print(f"Error parsing YAML: {e}")
            return {}

    def update_metrics(self, items: List[Dict]):
        for library in items:
            self.total_libraries += 1

            if library.get('description'):
                self.libraries_with_description += 1

            target_versions = library.get('target_versions', {})
            if target_versions.get('javaagent'):
                self.libraries_with_javaagent += 1
            if target_versions.get('library'):
                self.libraries_with_library_version += 1

            telemetry_value = library.get('telemetry')
            if telemetry_value is not None and telemetry_value is not False:
                self.libraries_with_telemetry += 1

    def extract_metrics(self, data: Dict):
        self.__init__()

        for category_name, category_items in data.get('libraries', {}).items():
            if isinstance(category_items, list):
                self.update_metrics(category_items)

        if 'internal' in data and isinstance(data['internal'], list):
            self.update_metrics(data['internal'])
        if 'custom' in data and isinstance(data['custom'], list):
            self.update_metrics(data['custom'])


def fetch_instrumentation_metrics(g: Github):
    """
    Fetches instrumentation metadata, parses it, and sends metrics.
    """
    print("Fetching instrumentation metadata metrics...")
    repo = "open-telemetry/opentelemetry-java-instrumentation"
    file_path = "docs/instrumentation-list.yaml"

    github_client = GitHubAPIClient(github_client=g)
    parser = InstrumentationMetricsParser()

    file_content = github_client.get_file_content(repo, file_path)
    if not file_content:
        print(f"  Failed to fetch {file_path}")
        return

    yaml_data = parser.parse_yaml_content(file_content)
    if not yaml_data:
        print(f"  Failed to parse YAML from {file_path}")
        return

    parser.extract_metrics(yaml_data)

    meter.create_gauge("instrumentation.libraries.total").set(parser.total_libraries)
    meter.create_gauge("instrumentation.libraries.with_description").set(
        parser.libraries_with_description)
    meter.create_gauge("instrumentation.libraries.with_javaagent_target_version").set(
        parser.libraries_with_javaagent)
    meter.create_gauge("instrumentation.libraries.with_library_target_version").set(
        parser.libraries_with_library_version)
    meter.create_gauge("instrumentation.libraries.with_telemetry").set(
        parser.libraries_with_telemetry)

    print(f"  Instrumentation Metrics:")
    print(f"    Total Libraries: {parser.total_libraries}")
    print(f"    Libraries with Description: {parser.libraries_with_description}")
    print(f"    Libraries with javaagent: {parser.libraries_with_javaagent}")
    print(f"    Libraries with library: {parser.libraries_with_library_version}")
    print(f"    Libraries with telemetry: {parser.libraries_with_telemetry}")


def fetch_workflow_run_metrics(github_client: Github, lookback_hours: int = 2):
    """
    Fetches workflow run duration metrics for main branch builds.

    Args:
        github_client: Authenticated GitHub client
        lookback_hours: Number of hours to look back for workflow runs (default 2, use larger values for backfill)
    """
    print(f"Fetching workflow run metrics (last {lookback_hours} hours)...")
    repo_name = "open-telemetry/opentelemetry-java-instrumentation"

    try:
        repo = github_client.get_repo(repo_name)

        # Calculate date filter
        since_date = datetime.now() - timedelta(hours=lookback_hours)
        date_filter = since_date.strftime("%Y-%m-%dT%H:%M:%S")

        # Find the "Build" workflow
        workflows = repo.get_workflows()
        build_workflow = None
        for wf in workflows:
            if wf.name == "Build" or "build.yml" in wf.path:
                build_workflow = wf
                print(f"  Found workflow: {wf.name} ({wf.path})")
                break

        if not build_workflow:
            print("  Warning: Build workflow not found")
            return

        # Get workflow runs (both push and pull_request events)
        runs = build_workflow.get_runs(
            created=f">={date_filter}"
        )

        runs_processed = 0
        runs_total = 0
        runs_incomplete = 0
        runs_skipped_branch = 0
        for run in runs:
            runs_total += 1

            # Track main branch builds (push events) and PR #14748 builds (pull_request events)
            is_pr_14748 = False
            if run.event == "pull_request":
                # Check if this is PR #14748
                try:
                    # Get the PR number from the run
                    if hasattr(run, 'pull_requests') and len(run.pull_requests) > 0:
                        pr_number = run.pull_requests[0].number
                        if pr_number == 14748:
                            is_pr_14748 = True
                        else:
                            # Skip other PR builds
                            runs_skipped_branch += 1
                            continue
                    else:
                        # Skip PR builds without PR number
                        runs_skipped_branch += 1
                        continue
                except Exception:
                    runs_skipped_branch += 1
                    continue
            elif run.event == "push" and run.head_branch == "main":
                # Main branch builds
                pass
            else:
                # Skip all other events/branches
                runs_skipped_branch += 1
                continue

            # Only process completed runs
            if run.status != "completed":
                runs_incomplete += 1
                continue

            try:
                # Get timing data
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
                    "is_build_test": "true" if is_pr_14748 else "false"
                }

                workflow_duration_histogram.record(duration_minutes, attributes)

                if runs_processed == 0:
                    print(f"  Debug: Recording histogram value {duration_minutes} minutes with attributes {attributes}")

                runs_processed += 1

                if runs_processed <= 5:  # Print first 5 for debugging
                    print(f"  - Run #{run.run_number} (event={run.event}): {duration_minutes:.1f} minutes, conclusion={run.conclusion}")

            except Exception as e:
                print(f"  Warning: Could not fetch timing for run {run.id}: {e}")
                continue

        print(f"  Total runs found: {runs_total}")
        print(f"  Non-main branch runs skipped: {runs_skipped_branch}")
        print(f"  Incomplete runs skipped: {runs_incomplete}")
        print(f"  Processed {runs_processed} main branch workflow runs")

    except Exception as e:
        print(f"Error fetching workflow run metrics for {repo_name}: {e}")


if __name__ == "__main__":
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        raise ValueError("GITHUB_TOKEN environment variable not set.")
    g = Github(github_token)

    # Get lookback period for workflow metrics (default 2 hours, set higher for backfill)
    workflow_lookback_hours = int(os.environ.get("WORKFLOW_LOOKBACK_HOURS", "2"))

    fetch_github_metrics(g)
    fetch_instrumentation_metrics(g)
    fetch_workflow_run_metrics(g, lookback_hours=workflow_lookback_hours)
    print("All metrics collected. Flushing metrics before exit...")

    provider.force_flush()

    print("Metrics flushed. The script will exit after 5 seconds.")
    time.sleep(5)
