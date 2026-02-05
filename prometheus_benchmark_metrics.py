import json
import re
import time
from typing import Dict, List, Optional

import requests
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider, Counter
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, AggregationTemporality
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource

resource = Resource.create({"service.name": "prometheus-benchmark-metrics"})

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

meter = metrics.get_meter("prometheus.benchmark.metrics.meter")


class JMHResultsParser:
    """Parser for JMH benchmark results in JSON format."""

    @staticmethod
    def parse_benchmark_name(benchmark_path: str) -> tuple[str, str]:
        """
        Parse the benchmark path to extract class and method names.

        Example:
            "io.prometheus.metrics.benchmarks.CounterBenchmark.codahaleIncNoLabels"
            Returns: ("CounterBenchmark", "codahaleIncNoLabels")
        """
        parts = benchmark_path.split('.')
        if len(parts) >= 2:
            class_name = parts[-2]  # e.g., "CounterBenchmark"
            method_name = parts[-1]  # e.g., "codahaleIncNoLabels"
            return class_name, method_name
        return "unknown", "unknown"

    @staticmethod
    def normalize_class_name(class_name: str) -> str:
        """
        Normalize class name to lowercase for metric naming.
        Example: "CounterBenchmark" -> "counterbenchmark"
        """
        return class_name.lower()

    def parse_results(self, results_json: str) -> List[Dict]:
        """
        Parse JMH results JSON and extract benchmark metrics.

        Returns:
            List of dictionaries containing:
            {
                "class_name": str,
                "method_name": str,
                "score": float,
                "score_error": float,
                "score_unit": str,
                "threads": int,
                "forks": int,
            }
        """
        try:
            results = json.loads(results_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON: {e}")

        benchmarks = []

        for result in results:
            benchmark_path = result.get("benchmark", "")
            class_name, method_name = self.parse_benchmark_name(benchmark_path)

            primary_metric = result.get("primaryMetric", {})
            score = primary_metric.get("score", 0.0)
            score_error = primary_metric.get("scoreError", 0.0)
            score_unit = primary_metric.get("scoreUnit", "ops/s")

            threads = result.get("threads", 1)
            forks = result.get("forks", 1)

            benchmarks.append({
                "class_name": class_name,
                "method_name": method_name,
                "score": score,
                "score_error": score_error,
                "score_unit": score_unit,
                "threads": threads,
                "forks": forks,
            })

        return benchmarks


class PrometheusBenchmarkMetricsCollector:
    """Collects Prometheus client_java benchmark metrics from GitHub."""

    RESULTS_URL = "https://raw.githubusercontent.com/prometheus/client_java/benchmarks/results.json"
    README_URL = "https://raw.githubusercontent.com/prometheus/client_java/benchmarks/README.md"

    def __init__(self):
        self.parser = JMHResultsParser()

    def fetch_results(self) -> Optional[str]:
        try:
            print(f"  Fetching results.json from {self.RESULTS_URL}...")
            response = requests.get(self.RESULTS_URL, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"  Error fetching results.json: {e}")
            return None

    def fetch_readme(self) -> Optional[str]:
        try:
            print(f"  Fetching README.md from {self.README_URL}...")
            response = requests.get(self.README_URL, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"  Error fetching README.md: {e}")
            return None

    def parse_processor_type(self, readme_content: str) -> str:
        """
        Parse the processor type from README.md.

        Expected format:
        - **Hardware:** AMD EPYC 7763 64-Core Processor, 4 cores, 16 GB RAM

        Returns:
            Processor type string or "unknown" if not found.
        """
        try:
            # Look for the Hardware line in the README
            hardware_match = re.search(r'-\s*\*\*Hardware:\*\*\s*([^,]+)', readme_content)
            if hardware_match:
                processor = hardware_match.group(1).strip()
                print(f"  Found processor: {processor}")
                return processor
            else:
                print("  Warning: Could not find processor information in README.md")
                return "unknown"
        except Exception as e:
            print(f"  Error parsing processor type: {e}")
            return "unknown"

    def collect_and_export_metrics(self):
        print("Collecting Prometheus client_java benchmark metrics...")
        print("=" * 60)

        results_content = self.fetch_results()
        if not results_content:
            print("  Failed to fetch results. Exiting.")
            return

        readme_content = self.fetch_readme()
        processor_type = "unknown"
        if readme_content:
            processor_type = self.parse_processor_type(readme_content)
        else:
            print("  Warning: Could not fetch README.md, using 'unknown' for processor type")
        print()

        try:
            benchmarks = self.parser.parse_results(results_content)
            print(f"  Parsed {len(benchmarks)} benchmark results")
            print()

            # Group benchmarks by class for better organization
            benchmarks_by_class = {}
            for benchmark in benchmarks:
                class_name = benchmark["class_name"]
                if class_name not in benchmarks_by_class:
                    benchmarks_by_class[class_name] = []
                benchmarks_by_class[class_name].append(benchmark)

            # Export metrics for each benchmark
            total_metrics = 0
            for class_name in sorted(benchmarks_by_class.keys()):
                print(f"Processing {class_name}:")
                print(f"  {'-' * 56}")

                class_benchmarks = benchmarks_by_class[class_name]
                normalized_class = self.parser.normalize_class_name(class_name)

                for benchmark in class_benchmarks:
                    metric_name = f"prometheus_client.benchmark.{normalized_class}.score"

                    gauge = meter.create_gauge(metric_name)
                    gauge.set(
                        benchmark["score"],
                        {
                            "method": benchmark["method_name"],
                            "threads": str(benchmark["threads"]),
                            "forks": str(benchmark["forks"]),
                            "unit": benchmark["score_unit"],
                            "processor": processor_type,
                        }
                    )

                    # Also export score_error as a separate metric
                    error_metric_name = f"prometheus_client.benchmark.{normalized_class}.score_error"
                    error_gauge = meter.create_gauge(error_metric_name)
                    error_gauge.set(
                        benchmark["score_error"],
                        {
                            "method": benchmark["method_name"],
                            "threads": str(benchmark["threads"]),
                            "forks": str(benchmark["forks"]),
                            "unit": benchmark["score_unit"],
                            "processor": processor_type,
                        }
                    )

                    print(f"    {benchmark['method_name']:<40} = {benchmark['score']:>12.2f} {benchmark['score_unit']} "
                          f"(±{benchmark['score_error']:.2f}) [threads={benchmark['threads']}]")

                    total_metrics += 2  # score + score_error

                print()

            print("=" * 60)
            print(f"Successfully exported {total_metrics} metrics")

        except Exception as e:
            print(f"  Error parsing results: {e}")
            raise


def main():
    """Main entry point for Prometheus benchmark metrics collection."""
    print("=" * 60)
    print("Prometheus Client Java Benchmark Metrics")
    print("=" * 60)
    print()

    collector = PrometheusBenchmarkMetricsCollector()
    collector.collect_and_export_metrics()

    print("\nFlushing metrics before exit...")
    provider.force_flush()

    print("Metrics flushed. The script will exit after 5 seconds.")
    time.sleep(5)


if __name__ == "__main__":
    main()
