import pytest


@pytest.fixture(autouse=True)
def _robot_hikaye_bos(monkeypatch):
    """Testler ayrı hikâye akışını doğrular; Hikâye Robotu listesi testte boş (robot davranışı ayrı testte)."""
    from otopilot import calistir
    monkeypatch.setattr(calistir, "ROBOT_HIKAYE", set())
