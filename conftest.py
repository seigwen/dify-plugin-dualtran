import pathlib
import sys

# The plugin root must be importable so tests can load tools/ and provider/.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
