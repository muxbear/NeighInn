from __future__ import annotations

import asyncio
import selectors
import sys

import uvicorn

if sys.platform == "win32":
    # psycopg async cannot use the Windows ProactorEventLoop. Run uvicorn on a
    # selector loop explicitly instead of relying on the process-wide policy.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


if __name__ == "__main__":
    config = uvicorn.Config("src.main:app", host="127.0.0.1", port=5193, loop="asyncio")
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    else:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(server.serve())
