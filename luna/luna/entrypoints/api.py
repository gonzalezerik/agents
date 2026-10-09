"""`python -m luna.entrypoints.api` -- uvicorn entrypoint wiring
`luna.api.main`'s app."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "luna.api.main:app",
        host="0.0.0.0",  # noqa: S104 - intentional: this is the container's only interface
        port=int(os.environ.get("PORT", "8000")),
        # NOTE: no JSON log formatter is wired up yet -- uvicorn's default
        # logging is left as-is for now.
    )


if __name__ == "__main__":
    main()
