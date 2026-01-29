#!/bin/bash
set -e

echo "=========================================="
echo "Running Benchmark Metrics Collection"
echo "=========================================="
echo ""

echo "1. Collecting OpenTelemetry Java Instrumentation Benchmarks..."
python ./benchmark_metrics.py

echo ""
echo "=========================================="
echo ""

echo "2. Collecting Prometheus Client Java Benchmarks..."
python ./prometheus_benchmark_metrics.py

echo ""
echo "=========================================="
echo "All benchmark metrics collected successfully!"
echo "=========================================="