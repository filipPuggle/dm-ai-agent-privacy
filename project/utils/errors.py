"""
Definim erorile custom pentru proiect.
Se folosesc în flows, business logic și integrări.
"""

class AgentError(Exception):
    """Eroare generică a agentului."""
    pass


# ---------------- Business / Flow ----------------

class ValidationError(AgentError):
    """Date lipsă sau invalide (ex: fără număr de telefon)."""
    pass


class DeadlineError(AgentError):
    """Termen limită imposibil de respectat."""
    pass


class PricingError(AgentError):
    """Probleme la calcularea prețului."""
    pass


class ShippingError(AgentError):
    """Probleme la determinarea metodei de livrare."""
    pass


# ---------------- Integrations ----------------

class GoogleSheetsError(AgentError):
    """Export spre Google Sheets a eșuat."""
    pass


class RateLimitError(AgentError):
    """Depășire a limitelor de rată (ex: API extern)."""
    pass


class RetryExhaustedError(AgentError):
    """Toate încercările de retry au eșuat."""
    pass