import os
import tempfile

# Ensure tests never pollute user data directory
test_dir = tempfile.TemporaryDirectory()
os.environ["LOCALFIN_DATA_DIR"] = test_dir.name
