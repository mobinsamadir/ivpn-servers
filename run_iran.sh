#!/usr/bin/env bash
set -e

# Change directory to script directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================="
echo "🇮🇷 ivpn-servers: Starting Iran Node Test"
echo "⏰ Time: $(date)"
echo "=========================================="

# 1. Update repository with latest candidate servers from GitHub
echo "📥 Fetching latest candidate configs from GitHub..."
git pull --rebase --autostash origin main

# 2. Activate Python virtualenv if exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# 3. Run test with lowest CPU priority (nice -n 19) to ensure 0% impact on existing website
echo "🚀 Running audit with low CPU priority (nice -n 19)..."
nice -n 19 python3 iran_test.py "$@"

echo "=========================================="
echo "✅ Iran Test Cycle Completed!"
echo "=========================================="
