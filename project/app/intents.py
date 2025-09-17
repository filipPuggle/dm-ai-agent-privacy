class Intents:
    """Defines all supported conversation intents."""

    ORDER = "ORDER"               # user vrea să comande / să cumpere
    FAQ_PRICING = "FAQ_PRICING"   # întreabă de preț
    FAQ_DELIVERY = "FAQ_DELIVERY" # întreabă de livrare
    FAQ_TERMS = "FAQ_TERMS"       # întreabă de termene / durată
    MEDIA = "MEDIA"               # a trimis o poză / postare
    OTHER = "OTHER"               # orice altceva (fallback)

    @staticmethod
    def list_all():
        """Return all available intents as a list."""
        return [
            Intents.ORDER,
            Intents.FAQ_PRICING,
            Intents.FAQ_DELIVERY,
            Intents.FAQ_TERMS,
            Intents.MEDIA,
            Intents.OTHER,
        ]