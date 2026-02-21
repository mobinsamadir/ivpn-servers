# V2Ray Config Aggregator & Tester

This tool aggregates V2Ray/Xray subscription URLs, deduplicates configurations, and tests them for TCP connectivity and Real Delay (latency). It automatically updates the list of valid configurations every 12 hours via GitHub Actions.

## Architecture

1.  **Aggregator (`aggregator.py`)**: Fetches subscriptions from `sources.txt`, parses configs, deduplicates them, and saves to `all_configs.txt`.
2.  **Tester (`tester.py`)**:
    *   Reads `all_configs.txt`.
    *   Performs mass TCP connectivity tests -> `tcp_passed.txt`.
    *   Performs Real Delay tests (using Xray core) on TCP-passed configs -> `real_delay_passed.txt`.
3.  **Local Test (`local_test.py`)**: Allows users to run tests on their own machine using the latest passed configs.

## Output Files

*   `all_configs.txt`: All unique configurations found.
*   `tcp_passed.txt`: Configs that passed TCP connection test.
*   `real_delay_passed.txt`: Configs that passed full Xray connection test.

## Local Testing

You can run a local test to verify the configurations from your own network environment. This is useful because a config working on GitHub Actions (US/Europe) might not work from your specific location.

### Prerequisites

*   Python 3.9+
*   Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

### Running the Test

**Windows:**
Double-click `run_local.bat`.

**Linux/macOS:**
Run `./run_local.sh`.

The script will:
1.  Read `real_delay_passed.txt` (which contains configs that already passed server-side tests).
2.  Download Xray core if missing.
3.  Test each config by attempting to connect through it to a test URL.
4.  Save results to `local_results/<timestamp>/` including a detailed JSON report and a passed config list.

### Configuration

You can configure concurrency and timeouts via environment variables:

*   `REAL_DELAY_CONCURRENCY` (default: 50) - How many concurrent tests to run.
*   `REAL_DELAY_TIMEOUT` (default: 5.0) - Timeout in seconds.
*   `TEST_URL` (default: `http://cp.cloudflare.com/generate_204`) - The URL to test connectivity against.

## GitHub Workflow

The workflow runs every 12 hours (UTC) and commits the updated lists back to the repository. It handles the aggregation and initial testing.
