"""FastAPI application setup and static file serving for OpenVelo Insights."""

from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import FastAPI

from .api import router as api_router

app = FastAPI(title="OpenVelo Insights")

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Serve /static files
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# Serve index.html at "/"
@app.get("/")
def serve_index():
    """Serve the static single-page app."""
    return FileResponse(_STATIC_DIR / "index.html")


# API routes
app.include_router(api_router, prefix="/v1")
