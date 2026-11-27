"""IG Otopilot ↔ anahtar havuzu: 1. anahtar günlük 429 → 2. anahtar (sahte HTTP, gerçek çağrı yok)."""
import json

from otopilot import llm

GUNLUK = {"error": {"code": 429, "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                              "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}


class Y:
    def __init__(self, veri, kod=200):
        self.status_code, self.text = kod, json.dumps(veri)


def _hazirla(monkeypatch, cagri):
    monkeypatch.setenv("GEMINI_API_KEY", "anahtar-bir")
    monkeypatch.setenv("GEMINI_API_KEY_2", "anahtar-iki")
    monkeypatch.setattr(llm, "_kesif", ["gemini-x-flash"])
    monkeypatch.setattr(llm, "_kota_doldu", set())
    monkeypatch.setattr(llm, "_sayac", {"istek": 0})

    def post(url, headers=None, json=None, timeout=None):
        k = headers["x-goog-api-key"]
        cagri.append(k)
        if k == "anahtar-bir":
            return Y(GUNLUK, 429)
        return Y({"candidates": [{"content": {"parts": [{"text": '{"a": 1}'}]}}]})
    monkeypatch.setattr(llm.requests, "post", post)


def test_birinci_anahtar_dolunca_ikinciye_gecer_ve_hatirlanir(monkeypatch):
    cagri = []
    _hazirla(monkeypatch, cagri)
    assert llm.json_sor("s", "i") == {"a": 1, "_saglayici": "gemini"}
    assert cagri == ["anahtar-bir", "anahtar-iki"]
    assert llm.json_sor("s", "i")["a"] == 1
    assert cagri == ["anahtar-bir", "anahtar-iki", "anahtar-iki"], "dolu anahtar aynı Google gününde yeniden denenmez"
    assert "gemini:gemini-x-flash" not in llm._kota_doldu, "havuzda boş anahtar varken model dolu sayılmaz"


def test_tum_anahtarlar_doluysa_groq_yoksa_none(monkeypatch):
    cagri = []
    _hazirla(monkeypatch, cagri)
    monkeypatch.setenv("GEMINI_API_KEY_2", "anahtar-bir")   # tek gerçek anahtar
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert llm.json_sor("s", "i") is None
    assert cagri == ["anahtar-bir"] and "gemini:gemini-x-flash" in llm._kota_doldu


def test_var_mi_havuzdan(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert not llm.var_mi()
    monkeypatch.setenv("GEMINI_API_KEY_3", "x")
    assert llm.var_mi()
