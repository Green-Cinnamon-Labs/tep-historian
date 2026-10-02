"""Ponto de entrada: `python -m tep_historian`."""

import logging
import os

import uvicorn

from .api import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[historian] %(levelname)s %(message)s")
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8090")))


if __name__ == "__main__":
    main()
