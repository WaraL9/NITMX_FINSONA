"""Dev server entry point, restarted by `watchfiles` on code changes (see `npm run dev:api`).

uvicorn's own --reload can hang on Windows when restarting its worker; watchfiles
kills and relaunches the whole process instead, which is reliable on every OS.
"""

import uvicorn


def run() -> None:
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
