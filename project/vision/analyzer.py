"""
Analizor pentru fișiere media trimise de clienți (imagini).
Poate fi extins cu OpenAI Vision sau alt model de ML.
"""

from typing import Dict


def analyze_image(file_url: str) -> Dict:
    """
    Analizează o imagine și returnează un rezumat cu informații utile.
    Deocamdată simulăm logica cu reguli simple.
    
    Args:
        file_url: URL / path spre imagine
    
    Returns:
        dict cu rezultate ex:
        {
            "is_valid": True,
            "detected_category": "lamp_design",
            "notes": "Imagine acceptată pentru Lampă după poză"
        }
    """
    if not file_url:
        return {
            "is_valid": False,
            "detected_category": None,
            "notes": "Nu există imagine"
        }

    # TODO: aici putem conecta un model real de vision
    # deocamdată returnăm dummy
    return {
        "is_valid": True,
        "detected_category": "lamp_design",
        "notes": f"Imagine procesată: {file_url}"
    }
