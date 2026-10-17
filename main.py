import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

data = []

for number in range(1, 6):
    path = BASE_DIR / f"data-part-{number}.json"

    with path.open("r", encoding="utf-8") as file:
        data.extend(json.load(file))
