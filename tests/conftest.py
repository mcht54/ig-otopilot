import pytest


@pytest.fixture(autouse=True)
def _robot_hikaye_bos(monkeypatch):
    """Testler ayrı hikâye akışını doğrular; Hikâye Robotu listesi testte boş (robot davranışı ayrı testte)."""
    from otopilot import calistir
    monkeypatch.setattr(calistir, "ROBOT_HIKAYE", set())


@pytest.fixture(autouse=True)
def _panel_oidc_yok(monkeypatch):
    """Testte panele asla istek gitmesin (main() paylaşımdan önce platform ayarlarını tazeler)."""
    monkeypatch.delenv("ACTIONS_ID_TOKEN_REQUEST_URL", raising=False)
    monkeypatch.delenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", raising=False)
