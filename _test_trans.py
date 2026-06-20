import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
try:
    import fsnovel_downloader as fd
    fd._load_glossary()
    print("Translating '你好'...")
    res, fail = fd.translate_text("你好")
    print(f"Result: '{res}', fail count: {fail}")
except Exception as e:
    print(f"Error: {e}")
