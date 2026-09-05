"""Barkod okuyucu: sıralama, çift okuma koruması ve karar penceresi davranışı.

Bu modülün koruduğu üç gerçek hata:
  * 450 ms'lik çift-okuma penceresi, aynı ürünü hızlı okutmayı ENGELLİYORDU,
  * karar penceresi kapandıktan sonra biriken okutmalar GECİKMİŞ SATIŞ
    üretiyordu,
  * aynı olayın iki kez teslimi ürünü iki kez satıyordu.

Testler sahte saat kullanır: hiç ``sleep`` yoktur, sonuçlar belirlidir.
"""
from __future__ import annotations

import pytest

from app.scanner.scan_event import ScanEvent
from app.scanner.scan_router import RouterMode, ScanOutcome, ScanRouter
from app.services.scan_guard import ScanGuard


class SahteSaat:
    """İlerletilebilir tekdüze saat (saniye cinsinden)."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, ms: float) -> None:
        self.now += ms / 1000.0


@pytest.fixture
def saat():
    return SahteSaat()


@pytest.fixture
def router(saat):
    return ScanRouter(guard=ScanGuard(window_ms=120, clock=saat))


def _olay(code: str) -> ScanEvent:
    return ScanEvent(code=code, key_count=13, avg_gap_ms=8.0)


# ===================== Sıra ve teslim ====================================
def test_okutma_etkin_ekrana_gider(router):
    gelenler = []
    router.register("satis", gelenler.append)
    router.set_context("satis")

    assert router.dispatch(_olay("8690504001492")) is ScanOutcome.HANDLED
    assert [e.code for e in gelenler] == ["8690504001492"]


def test_isleyici_yoksa_okutma_kaybolmaz_bildirilir(router):
    assert router.dispatch(_olay("123")) is ScanOutcome.NO_HANDLER
    assert router.diagnostics()[-1][1] is ScanOutcome.NO_HANDLER


def test_on_hizli_okutma_sirayla_islenir(router, saat):
    """Aynı barkodun 10 kez okutulması BİRİNCİL miktar giriş yöntemidir."""
    gelenler = []
    router.register("satis", gelenler.append)
    router.set_context("satis")

    for _ in range(10):
        saat.advance(300)                       # gerçekçi: ~3 saniyede 10 okutma
        router.dispatch(_olay("8690504001492"))

    assert len(gelenler) == 10, "hiçbir okutma düşmedi"
    assert all(e.code == "8690504001492" for e in gelenler)


def test_farkli_barkodlar_sirayla_islenir(router, saat):
    gelenler = []
    router.register("satis", gelenler.append)
    router.set_context("satis")

    kodlar = [f"869000000000{i}" for i in range(10)]
    for kod in kodlar:
        saat.advance(50)
        router.dispatch(_olay(kod))

    assert [e.code for e in gelenler] == kodlar, "SIRA korunur"


def test_isleyici_icinden_gelen_okutma_siraya_girer(router, saat):
    """Yeniden giriş: işleyici çalışırken gelen okutma kaybolmamalı."""
    gelenler = []

    def isleyici(event):
        gelenler.append(event.code)
        if event.code == "ILK":
            saat.advance(500)
            router.dispatch(_olay("IKINCI"))

    router.register("satis", isleyici)
    router.set_context("satis")
    router.dispatch(_olay("ILK"))

    assert gelenler == ["ILK", "IKINCI"]


# ===================== Çift okuma koruması ===============================
def test_donanim_cift_tetiklemesi_yutulur(router, saat):
    gelenler = []
    router.register("satis", gelenler.append)
    router.set_context("satis")

    router.dispatch(_olay("8690504001492"))
    saat.advance(15)                            # okuyucu çift-tetiklemesi
    sonuc = router.dispatch(_olay("8690504001492"))

    assert sonuc is ScanOutcome.DUPLICATE
    assert len(gelenler) == 1


def test_insan_hizinda_tekrar_okutma_ENGELLENMEZ(router, saat):
    """En kritik ayar: 250 ms sonra gelen aynı barkod GERÇEK bir satıştır."""
    gelenler = []
    router.register("satis", gelenler.append)
    router.set_context("satis")

    router.dispatch(_olay("8690504001492"))
    saat.advance(250)
    router.dispatch(_olay("8690504001492"))

    assert len(gelenler) == 2, "120 ms'lik pencere gerçek satışı düşürmez"


def test_farkli_barkod_hemen_kabul_edilir(router, saat):
    gelenler = []
    router.register("satis", gelenler.append)
    router.set_context("satis")

    router.dispatch(_olay("AAA"))
    saat.advance(5)
    router.dispatch(_olay("BBB"))
    assert len(gelenler) == 2


def test_ekran_degisince_koruma_sifirlanir(router, saat):
    gelenler = []
    router.register("satis", gelenler.append)
    router.register("stok", gelenler.append)

    router.set_context("satis")
    router.dispatch(_olay("AAA"))
    saat.advance(10)
    router.set_context("stok")
    router.dispatch(_olay("AAA"))

    assert len(gelenler) == 2, "başka ekranda aynı barkod yeni bir işlemdir"


def test_ayni_olay_iki_kez_teslim_edilirse_bir_kez_islenir(router):
    """Idempotans: Qt olayı yinelerse ürün iki kez satılmamalı."""
    gelenler = []
    router.register("satis", gelenler.append)
    router.set_context("satis")

    olay = _olay("8690504001492")
    assert router.dispatch(olay) is ScanOutcome.HANDLED
    assert router.dispatch(olay) is ScanOutcome.DUPLICATE
    assert len(gelenler) == 1


# ===================== Karar penceresi ===================================
def test_karar_penceresi_acikken_okutma_ISLENMEZ(router, saat):
    gelenler = []
    engellenenler = []
    router.register("satis", gelenler.append)
    router.on_blocked = engellenenler.append
    router.set_context("satis")

    router.suspend("tanınmayan barkod penceresi")
    for _ in range(5):
        saat.advance(300)
        assert router.dispatch(_olay("8690504001492")) is ScanOutcome.BLOCKED

    assert gelenler == [], "hiçbir satış oluşmadı"
    assert len(engellenenler) == 5, "beşi de ANINDA geri bildirildi"


def test_pencere_kapaninca_GECIKMIS_SATIS_olusmaz(router, saat):
    """Kuyruk oynatılsaydı kullanıcı istemediği satışları görürdü."""
    gelenler = []
    router.register("satis", gelenler.append)
    router.set_context("satis")

    router.suspend()
    for _ in range(3):
        saat.advance(300)
        router.dispatch(_olay("8690504001492"))
    router.resume()

    assert gelenler == [], "kapanışta hiçbir şey işlenmedi"
    assert router.mode is RouterMode.ACTIVE


def test_askidan_sonra_yeni_okutma_normal_islenir(router, saat):
    gelenler = []
    router.register("satis", gelenler.append)
    router.set_context("satis")

    router.suspend()
    router.dispatch(_olay("ENGELLENEN"))
    router.resume()
    saat.advance(300)
    router.dispatch(_olay("YENI"))

    assert [e.code for e in gelenler] == ["YENI"]


def test_isleyici_pencere_acarsa_kalan_kuyruk_islenmez(router, saat):
    """Bir okutma karar penceresi açtıysa, arkasındakiler de sürpriz yapmamalı."""
    gelenler = []

    def isleyici(event):
        # Tanınmayan barkod işlenirken arkadan bir okutma daha gelir; hemen
        # ardından karar penceresi açılır.
        gelenler.append(event.code)
        if event.code == "BILINMEYEN":
            router.dispatch(_olay("ARKADAN_GELEN"))
            router.suspend("ürün tanımlama penceresi")

    router.register("satis", isleyici)
    router.set_context("satis")
    saat.advance(300)
    router.dispatch(_olay("BILINMEYEN"))

    assert gelenler == ["BILINMEYEN"], "arkadan gelen okutma İŞLENMEDİ"
    assert router.is_suspended


def test_engellenen_okutmalar_tanilamada_gorunur(router, saat):
    router.register("satis", lambda e: None)
    router.set_context("satis")
    router.suspend()
    router.dispatch(_olay("ENGELLENEN"))

    kayitlar = router.diagnostics()
    assert kayitlar[-1][0].code == "ENGELLENEN"
    assert kayitlar[-1][1] is ScanOutcome.BLOCKED


def test_isleyici_hatasi_okuyucuyu_kilitlemez(router, saat):
    gelenler = []

    def bazen_patlar(event):
        if event.code == "PATLAT":
            raise RuntimeError("ekran hatası")
        gelenler.append(event.code)

    router.register("satis", bazen_patlar)
    router.set_context("satis")

    router.dispatch(_olay("PATLAT"))
    saat.advance(300)
    router.dispatch(_olay("SONRAKI"))

    assert gelenler == ["SONRAKI"], "hatadan sonra okuyucu çalışmaya devam etti"


# ===================== ScanGuard birimi ==================================
def test_guard_penceresi_kapatilabilir(saat):
    guard = ScanGuard(window_ms=0, clock=saat)
    assert guard.check("AAA", "satis") is True
    assert guard.check("AAA", "satis") is True, "0 = koruma kapalı"


def test_guard_varsayilani_120_ms():
    from app.services.scan_guard import DEFAULT_WINDOW_MS

    assert DEFAULT_WINDOW_MS == 120, (
        "tekrar okutma birincil miktar giriş yöntemi olduğu için dar tutulur"
    )


def test_ayarlardan_gelen_pencere_sinirlanir(services):
    services.settings.set("duplicate_scan_ms", 99999)
    assert services.settings.duplicate_scan_ms() == 1000
    services.settings.set("duplicate_scan_ms", -5)
    assert services.settings.duplicate_scan_ms() == 0


# ===================== ScanEvent =========================================
def test_okuyucu_hizi_taninir():
    okuyucu = ScanEvent(code="8690504001492", key_count=13, avg_gap_ms=8.0)
    insan = ScanEvent(code="8690504001492", key_count=13, avg_gap_ms=180.0)
    assert okuyucu.looks_machine_typed is True
    assert insan.looks_machine_typed is False
    assert "barkod okuyucu" in okuyucu.describe()


def test_her_olayin_benzersiz_kimligi_vardir():
    a = ScanEvent(code="AAA")
    b = ScanEvent(code="AAA")
    assert a.scan_id != b.scan_id, "bilerek tekrar okutmak yeni bir olaydır"
