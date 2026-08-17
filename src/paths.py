from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
TICKERS_PATH = CONFIG_DIR / "tickers.yaml"
TICKERS_EXAMPLE_PATH = CONFIG_DIR / "tickers.example.yaml"
SHARED_CONDITIONS_PATH = CONFIG_DIR / "shared_conditions.yaml"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "pa.sqlite"
FIXTURES_DIR = ROOT / "tests" / "fixtures"
