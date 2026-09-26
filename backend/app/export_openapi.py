"""Write the OpenAPI schema to backend/openapi.json for frontend type generation.

    python -m app.export_openapi
"""

import json

from app.config import BACKEND_DIR
from app.main import app

if __name__ == "__main__":
    out = BACKEND_DIR / "openapi.json"
    out.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
