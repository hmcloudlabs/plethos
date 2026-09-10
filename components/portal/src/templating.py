from pathlib import Path
from fastapi.templating import Jinja2Templates

from auth import add_csrf_token
from config import config

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR),
    context_processors=[add_csrf_token]
)
templates.env.globals["config"] = config