import os
import logging
from flask import Flask
from dotenv import load_dotenv

def create_app():
    # încarcă env vars
    load_dotenv()

    app = Flask(__name__)
    logging.basicConfig(level=logging.INFO)

    # importă și înregistrează rutele din webhook.py
    from . import webhook
    app.register_blueprint(webhook.bp)

    return app
