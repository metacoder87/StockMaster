import os
import sys

# Get the project root directory (one level up from tests)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add the project root to Python path if not already present
if project_root not in sys.path:
	sys.path.insert(0, project_root)
