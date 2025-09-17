from app.intents import Intents
from app.nlu.classifier import classify_intent
from app.flows import order_flow, faq_flow, terms_flow, media_flow, fallback_flow

def route_message(user_id: str, text: str) -> str:
    """
    Route the incoming message to the appropriate flow based on intent.
    Returns a reply string (or empty string if no reply).
    """
    # 1. Determină intenția cu classifier-ul
    intent = classify_intent(text)

    # 2. Rutare către fluxul corect
    if intent == Intents.ORDER:
        return order_flow.handle(user_id, text)

    elif intent == Intents.FAQ_PRICING:
        return faq_flow.handle_pricing(user_id, text)

    elif intent == Intents.FAQ_DELIVERY:
        return faq_flow.handle_delivery(user_id, text)

    elif intent == Intents.FAQ_TERMS:
        return terms_flow.handle(user_id, text)

    elif intent == Intents.MEDIA:
        return media_flow.handle(user_id, text)

    else:
        return fallback_flow.handle(user_id, text)
