#!/usr/bin/env python3
"""
OpenTelemetry Java Instrumentation Metadata Tracker

This script tracks the evolution of instrumentation library metrics
from the OpenTelemetry Java instrumentation repository over time.
"""
import os

import requests
import yaml
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class GitHubAPIClient:
    def __init__(self, token: Optional[str] = None):
        self.base_url = "https://api.github.com"
        self.headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'OTel-Metadata-Tracker/1.0'
        }
        if token:
            self.headers['Authorization'] = f'Bearer {token}'

    def get_file_content(self, repo: str, file_path: str) -> Optional[str]:
        url = f"{self.base_url}/repos/{repo}/contents/{file_path}"

        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()

            file_data = response.json()
            if file_data.get('encoding') == 'base64':
                import base64
                content = base64.b64decode(file_data['content']).decode('utf-8')
                return content

            return None

        except requests.exceptions.RequestException as e:
            print(f"Error fetching file content: {e}")
            return None


class InstrumentationMetricsParser:
    """Parser for OpenTelemetry instrumentation YAML files"""

    total_libraries = 0
    libraries_with_description = 0
    libraries_with_javaagent = 0
    libraries_with_library_version = 0
    libraries_with_telemetry = 0

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

            if library.get('telemetry'):
                self.libraries_with_telemetry += 1

    def extract_metrics(self, data: Dict) -> Dict[str, int]:
        for category_name, category_items in data['libraries'].items():
            self.update_metrics(category_items)

        self.update_metrics(data["internal"])
        self.update_metrics(data["custom"])


def generate_date_range(start_date: datetime, end_date: datetime) -> List[datetime]:
    """Generate a list of dates from start_date to end_date (inclusive)"""
    dates = []
    current_date = start_date

    while current_date <= end_date:
        dates.append(current_date)
        current_date += timedelta(days=1)

    return dates


def main():
    repo = "open-telemetry/opentelemetry-java-instrumentation"
    file_path = "docs/instrumentation-list.yaml"
    end_date = datetime.now()

    github_client = GitHubAPIClient(token=os.environ.get("GITHUB_TOKEN"))
    parser = InstrumentationMetricsParser()

    print(
        f"Tracking OpenTelemetry Java Instrumentation metrics")
    print(f"Repository: {repo}")
    print(f"File: {file_path}")
    print("-" * 80)

    file_content = github_client.get_file_content(repo, file_path)
    if not file_content:
        print(f"  File not found")
        return

    yaml_data = parser.parse_yaml_content(file_content)
    if not yaml_data:
        print(f"  Failed to parse YAML")
        return

    parser.extract_metrics(yaml_data)

    print(f" Total Libraries: {parser.total_libraries}")
    print(f" Libraries with Description: {parser.libraries_with_description}")
    print(f" Libraries with javaagent: {parser.libraries_with_javaagent}")
    print(f" Libraries with library: {parser.libraries_with_javaagent}")
    print(f" Libraries with telemetry: {parser.libraries_with_library_version}")
    print(f" Total Libraries: {parser.libraries_with_telemetry}")



if __name__ == "__main__":
    main()
