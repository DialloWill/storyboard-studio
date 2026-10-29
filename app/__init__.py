import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

from . import storage


def create_app(config=None):
    app = Flask(__name__)

    # Tests must never read a real .env file.
    if not (config and config.get("TESTING")):
        load_dotenv()

    app.config.update(
        DATA_DIR="data",
        GENERATOR=os.environ.get("GENERATOR", "mock"),
        COMFY_API_KEY=os.environ.get("COMFY_API_KEY", ""),
    )
    app.config.update(config or {})

    # Absolute path: send_file resolves relative paths against the app folder, not the cwd.
    app.config["DATA_DIR"] = Path(app.config["DATA_DIR"]).resolve()
    storage.ensure_data_dir(app.config["DATA_DIR"])

    from .routes import bp
    app.register_blueprint(bp)
    return app
