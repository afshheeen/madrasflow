import json
from pathlib import Path
import duckdb

def connection(path=':memory:'):
    con = duckdb.connect(str(path))
    con.execute("SET threads=4")
    con.execute("SET memory_limit='2GB'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET enable_progress_bar=false")
    return con

def literal(value):
    return "'" + str(value).replace("'", "''") + "'"

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding='utf-8')

def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))
