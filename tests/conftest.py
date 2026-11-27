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


@pytest.fixture(autouse=True)
def _gemini_havuz_gecici(monkeypatch, tmp_path):
    """Gemini anahtar havuzunun dolu işaretleri testte geçici dosyaya yazılır (depodaki durum/ kirlenmez)."""
    monkeypatch.setenv("GEMINI_HAVUZ_DOSYASI", str(tmp_path / "gemini-havuz.json"))
    for i in range(1, 10):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
