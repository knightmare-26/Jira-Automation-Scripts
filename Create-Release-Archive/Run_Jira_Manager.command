#!/bin/bash
# Move to the directory where this script is located
cd -- "$(dirname "$0")"

echo "------------------------------------------------"
echo "      Jira Version Manager - One-Click Start    "
echo "------------------------------------------------"

# 1. Check for Python 3
if ! command -v python3 &> /dev/null
then
    echo "❌ Error: Python 3 is not installed on this Mac."
    echo "Please download and install it from: https://www.python.org/downloads/"
    echo ""
    read -p "Press Enter to exit..."
    exit
fi

# 2. Install/Update dependencies silently
echo "🔄 Checking for required components... (this may take a moment the first time)"
python3 -m pip install -r requirements.txt --user --quiet

# 3. Launch the app
echo "🚀 Launching the Jira Version Manager..."
echo "Wait for a new tab to open in your web browser."
echo ""
echo "(You can minimize this window, but don't close it while using the app)"

# Running via 'python3 -m streamlit' is more reliable than 'streamlit' command
python3 -m streamlit run jira_ui.py --server.headless true
