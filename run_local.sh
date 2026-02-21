#!/bin/bash
echo "Starting Local Test..."
python3 local_test.py
if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Test failed or script error."
else
    echo ""
    echo "✅ Test finished."
fi
