import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider, Counter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, AggregationTemporality
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource

resource = Resource.create({"service.name": "benchmark-overhead-metrics"})

# OTLP exporter with cumulative temporality for Prometheus/Mimir compatibility
otlp_exporter = OTLPMetricExporter(
    preferred_temporality={
        Counter: AggregationTemporality.CUMULATIVE,
    }
)
otlp_reader = PeriodicExportingMetricReader(otlp_exporter, export_interval_millis=5000)

provider = MeterProvider(
    resource=resource,
    metric_readers=[otlp_reader]
)
metrics.set_meter_provider(provider)

meter = metrics.get_meter("benchmark.overhead.metrics.meter")


class BenchmarkReportParser:
    """Parser for OpenTelemetry Java benchmark summary.txt files."""

    @staticmethod
    def split_by_multiple_spaces(text: str) -> List[str]:
        """Split text by multiple consecutive spaces (2 or more)."""
        return [s.strip() for s in re.split(r'\s{2,}', text.strip()) if s.strip()]

    @staticmethod
    def normalize_metric_name(name: str) -> str:
        """
        Normalize metric names to a consistent format.
        Example: "Startup time (ms)" -> "startup_time_ms"
        """
        # Replace special characters and spaces with underscores
        normalized = re.sub(r'[^\w\s]', '', name.lower())
        normalized = re.sub(r'\s+', '_', normalized)
        # Remove trailing underscores
        return normalized.strip('_')

    @staticmethod
    def parse_date(date_str: str) -> datetime:
        """Parse the date string from the summary file."""
        try:
            # Format: "Wed Oct 22 05:21:03 UTC 2025"
            return datetime.strptime(date_str, "%a %b %d %H:%M:%S %Z %Y")
        except ValueError as e:
            print(f"Warning: Failed to parse date '{date_str}': {e}")
            return datetime.now()

    @staticmethod
    def parse_value(value_str: str) -> Optional[float]:
        """
        Parse a metric value, handling various formats.
        - Time format (HH:MM:SS) -> total seconds
        - Numeric values -> float
        - Invalid values -> None
        """
        value_str = value_str.strip()

        # Handle malformed data (unsure why this happens sometimes)
        if "8796093022208" in value_str:
            return None

        # Handle time format (HH:MM:SS)
        if ':' in value_str and len(value_str.split(':')) == 3:
            try:
                parts = value_str.split(':')
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = int(parts[2])
                return float(hours * 3600 + minutes * 60 + seconds)
            except ValueError:
                return None

        # Handle numeric values
        try:
            return float(value_str)
        except ValueError:
            return None

    def parse_report(self, report: str) -> Tuple[datetime, Dict[str, Dict[str, float]]]:
        """
        Parse a benchmark summary report.

        Returns:
            Tuple of (date, metrics_dict) where metrics_dict is:
            {
                "entity_name": {
                    "metric_name": value,
                    ...
                },
                ...
            }
        """
        sections = report.split("----------------------------------------------------------\n")

        if len(sections) < 3:
            raise ValueError("Invalid report format: missing sections")

        # Extract date from section 1 (index 1)
        date_line = None
        for line in sections[1].split('\n'):
            if "Run at" in line:
                date_line = line.split("Run at")[1].strip()
                break

        if not date_line:
            raise ValueError("Could not find 'Run at' date in report")

        report_date = self.parse_date(date_line)

        # Parse metrics section (index 2)
        metrics_section = sections[2].strip()
        lines = metrics_section.split('\n')

        if not lines:
            raise ValueError("Empty metrics section")

        # Extract entity names (column headers) from first line
        header_line = lines[0]
        if ':' not in header_line:
            raise ValueError("Invalid header format")

        header_parts = header_line.split(':', 1)
        entities = self.split_by_multiple_spaces(header_parts[1])

        # Initialize metrics dictionary
        metrics: Dict[str, Dict[str, float]] = {entity: {} for entity in entities}

        # Parse each metric line
        for line in lines[1:]:
            if not line.strip():
                continue

            # Skip the "Run duration" line and other headers
            if ':' not in line:
                continue

            parts = line.split(':', 1)
            metric_name = parts[0].strip()

            # Skip if metric name is empty or is the header line
            if not metric_name or metric_name == "Agent":
                continue

            # Normalize the metric name
            normalized_name = self.normalize_metric_name(metric_name)

            # Parse values for each entity
            values_str = parts[1]
            values = self.split_by_multiple_spaces(values_str)

            # Match values to entities
            for i, entity in enumerate(entities):
                if i < len(values):
                    parsed_value = self.parse_value(values[i])
                    if parsed_value is not None:
                        # Round to 2 decimal places like the Go implementation
                        metrics[entity][normalized_name] = round(parsed_value, 2)

        return report_date, metrics


class BenchmarkMetricsCollector:
    """Collects benchmark overhead metrics from GitHub gh-pages branch."""

    BASE_URL = "https://raw.githubusercontent.com/open-telemetry/opentelemetry-java-instrumentation/gh-pages/benchmark-overhead/results"

    TEST_TYPES = [
        "release",
        "snapshot",
        "snapshot-regression"
    ]

    def __init__(self):
        self.parser = BenchmarkReportParser()

    def fetch_summary_file(self, test_type: str) -> Optional[str]:
        """Fetch a summary.txt file from GitHub."""
        url = f"{self.BASE_URL}/{test_type}/summary.txt"

        try:
            print(f"  Fetching {test_type}/summary.txt...")
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"  Error fetching {test_type}/summary.txt: {e}")
            return None

    def collect_and_export_metrics(self):
        """Collect all benchmark metrics and export them via OTLP."""
        print("Collecting benchmark overhead metrics...")
        print("=" * 60)

        for test_type in self.TEST_TYPES:
            print(f"\nProcessing {test_type} benchmarks:")

            summary_content = self.fetch_summary_file(test_type)
            if not summary_content:
                print(f"  Skipping {test_type} due to fetch error")
                continue

            try:
                report_date, metrics = self.parser.parse_report(summary_content)
                print(f"  Report date: {report_date}")
                print(f"  Entities found: {list(metrics.keys())}")

                for entity, entity_metrics in metrics.items():
                    print(f"\n  Entity: {entity}")
                    print(f"  {'-' * 50}")

                    for metric_name, value in entity_metrics.items():
                        full_metric_name = f"benchmark.{metric_name}"

                        gauge = meter.create_gauge(full_metric_name)
                        gauge.set(
                            value,
                            {
                                "entity": entity,
                                "test_type": test_type,
                            }
                        )

                        print(f"    {full_metric_name:<40} = {value:>12.2f}  [entity={entity}, test_type={test_type}]")

                print(f"\n  Successfully exported {sum(len(m) for m in metrics.values())} metrics for {test_type}")

            except Exception as e:
                print(f"  Error parsing {test_type} report: {e}")
                continue

        print("\n" + "=" * 60)
        print("Benchmark metrics collection complete")


def main():
    """Main entry point for benchmark metrics collection."""
    print("=" * 60)
    print("OpenTelemetry Java Benchmark Overhead Metrics")
    print("=" * 60)
    print()

    collector = BenchmarkMetricsCollector()
    collector.collect_and_export_metrics()

    print("\nFlushing metrics before exit...")
    provider.force_flush()

    print("Metrics flushed. The script will exit after 5 seconds.")
    time.sleep(5)


if __name__ == "__main__":
    main()
