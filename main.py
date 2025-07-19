import os
import time
import yaml
from typing import Dict, List, Optional

from github import Github

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource

resource = Resource.create({"service.name": "github-metrics"})
exporter = OTLPMetricExporter()
reader = PeriodicExportingMetricReader(exporter, export_interval_millis=1000)
provider = MeterProvider(resource=resource, metric_readers=[reader])
metrics.set_meter_provider(provider)

meter = metrics.get_meter("github.metrics.meter")


def fetch_github_metrics(github_client: Github):
    """
    Fetches GitHub repository metrics (issues, PRs, stars)
    """
    print("Fetching GitHub repository metrics...")

    repos = [
        "open-telemetry/opentelemetry-java-instrumentation",
        "open-telemetry/opentelemetry-java",
        "open-telemetry/opentelemetry-java-contrib",
        "open-telemetry/opentelemetry-java-examples"
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


if __name__ == "__main__":
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        raise ValueError("GITHUB_TOKEN environment variable not set.")
    g = Github(github_token)

    fetch_github_metrics(g)
    fetch_instrumentation_metrics(g)
    print("All metrics collected. The script will exit after 5 seconds.")
    time.sleep(5)
