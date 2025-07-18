# GitHub Metrics Exporter

This project provides a GitHub Action to collect various metrics from GitHub repositories and send them to a Grafana
Cloud instance (or any OpenTelemetry-compatible metrics backend).

![screenshot](./img/dashboard-screenshot.png)

## What it Does

The script `main.py` performs the following actions:

1.  **GitHub Repository Metrics:** Fetches the number of open issues, open pull requests, and star count for specified GitHub repositories.
2.  **Instrumentation Metadata Metrics:** Fetches and parses a YAML file from a specific GitHub repository (`open-telemetry/opentelemetry-java-instrumentation/docs/instrumentation-list.yaml`) to extract counts of:
    *   Total libraries.
    *   Libraries with descriptions.
    *   Libraries with `javaagent` target versions.
    *   Libraries with `library` target versions.
    *   Libraries with telemetry configurations.

All collected metrics are exported using OpenTelemetry Protocol (OTLP) to a configured endpoint.

## Running Locally

To run and test this project locally, you can use Docker Compose to set up a local OpenTelemetry Collector and Grafana instance.

### Prerequisites

*   Docker
*   Python 3.8+
*   A GitHub Personal Access Token (PAT) with `repo` scope (for fetching GitHub data).

### Setup

1.  **Start the Local Environment:**
    ```bash
    docker-compose up -d
    ```
    This will start an OpenTelemetry Collector listening on `http://localhost:4318` and a Grafana instance accessible at `http://localhost:3000`

2.  **Install Python Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Run the Script:**
    Execute the `main.py` script, replace `YOUR_GITHUB_TOKEN` with your actual token.
    
    ```bash
    export GITHUB_TOKEN="YOUR_GITHUB_TOKEN"
    python3 main.py
    ```

4.  **View Metrics in Grafana:**
    Open your browser to `http://localhost:3000`. You can then use the Explore view to query for metrics like `repo.issues.open` or `instrumentation.libraries.total`.
    There are also pre-built dashboards for both cloud and local development

## GitHub Action Setup

This project is designed to run as a GitHub Action on a recurring schedule.

### Workflow File

The workflow is defined in `.github/workflows/nightly-metrics.yml`. It is configured to run every 12 hours and can also be triggered manually.

### Required GitHub Secrets

To enable the GitHub Action to run successfully, you must configure the following secrets in your GitHub repository settings (`Settings` > `Secrets and variables` > `Actions`):

1.  **`OTEL_EXPORTER_OTLP_ENDPOINT`**
    *   In Grafana Cloud, navigate to your stack, then find the OTLP configuration details. Look for the metrics endpoint URL.

2.  **`OTEL_EXPORTER_OTLP_HEADERS`**
    *   The authorization headers required by your Grafana Cloud OTLP endpoint. This typically involves Basic Authentication using your Grafana Cloud Instance ID (username) and an API Key (password).
    *   **How to get it:**
        1.  In Grafana Cloud, go to `Security` > `API Keys` and create a new API key with the `Metrics Publisher` role. Note down the Instance ID and the generated API Key.
        2.  Combine your Instance ID and API Key in the format `YOUR_INSTANCE_ID:YOUR_API_KEY`.
        3.  Base64 encode this combined string. You can do this on the command line:
            ```bash
            echo -n "YOUR_INSTANCE_ID:YOUR_API_KEY" | base64
            ```
        4.  The secret value should then be in the format `Authorization=Basic <base64_encoded_string>`.
    *   **Example:** If your base64 encoded string is `MTIzNDU2OmdsY18uLi4=`, the secret value would be `Authorization=Basic MTIzNDU2OmdsY14uLi4=`

### GitHub Action Environment (if applicable)

If you have configured these secrets within a specific GitHub Action environment (e.g., `production`), ensure that your workflow job explicitly references that environment:

```yaml
jobs:
  build-and-run:
    runs-on: ubuntu-latest
    environment: your-environment-name # Add this line if using an environment
    # ... rest of your job configuration
```

