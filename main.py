
import os
import time
from github import Github

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource

github_data = []

resource = Resource.create({"service.name": "github-metrics"})
exporter = OTLPMetricExporter()
reader = PeriodicExportingMetricReader(exporter, export_interval_millis=1000)
provider = MeterProvider(resource=resource, metric_readers=[reader])
metrics.set_meter_provider(provider)

meter = metrics.get_meter("github.metrics.meter")


def fetch_github_metrics():
    """
    Fetches metrics and stores them in the global github_data list.
    """
    print("Fetching GitHub metrics...")
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        raise ValueError("GITHUB_TOKEN environment variable not set.")

    g = Github(github_token)

    repos = [
        "open-telemetry/opentelemetry-java-instrumentation",
        "open-telemetry/opentelemetry-java"
    ]

    for repo_name in repos:
        try:
            repo = g.get_repo(repo_name)
            open_pulls_count = repo.get_pulls(state='open').totalCount
            # The number of open issues includes PRs, so we subtract them.
            open_issues_count = repo.open_issues_count - open_pulls_count

            print(f"  - {repo_name}: Issues={open_issues_count}, PRs={open_pulls_count}")

            repo_tag = repo_name.replace("open-telemetry/", "")

            meter.create_gauge("repo.issues.open").set(open_issues_count, {"repo": repo_tag})
            meter.create_gauge("repo.prs.open").set(open_pulls_count, {"repo": repo_tag})

        except Exception as e:
            print(f"Error fetching data for {repo_name}: {e}")


if __name__ == "__main__":
    fetch_github_metrics()
    print("The script will exit after 5 seconds.")
    time.sleep(5)
