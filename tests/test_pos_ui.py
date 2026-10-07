"""Dokunmatik POS arayüzü — V1.1 Sepetli Satış.

Korunan sözler:
  * satış YALNIZCA açık bir ödeme eylemiyle (NAKİT / KART) oluşur,
  * F10 bu ekranı tamamlayamaz ama Stok Girişi/Sayımı'nda eskisi gibi çalışır,
  * çift dokunma ikinci bir satış yazamaz,
  * ödeme başarısız olursa sepet BOZULMAZ,
  * müşteri ekranı satıştan sonra son tutarı atlamaz ve arızası satışı bozmaz.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
)

from app.core.models import OperatingMode, PaymentMethod  # noqa: E402
from app.core.tr import tr_lower  # noqa: E402
from app.payments.base import FailureKind, PaymentResult  # noqa: E402
from app.scanner.scan_event import ScanEvent  # noqa: E402
from app.ui import metrics, theme  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

BIRA = "8690504001492"


from ui_support import *  # noqa: E402,F401,F403
from fakes import SiraliSahteEkran  # noqa: E402


# ===================== Sepet ve miktar denetimleri =======================
def test_tekrarli_okutma_satir_adedini_artirir(sayfa, qapp, bira):
    for _ in range(7):
        sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    assert len(sayfa.cart.lines) == 1, "aynı ürün tek satırda toplanır"
    assert sayfa.cart.item_count == 7
    assert len(sayfa._rows) == 1, "tek dokunmatik satır gereci"
    assert sayfa._rows[bira].qty_label.text() == "7"


def test_arti_dugmesi_adedi_artirir(sayfa, qapp, bira):
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    sayfa._rows[bira].plus_button.click()
    qapp.processEvents()
    assert sayfa.cart.find(bira).quantity == 2
    assert sayfa._rows[bira].qty_label.text() == "2"


def test_eksi_dugmesi_adedi_azaltir(sayfa, qapp, bira):
    for _ in range(3):
        sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    sayfa._rows[bira].minus_button.click()
    qapp.processEvents()
    assert sayfa.cart.find(bira).quantity == 2


def test_bir_adetteyken_eksi_satiri_siler(sayfa, qapp, bira):
    """``Cart.set_quantity`` 0'da satırı kendisi siler; ayrı kural yazılmadı."""
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    sayfa._rows[bira].minus_button.click()
    qapp.processEvents()
    assert sayfa.cart.is_empty
    assert sayfa._rows == {}


def test_carpi_dugmesi_satiri_kaldirir(sayfa, qapp, services, bira, cips_urunu):
    sayfa.handle_scan(ScanEvent(code=BIRA))
    sayfa._add_product(cips_urunu, 1, None, 1)
    qapp.processEvents()
    assert len(sayfa.cart.lines) == 2

    sayfa._rows[bira].remove_button.click()
    qapp.processEvents()
    assert [line.product_id for line in sayfa.cart.lines] == [cips_urunu]


def test_dokunma_hedefleri_yeterince_buyuk(sayfa, qapp, bira):
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    satir = sayfa._rows[bira]

    for dugme in (satir.plus_button, satir.minus_button, satir.remove_button):
        assert dugme.height() >= metrics.TOUCH_TARGET_MIN
        assert dugme.width() >= metrics.TOUCH_TARGET_MIN
    # NOT: boy STIL SAYFASINDAN gelir (QSS min-height, setMinimumHeight'i ezer),
    # bu yuzden minimumSizeHint olculur.
    for dugme in (sayfa.cash_button, sayfa.card_button):
        assert dugme.minimumSizeHint().height() >= metrics.PAYMENT_BUTTON_HEIGHT


# ===================== Tek dokunuş ödeme =================================
def test_nakit_tek_dokunusla_tamamlar(sayfa, qapp, services, bira):
    for _ in range(2):
        sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    sayfa.cash_button.click()
    qapp.processEvents()

    satis = services.sales.last_sale()
    assert satis["payment_method"] == "NAKIT"
    assert satis["total_amount"] == 16000
    assert sayfa.cart.is_empty, "sepet temizlendi"
    assert sayfa._rows == {}


def test_kart_tek_dokunusla_tamamlar(sayfa, qapp, services, bira):
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    sayfa.card_button.click()
    qapp.processEvents()
    assert services.sales.last_sale()["payment_method"] == "KART"


def test_basaridan_sonra_barkoda_hazir_doner(sayfa, qapp, services, bira):
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    sayfa.cash_button.click()
    qapp.processEvents()

    assert sayfa.cart.is_empty
    assert sayfa.barcode.text() == ""
    # Yeni okutma ANINDA çalışmalı.
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    assert sayfa.cart.item_count == 1


def test_cift_dokunma_tek_satis_yazar(sayfa, qapp, services, bira):
    """Dokunmatikte çift dokunma gerçek bir risktir."""
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    sayfa.cash_button.click()
    sayfa.cash_button.click()
    sayfa.complete(PaymentMethod.CASH)       # üçüncü deneme, doğrudan
    qapp.processEvents()

    assert services.db.scalar(
        "SELECT COUNT(*) FROM sales WHERE entry_type = 'SALE'"
    ) == 1
    assert services.products.get(bira)["current_stock"] == 47


def test_bos_sepet_odeme_yazmaz(sayfa, qapp, services):
    sayfa.cash_button.click()
    sayfa.complete(PaymentMethod.CARD)
    qapp.processEvents()
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0


def test_odeme_reddedilince_sepet_AYNEN_durur(sayfa, qapp, window, services, bira):
    class RedAdaptor:
        name = "red"
        supports_void = False

        def authorize(self, request):
            return PaymentResult(
                approved=False, method=request.method, amount=request.amount,
                message="Kart reddedildi.", failure_kind=FailureKind.DECLINED,
            )

        def void(self, reference):            # pragma: no cover
            raise RuntimeError("olmaz")

    services.payments.register(PaymentMethod.CARD, RedAdaptor())

    for _ in range(3):
        sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    sayfa.card_button.click()
    qapp.processEvents()

    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0
    assert sayfa.cart.item_count == 3, "sepet bozulmadı"
    assert services.products.get(bira)["current_stock"] == 48
    assert "reddedildi" in sayfa.banner.headline.text()
    assert window.router.mode.name == "ACTIVE", "okutma yeniden açıldı"
    assert sayfa.cash_button.isEnabled() and sayfa.card_button.isEnabled()


def test_adaptor_patlarsa_satis_olusmaz(sayfa, qapp, window, services, bira):
    class PatlayanAdaptor:
        name = "patlak"
        supports_void = False

        def authorize(self, request):
            raise RuntimeError("terminal kablosu çıktı")

        def void(self, reference):            # pragma: no cover
            raise RuntimeError("olmaz")

    services.payments.register(PaymentMethod.CASH, PatlayanAdaptor())

    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    sayfa.cash_button.click()                 # istisna SIZMAMALI
    qapp.processEvents()

    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0
    assert sayfa.cart.item_count == 1
    assert window.router.mode.name == "ACTIVE"


def test_basarida_modal_pencere_acilmaz(sayfa, qapp, bira, monkeypatch):
    cagrildi = {"sayi": 0}
    monkeypatch.setattr(
        QMessageBox, "exec",
        lambda self: cagrildi.__setitem__("sayi", cagrildi["sayi"] + 1),
    )
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    sayfa.cash_button.click()
    qapp.processEvents()
    assert cagrildi["sayi"] == 0


# ===================== F10 Sepetli Satış'ı tamamlamaz ====================
def test_f10_sepetli_satisi_TAMAMLAMAZ(sayfa, qapp, window, services, bira):
    """Klavyesiz POS: satış yalnızca açık NAKİT/KART eylemiyle oluşur."""
    for _ in range(2):
        sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    window._complete_current()                # F10
    qapp.processEvents()

    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0
    assert sayfa.cart.item_count == 2, "sepet değişmedi"
    assert services.products.get(bira)["current_stock"] == 48


def test_sepet_ekraninda_F10_yazmaz(sayfa, qapp, bira):
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    gerecler = sayfa.findChildren(QAbstractButton) + sayfa.findChildren(QLabel)
    for gerec in gerecler:
        assert "F10" not in (gerec.text() or ""), f"F10 ipucu: {gerec.text()}"


def test_varsayilan_guvenli_taraftadir(sayfa):
    """Yeni bir sayfa ``complete()`` eklerse F10'u KAZARA devralmamalı."""
    from app.ui.pages.base import Page

    assert Page.completes_with_shortcut is False
    assert sayfa.completes_with_shortcut is False


def test_f10_stok_girisini_tamamlar(window, qapp, services, bira, monkeypatch):
    """Gerileme koruması: POS dışı akışlarda F10 eskisi gibi çalışır."""
    from app.ui.pages import stock_entry as stok_modul

    # Onay penceresi testte daima False doner; gercek yolu sinamak icin
    # acikca "evet" dedirtilir.
    monkeypatch.setattr(stok_modul, "ask_confirm", lambda *a, **k: True)

    # ONCE ekrana gidilir: on_activated taslak kurtarma sorar ve testte
    # "Taslagi Sil" sayildigi icin onceden olusturulan fisi SILERDI.
    window.go_to("stok_girisi")
    stok = window.pages["stok_girisi"]
    qapp.processEvents()

    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 24, unit_cost=5000)
    stok.receipt_id = fis

    assert stok.completes_with_shortcut is True
    window._complete_current()                # F10
    qapp.processEvents()

    assert services.purchases.receipt(fis)["status"] == "COMMITTED"
    assert services.products.get(bira)["current_stock"] == 72


def test_f10_stok_sayimini_bitirir(window, qapp, services, bira, monkeypatch):
    from app.ui.pages import stock_count as sayim_modul

    monkeypatch.setattr(sayim_modul, "ask_confirm", lambda *a, **k: True)

    oturum = services.counts.start([1])        # Bira Dolabı
    services.counts.set_counted(oturum, bira, 1, 40)

    window.go_to("stok_sayimi")
    sayim = window.pages["stok_sayimi"]
    sayim.session_id = oturum
    qapp.processEvents()

    assert sayim.completes_with_shortcut is True
    window._complete_current()                # F10
    qapp.processEvents()

    assert services.counts.open_session() is None
    assert services.products.get(bira)["current_stock"] == 40


# ===================== Stok uyarıları kipe bağlı =========================
def test_sales_first_satista_stok_uyarisi_gostermez(sayfa, qapp, services, bira):
    """Stoksuz satış normaldir; kasada her satışta uyarı çıkmaz."""
    for _ in range(60):                        # stok 48 → eksiye düşer
        sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    sayfa.cash_button.click()
    qapp.processEvents()

    assert services.products.get(bira)["current_stock"] == -12
    assert "stok" not in tr_lower(sayfa.flash.line.text())


def test_inventory_tracked_satista_stok_uyarisi_gosterir(
    window, qapp, services, bira
):
    services.settings.set("operating_mode", OperatingMode.INVENTORY_TRACKED)
    window.go_to("sepetli_satis")
    qapp.processEvents()
    sayfa = window.pages["sepetli_satis"]

    for _ in range(60):
        sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    sayfa.cash_button.click()
    qapp.processEvents()

    assert "stok" in tr_lower(sayfa.flash.line.text())


# ===================== Müşteri ekranı sıralaması =========================



def test_ekran_son_tutari_ATLAMAZ(sayfa, qapp, services, bira):
    """``checkout`` sepeti boşaltır; ekran yine de son tutarı göstermeli."""
    sahte = SiraliSahteEkran()
    services.display.set_display(sahte)

    for _ in range(2):
        sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    assert sahte.cagrilar[-1] == ("total", 16000)

    sayfa.cash_button.click()
    qapp.processEvents()

    # Tamamlama sepeti bosaltir; ekran yine de son tutarda KALMALI.
    assert ("idle", None) not in sahte.cagrilar, (
        "tamamlama sırasında ekran 0.00'a DÜŞMEDİ"
    )
    assert ("total", 0) not in sahte.cagrilar
    assert sahte.cagrilar[-1] == ("total", 16000), "son tutar ekranda kaldı"

    sayfa._release_display_hold()              # bekletme süresi doldu
    assert sahte.cagrilar[-1] == ("idle", None), "ancak ŞİMDİ 0.00"


def test_sepet_degisince_ekran_guncellenir(sayfa, qapp, services, bira):
    sahte = SiraliSahteEkran()
    services.display.set_display(sahte)

    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    assert ("total", 8000) in sahte.cagrilar

    sayfa._rows[bira].plus_button.click()
    qapp.processEvents()
    assert ("total", 16000) in sahte.cagrilar


def test_bozuk_ekran_satisi_ENGELLEMEZ(sayfa, qapp, services, bira):
    class PatlayanEkran:
        def show_total(self, kurus):
            raise OSError("COM portu yok")

        def show_idle(self):
            raise OSError("COM portu yok")

        def close(self):
            pass

    services.display.set_display(PatlayanEkran())
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    sayfa.cash_button.click()
    qapp.processEvents()

    assert services.sales.last_sale()["payment_method"] == "NAKIT"
    assert sayfa.cart.is_empty


def test_basari_yolu_patlasa_bile_ekran_BEKLETMESI_cozulur(
    sayfa, qapp, services, bira, monkeypatch
):
    """Satış yazıldıktan SONRAKİ bir arayüz hatası ekranı donduramaz.

    ``_display_hold`` True kalsaydı ``_publish_display()`` kalıcı olarak susar
    ve müşteri ekranı o tutarda sonsuza dek takılırdı. Bu yüzden bekletmeyi
    çözen zamanlayıcı, kırılabilir arayüz adımlarından ÖNCE kurulur.
    """
    services.settings.set("customer_display_hold_ms", "0")   # hemen çözülsün
    sahte = SiraliSahteEkran()
    services.display.set_display(sahte)

    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    def patla(*args, **kwargs):
        raise RuntimeError("şerit çizilemedi")

    monkeypatch.setattr(sayfa.flash, "flash", patla)

    with pytest.raises(RuntimeError):
        sayfa.complete(PaymentMethod.CASH)

    assert services.sales.last_sale() is not None, "satış YAZILDI"
    assert sayfa.cart.is_empty
    assert sayfa._checkout_busy is False

    qapp.processEvents()                     # bekletme zamanlayıcısı ateşlenir
    assert sayfa._display_hold is False, "bekletme bayrağı takılı KALMADI"
    assert sahte.cagrilar[-1] == ("idle", None), "ekran 0.00'a döndü"


def test_commit_patlarsa_sepet_KORUNUR(
    sayfa, qapp, window, services, bira, monkeypatch
):
    """Ödeme onaylandı ama satış YAZILAMADI: hiçbir şey yarım kalmaz."""
    def patla(*args, **kwargs):
        raise RuntimeError("disk dolu")

    monkeypatch.setattr(services.cart, "checkout", patla)

    for _ in range(2):
        sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    sayfa.cash_button.click()
    qapp.processEvents()

    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0, "satış yok"
    assert sayfa.cart.item_count == 2, "sepet olduğu gibi duruyor"
    assert services.products.get(bira)["current_stock"] == 48
    assert window.router.mode.name == "ACTIVE", "okutma yeniden açıldı"
    assert sayfa.cash_button.isEnabled() and sayfa.card_button.isEnabled()
    assert sayfa._checkout_busy is False
    assert sayfa._display_hold is False, "bekletme bayrağı çözüldü"
    assert "kaydedilemedi" in tr_lower(sayfa.banner.headline.text())


# ===================== Geri alma güvenliği ===============================
def test_sepet_doluyken_geri_alma_KAPALI(sayfa, qapp, window, services, bira):
    """Yarım sepet varken ÖNCEKİ müşterinin satışı kazara iptal edilemez."""
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    sayfa.cash_button.click()                # 1. müşteri bitti
    qapp.processEvents()
    satis_id = services.sales.last_sale()["id"]

    sayfa.handle_scan(ScanEvent(code=BIRA))  # 2. müşteri okutulmaya başlandı
    qapp.processEvents()

    assert not sayfa.undo_button.isEnabled(), "düğme kapalı"

    # F8 düğmeyi ATLAR (main_window._undo_last doğrudan metodu çağırır),
    # bu yüzden asıl kapı undo_last() içindedir.
    window._undo_last()
    qapp.processEvents()

    assert services.sales.sale(satis_id)["is_reversed"] == 0, (
        "önceki müşterinin satışı geri ALINMADI"
    )
    assert sayfa.cart.item_count == 1, "eldeki sepet bozulmadı"
    assert services.products.get(bira)["current_stock"] == 47
    assert "geri alma kapalı" in tr_lower(sayfa.banner.headline.text())


def test_sepet_bosalinca_geri_alma_ACILIR(
    sayfa, qapp, window, services, bira, monkeypatch
):
    """Kapı yalnızca dolu sepette iner: boş sepette geri alma ÇALIŞIR."""
    from app.ui.pages import cart_sale as modul

    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    sayfa.cash_button.click()
    qapp.processEvents()
    satis_id = services.sales.last_sale()["id"]
    assert services.products.get(bira)["current_stock"] == 47

    assert sayfa.undo_button.isEnabled(), "sepet boş: geri alma açık"
    monkeypatch.setattr(modul, "ask_confirm", lambda *a, **k: True)

    window._undo_last()                      # F8 yolu
    qapp.processEvents()

    assert services.sales.sale(satis_id)["is_reversed"] == 1
    assert services.products.get(bira)["current_stock"] == 48, "stok iade edildi"


# ===================== Panel kipe bağlı ==================================
def test_sales_first_panelinde_kar_GOSTERILMEZ(window, qapp, services, bira):
    """Stoksuz satış serbest olduğu için maliyet tahminidir; kesin kâr yanıltır."""
    sayfa = window.pages["sepetli_satis"]
    sayfa.handle_scan(ScanEvent(code=BIRA))
    sayfa.cash_button.click()
    qapp.processEvents()

    window.go_to("panel")
    qapp.processEvents()
    panel = window.pages["panel"]

    assert not panel.profit_card.isVisible(), "SALES_FIRST'te brüt kâr yok"
    assert not panel.stock_card.isVisible()
    assert not panel.attention_card.isVisible(), "stok uyarıları panelde yok"
    assert not panel.slow_card.isVisible()
    assert panel.payment_card.isVisible()
    assert panel.customers_card.isVisible()
    assert panel.avg_card.isVisible()


def test_inventory_tracked_panelinde_kar_gorunur(window, qapp, services, bira):
    services.settings.set("operating_mode", OperatingMode.INVENTORY_TRACKED)
    window.go_to("panel")
    qapp.processEvents()
    panel = window.pages["panel"]

    assert panel.profit_card.isVisible()
    assert panel.stock_card.isVisible()
    assert panel.attention_card.isVisible()
    assert not panel.payment_card.isVisible()


def test_panelde_kaydedilmemis_ayri_gosterilir(window, qapp, services, bira):
    """Ödeme seçimi öncesi satışlar nakit/kart sayılmaz."""
    services.sales.quick_sale(bira)            # payment_method NULL
    window.go_to("panel")
    qapp.processEvents()

    gun = services.settings.calendar().today()
    kovalar = services.analytics.payment_breakdown(gun, gun).buckets()
    assert [ad for ad, _, _ in kovalar] == ["Kaydedilmemiş"]
