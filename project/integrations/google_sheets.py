from __future__ import annotations
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

# ----------------------------
# Client & Worksheet helpers
# ----------------------------

def get_client() -> Optional[gspread.Client]:
    """
    Returnează clientul gspread construit din GCP_SA_JSON (env).
    Dacă lipsesc credențialele, întoarce None (nu aruncă).
    """
    sa_json = os.getenv("GCP_SA_JSON")
    if not sa_json:
        return None
    try:
        info = json.loads(sa_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception:
        return None


def get_worksheet(client: gspread.Client) -> Optional[gspread.Worksheet]:
    """
    Deschide worksheet-ul pe baza env-urilor SPREADSHEET_ID și SHEET_NAME.
    Creează sheet-ul dacă lipsește (cu header corect).
    """
    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    sheet_name = os.getenv("SHEET_NAME") or "Orders"
    if not client or not spreadsheet_id:
        return None

    sh = client.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(sheet_name)
    except WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows=200, cols=20)
        ws.append_row(default_header(), value_input_option="USER_ENTERED")

    # asigură headerul corect (dacă a fost modificat manual)
    ensure_header(ws)
    return ws


# ----------------------------
# Schema & Header
# ----------------------------

def default_header() -> List[str]:
    """
    Ordinea coloanelor folosite în tot proiectul (compatibil cu webhook.py).
    """
    return [
        "timestamp", "platform", "user_id",
        "product", "price",
        "name", "phone", "city", "address",
        "delivery", "payment",
        "photo_urls", "prepay_proof_urls",
        "deadline_client", "avans",
    ]


def ensure_header(ws: "gspread.Worksheet") -> None:
    """
    Verifică prima linie; dacă lipsesc coloane din schema standard, le adaugă la final.
    Nu rescrie valorile existente.
    """
    try:
        hdr = [h.strip() for h in ws.row_values(1)]
    except Exception:
        hdr = []

    wanted = default_header()
    if not hdr:
        ws.update("A1", [wanted])
        return

    missing = [c for c in wanted if c not in hdr]
    if missing:
        # scriem coloanele lipsă după ultimele existente
        start_col = len(hdr) + 1
        for i, name in enumerate(missing, start=0):
            ws.update_cell(1, start_col + i, name)


# ----------------------------
# Append utils
# ----------------------------

def append_order_row(ws: "gspread.Worksheet", row: List[str]) -> bool:
    """
    Adaugă o linie în sheet. Returnează True/False fără a arunca mai departe.
    """
    try:
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception:
        return False


def export_order(order: Dict) -> bool:
    """
    Exportă o comandă în Google Sheets.
    Așteaptă chei compatibile cu schema: name, phone, city, address, delivery, payment,
    product, price, platform, user_id, photo_urls, prepay_proof_urls, deadline_client, avans.
    Convertește automat listele în string-uri „; ”.
    """
    client = get_client()
    if not client:
        return False
    ws = get_worksheet(client)
    if not ws:
        return False

    def as_str_list(v):
        if v is None:
            return ""
        if isinstance(v, (list, tuple)):
            return "; ".join([str(x) for x in v if x is not None])
        return str(v)

    row = [
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        as_str_list(order.get("platform") or "instagram"),
        as_str_list(order.get("user_id") or ""),
        as_str_list(order.get("product") or ""),
        as_str_list(order.get("price") or ""),
        as_str_list(order.get("name") or ""),
        as_str_list(order.get("phone") or ""),
        as_str_list(order.get("city") or ""),
        as_str_list(order.get("address") or ""),
        as_str_list(order.get("delivery") or ""),
        as_str_list(order.get("payment") or ""),
        as_str_list(order.get("photo_urls") or []),
        as_str_list(order.get("prepay_proof_urls") or []),
        as_str_list(order.get("deadline_client") or ""),
        as_str_list(order.get("avans") or order.get("advance_amount") or ""),
    ]
    return append_order_row(ws, row)
