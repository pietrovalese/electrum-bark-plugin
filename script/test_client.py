import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from bark.client import BarkClient
print(BarkClient().snapshot())