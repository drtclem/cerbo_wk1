from app.seams.notifier import FakeNotifier, Notifier

database_url = "sqlite:///./cerbo.db"


def build_notifier() -> Notifier:
    """The only place the notifier stub is chosen."""
    return FakeNotifier()
