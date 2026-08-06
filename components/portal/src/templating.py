"""Shared filesystem paths and the Jinja2 templates instance.

Lives in its own module (not `main`) so the page routers can render templates
without importing `main`, which would create a circular import.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from config import config

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
DOCS_DIR = BASE_DIR / "docs"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["config"] = config
