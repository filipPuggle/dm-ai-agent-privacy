from typing import Dict, List
from app.sendmessage import send_instagram_message

def handle_media(user_id: str, attachments: List[Dict], state: Dict) -> None:
    """
    Procesează atașamente media trimise de client:
    - foto → flux Lampă după poză (P2)
    - video/documente → doar confirmare primire
    """

    if not attachments:
        return

    photo_urls = []
    video_urls = []
    file_urls = []

    for att in attachments:
        att_type = att.get("type")
        url = att.get("payload", {}).get("url")

        if att_type == "image" and url:
            photo_urls.append(url)
        elif att_type == "video" and url:
            video_urls.append(url)
        elif url:
            file_urls.append(url)

    # dacă avem poze → intrăm în flux P2
    if photo_urls:
        state.setdefault("photo_urls", []).extend(photo_urls)
        state["flow"] = "photo"

        send_instagram_message(
            user_id,
            "Am primit fotografia 📸\n"
            "Pe baza acesteia putem realiza lampa dorită 💡.\n"
            "Confirmați dacă doriți să continuăm cu această poză?"
        )
        return

    # dacă avem video → doar confirmăm
    if video_urls:
        send_instagram_message(
            user_id,
            "Am primit video-ul 🎥. Mulțumim! Îl vom transmite colegilor noștri."
        )
        return

    # alte fișiere
    if file_urls:
        send_instagram_message(
            user_id,
            "Am primit documentul atașat 📄. Mulțumim!"
        )
        return
