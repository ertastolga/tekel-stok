"""SALES_FIRST kipi, ödeme adaptörleri ve müşteri ekranı — servis düzeyi.

Bu modülün koruduğu sözler:
  * kip YALNIZCA sunumu etkiler; stoksuz satış zaten serbesttir ve öyle kalır,
  * hiçbir ödeme adaptörü istisnası dışarı sızmaz,
  * ödeme onayı veritabanı commit'inden ÖNCE alınır,
  * ödeme kovaları çıkarma ile değil, AÇIKÇA sayılır,
  * müşteri ekranı arızası bir satışı asla bozamaz.
"""
from __future__ import annotations

import pytest

from app.core.models import OperatingMode, PaymentMethod
from app.hardware.customer_display import (
    CustomerDisplayService,
    NullCustomerDisplay,
    SerialCustomerDisplay,
)
from app.payments.base import FailureKind, PaymentRequest, PaymentResult
from app.payments.service import PaymentService
from app.services.cart_service import Cart
from fakes import PatlayanAdaptor, RedAdaptor, SahteEkran, ZamanAsimiAdaptor  # noqa: E402

BIRA = "8690504001492"


# ===================== Çalışma kipi ======================================
def test_varsayilan_kip_sales_first(services):
    assert services.settings.operating_mode() == OperatingMode.SALES_FIRST
    assert services.settings.is_sales_first() is True


def test_kip_degistirilebilir(services):
    services.settings.set("operating_mode", OperatingMode.INVENTORY_TRACKED)
    assert services.settings.operating_mode() == OperatingMode.INVENTORY_TRACKED
    assert services.settings.is_sales_first() is False


def test_tanimsiz_kip_guvenli_varsayilana_duser(services):
    services.settings.set("operating_mode", "SAÇMA_DEĞER")
    assert services.settings.operating_mode() == OperatingMode.SALES_FIRST


def test_kip_eski_veritabaninda_kendiliginden_belirir(services, reopen):
    """Göç gerekmez: seed_settings eksik anahtarı ekler."""
    services.db.execute("DELETE FROM settings WHERE key = 'operating_mode'")
    yeni = reopen(services)
    try:
        assert yeni.settings.operating_mode() == OperatingMode.SALES_FIRST
    finally:
        yeni.close()


def test_ekran_bekletme_suresi_sinirlanir(services):
    services.settings.set("customer_display_hold_ms", 999999)
    assert services.settings.customer_display_hold_ms() == 30000
    services.settings.set("customer_display_hold_ms", -5)
    assert services.settings.customer_display_hold_ms() == 0


# ===================== Stoksuz satış (kipten BAĞIMSIZ) ===================
def test_hic_sayilmamis_urun_satilabilir(services):
    """SALES_FIRST'te başlatılmamış stok satışı engellemez."""
    pid = services.products.quick_create("Sayılmamış", 5000, initial_stock=None)
    sonuc = services.sales.quick_sale(pid)

    assert sonuc.total_amount == 5000
    assert services.products.get(pid)["current_stock"] == -1
    assert services.db.check_invariants(deep=True) == []


def test_sifir_stokta_satis(services, bira):
    assert services.products.get(bira)["current_stock"] == 0
    sonuc = services.sales.quick_sale(bira)
    assert sonuc.total_amount == 8000
    assert services.products.get(bira)["current_stock"] == -1


def test_negatif_stokta_tekrarli_satis_engellenmez(services, bira):
    for _ in range(10):
        services.sales.quick_sale(bira)

    assert services.products.get(bira)["current_stock"] == -10
    assert services.db.scalar(
        "SELECT COUNT(*) FROM sales WHERE entry_type = 'SALE'"
    ) == 10
    assert services.products.get(bira)["stock_value"] == 0
    assert services.db.check_invariants(deep=True) == []


def test_servis_katmani_kipten_habersizdir(services, bira):
    """Uyarılar HER İKİ kipte de üretilir; gösterip göstermemek arayüzün işi."""
    services.settings.set("operating_mode", OperatingMode.SALES_FIRST)
    sonuc = services.sales.quick_sale(bira)
    assert sonuc.warnings, "servis uyarıyı yine de üretir"

    services.settings.set("operating_mode", OperatingMode.INVENTORY_TRACKED)
    sonuc2 = services.sales.quick_sale(bira)
    assert sonuc2.warnings


# ===================== Ödeme yöntemi yazımı ==============================
def _sepet_sat(services, pid, adet=1, yontem=None):
    sepet = Cart()
    services.cart.add_product(sepet, pid, quantity=adet)
    return services.cart.checkout(sepet, payment_method=yontem)


def test_nakit_odeme_kaydedilir(services, bira):
    sonuc = _sepet_sat(services, bira, yontem=PaymentMethod.CASH)
    satis = services.sales.sale(sonuc.sale_id)
    assert satis["payment_method"] == "NAKIT"


def test_kart_odeme_kaydedilir(services, bira):
    sonuc = _sepet_sat(services, bira, yontem=PaymentMethod.CARD)
    satis = services.sales.sale(sonuc.sale_id)
    assert satis["payment_method"] == "KART"


def test_hizli_satis_odemesi_bos_kalir(services, bira):
    """Hızlı Satış akışı değişmez; ödeme sorulmaz, NULL kalır."""
    sonuc = services.sales.quick_sale(bira)
    assert services.sales.sale(sonuc.sale_id)["payment_method"] is None


def test_rollup_nakit_kart_toplamlari(services, bira, cips_urunu):
    _sepet_sat(services, bira, yontem=PaymentMethod.CASH)
    _sepet_sat(services, cips_urunu, yontem=PaymentMethod.CARD)

    gun = services.settings.calendar().today()
    satir = services.db.query_one(
        "SELECT * FROM daily_sales_rollup WHERE business_date = ?", (gun,)
    )
    assert satir["cash_amount"] == 8000
    assert satir["card_amount"] == 5000


def test_geri_alma_dogru_kovadan_duser(services, bira):
    sonuc = _sepet_sat(services, bira, yontem=PaymentMethod.CARD)
    services.sales.reverse_sale(sonuc.sale_id)

    gun = services.settings.calendar().today()
    satir = services.db.query_one(
        "SELECT * FROM daily_sales_rollup WHERE business_date = ?", (gun,)
    )
    assert satir["card_amount"] == 0
    assert satir["cash_amount"] == 0

    # Panelin YETKİLİ kaynağı rollup değil ``sales`` tablosudur: ters kayıt
    # orijinalin ``payment_method``'unu kopyaladığı için kendi kovasından
    # düşer. "Kaydedilmemiş" kovasına SIZMAZ.
    kirilim = services.analytics.payment_breakdown(gun, gun)
    assert kirilim.kart == 0, "ters kayıt KART kovasından düştü"
    assert kirilim.kaydedilmemis == 0, "ters kayıt bilinmiyor kovasına sızmadı"
    assert kirilim.total == 0


# ===================== Ödeme kovaları ====================================
def _ham_satis(services, yontem, tutar):
    """Doğrudan satış satırı yazar (kova sınıflandırmasını sınamak için)."""
    damga = services.settings.calendar().stamp()
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO sales(entry_type, sale_mode, created_at_utc, local_date, "
            "  local_hour, local_dow, business_date, total_amount, item_count, "
            "  payment_method) VALUES('SALE','SEPET',?,?,?,?,?,?,1,?)",
            (damga.created_at_utc, damga.local_date, damga.local_hour,
             damga.local_dow, damga.business_date, tutar, yontem),
        )


def test_her_odeme_kovasi_AYRI_sayilir(services):
    """VERESİYE ve DİĞER, 'Kaydedilmemiş' ile ASLA karışmaz."""
    _ham_satis(services, "NAKIT", 1000)
    _ham_satis(services, "KART", 2000)
    _ham_satis(services, "VERESIYE", 3000)
    _ham_satis(services, "DIGER", 4000)
    _ham_satis(services, None, 5000)

    gun = services.settings.calendar().today()
    kirilim = services.analytics.payment_breakdown(gun, gun)

    assert kirilim.nakit == 1000
    assert kirilim.kart == 2000
    assert kirilim.veresiye == 3000
    assert kirilim.diger == 4000
    assert kirilim.kaydedilmemis == 5000, "NULL yalnızca kendi kovasında"
    assert kirilim.total == 15000


def test_kalan_tutar_cikarmayla_bulunmaz(services):
    """Eski 'toplam − nakit − kart' yaklaşımı VERESİYE'yi yanlış etiketlerdi."""
    _ham_satis(services, "VERESIYE", 3000)
    gun = services.settings.calendar().today()
    kirilim = services.analytics.payment_breakdown(gun, gun)

    assert kirilim.veresiye == 3000
    assert kirilim.kaydedilmemis == 0, "veresiye bilinmiyor sayılmadı"


def test_kova_etiketleri_ve_yuzdeleri(services):
    _ham_satis(services, "NAKIT", 7500)
    _ham_satis(services, "KART", 2500)
    gun = services.settings.calendar().today()
    kovalar = services.analytics.payment_breakdown(gun, gun).buckets()

    assert [(ad, tutar) for ad, tutar, _ in kovalar] == [("Nakit", 7500), ("Kart", 2500)]
    assert kovalar[0][2] == 75.0
    assert kovalar[1][2] == 25.0


def test_bos_kovalar_gosterilmez(services):
    _ham_satis(services, "NAKIT", 1000)
    gun = services.settings.calendar().today()
    kovalar = services.analytics.payment_breakdown(gun, gun).buckets()
    assert [ad for ad, _, _ in kovalar] == ["Nakit"]


def test_eski_null_satirlar_kaydedilmemis_kalir(services, bira):
    """Ödeme seçimi öncesi yazılmış satışlar asla nakit/kart sayılmaz."""
    services.sales.quick_sale(bira)          # payment_method NULL
    gun = services.settings.calendar().today()
    kirilim = services.analytics.payment_breakdown(gun, gun)

    assert kirilim.kaydedilmemis == 8000
    assert kirilim.nakit == 0 and kirilim.kart == 0


# ===================== Sepet özeti ======================================
def test_sepet_ozeti_yalnizca_sepetli_satisi_sayar(services, bira, cips_urunu):
    services.sales.quick_sale(bira)                              # HIZLI — sayılmaz
    _sepet_sat(services, bira, adet=2, yontem=PaymentMethod.CASH)
    _sepet_sat(services, cips_urunu, adet=4, yontem=PaymentMethod.CASH)

    gun = services.settings.calendar().today()
    ozet = services.analytics.basket_summary(gun, gun)

    assert ozet.basket_count == 2
    assert ozet.item_count == 6
    assert ozet.revenue == 2 * 8000 + 4 * 5000
    assert ozet.avg_basket_value == 18000
    assert ozet.avg_items_per_basket == 3.0


def test_geri_alinan_sepet_ortalamaya_girmez(services, bira):
    sonuc = _sepet_sat(services, bira, yontem=PaymentMethod.CASH)
    services.sales.reverse_sale(sonuc.sale_id)

    gun = services.settings.calendar().today()
    assert services.analytics.basket_summary(gun, gun).basket_count == 0


def test_bos_gunde_ortalama_sifirdir(services):
    gun = services.settings.calendar().today()
    ozet = services.analytics.basket_summary(gun, gun)
    assert (ozet.avg_basket_value, ozet.avg_items_per_basket) == (0, 0.0)


def test_kesin_sepetler_yalnizca_sepetli_satistan_gelir(services, bira, cips_urunu):
    services.sales.quick_sale(bira)                              # TAHMİNİ — girmez
    sepet = Cart()
    services.cart.add_product(sepet, bira)
    services.cart.add_product(sepet, cips_urunu)
    services.cart.checkout(sepet, payment_method=PaymentMethod.CASH)

    gun = services.settings.calendar().today()
    sepetler = services.analytics.exact_baskets(gun, gun)

    assert len(sepetler) == 1
    _, urunler = sepetler[0]
    assert sorted(urunler) == sorted([bira, cips_urunu])


def test_sales_first_paneli_kar_dondurmez(services, bira):
    _sepet_sat(services, bira, yontem=PaymentMethod.CASH)
    panel = services.analytics.sales_first_dashboard()

    assert panel.revenue == 8000
    assert panel.basket.basket_count == 1
    assert panel.payments.nakit == 8000
    assert not hasattr(panel, "cost")
    assert not hasattr(panel, "gross_profit")


def test_karsilastirma_uc_donem_doner(services):
    kiyas = services.analytics.comparison()
    assert [ad for ad, _ in kiyas] == ["Bugün", "Dün", "Geçen hafta aynı gün"]


# ===================== Ödeme adaptörü ====================================
def test_manuel_adaptorler_aninda_onaylar():
    servis = PaymentService()
    for yontem in (PaymentMethod.CASH, PaymentMethod.CARD):
        sonuc = servis.authorize(yontem, 12345)
        assert sonuc.approved is True
        assert sonuc.method == yontem
        assert sonuc.amount == 12345


def test_adaptor_istisnasi_disari_SIZMAZ():
    servis = PaymentService()
    servis.register(PaymentMethod.CARD, PatlayanAdaptor())

    sonuc = servis.authorize(PaymentMethod.CARD, 5000)   # istisna fırlatmamalı

    assert sonuc.approved is False
    assert sonuc.failure_kind == FailureKind.DEVICE_ERROR
    assert sonuc.message and "Ödeme" in sonuc.message
    assert "RuntimeError" not in sonuc.message, "teknik ayrıntı kullanıcıya gitmez"


def test_zaman_asimi_denetimli_basarisizliga_cevrilir():
    servis = PaymentService()
    servis.register(PaymentMethod.CARD, ZamanAsimiAdaptor())
    sonuc = servis.authorize(PaymentMethod.CARD, 5000)

    assert sonuc.approved is False
    assert sonuc.failure_kind == FailureKind.TIMEOUT


def test_red_edilen_odeme_mesajiyla_doner():
    servis = PaymentService()
    servis.register(PaymentMethod.CARD, RedAdaptor())
    sonuc = servis.authorize(PaymentMethod.CARD, 5000)

    assert sonuc.approved is False
    assert sonuc.failure_kind == FailureKind.DECLINED
    assert sonuc.message == "Kart reddedildi."


def test_tanimsiz_yontem_reddedilir():
    sonuc = PaymentService().authorize("BITCOIN", 100)
    assert sonuc.approved is False
    assert sonuc.failure_kind == FailureKind.NOT_SUPPORTED


def test_void_kancasi_vardir_ama_manuelde_desteklenmez():
    """Gelecekteki telafi akışının yeri HAZIR; V1.1'de uygulanmaz."""
    servis = PaymentService()
    assert servis.supports_void(PaymentMethod.CASH) is False
    assert servis.supports_void(PaymentMethod.CARD) is False

    sonuc = servis.void(PaymentMethod.CARD, "REF-1")
    assert sonuc.approved is False
    assert sonuc.failure_kind == FailureKind.NOT_SUPPORTED


def test_odeme_onayi_commit_ten_ONCE_alinir(services, bira):
    """Terminal beklerken SQLite işlemi açık kalmamalı.

    Sahte adaptör çağrıldığı anda ``sales`` tablosu HÂLÂ BOŞ olmalıdır.
    """
    goruldu = {}

    class GozetleyenAdaptor:
        name = "gozetleyen"
        supports_void = False

        def authorize(self, request):
            goruldu["satis_sayisi"] = services.db.scalar(
                "SELECT COUNT(*) FROM sales", default=0
            )
            return PaymentResult(True, request.method, request.amount)

        def void(self, reference):  # pragma: no cover
            raise RuntimeError("olmaz")

    services.payments.register(PaymentMethod.CASH, GozetleyenAdaptor())

    sepet = Cart()
    services.cart.add_product(sepet, bira)
    odeme = services.payments.authorize(PaymentMethod.CASH, sepet.total)
    assert odeme.approved
    services.cart.checkout(sepet, payment_method=PaymentMethod.CASH)

    assert goruldu["satis_sayisi"] == 0, "ödeme anında henüz satış YAZILMAMIŞTI"
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 1


# ===================== Müşteri ekranı ====================================
def test_null_ekran_sessizdir():
    ekran = CustomerDisplayService(NullCustomerDisplay())
    ekran.show_total(1000)
    ekran.show_idle()
    ekran.close()          # hiçbir istisna yok


def test_ekran_hatasi_YUTULUR():
    ekran = CustomerDisplayService(SahteEkran(patlasin=True))
    ekran.show_total(1000)     # istisna fırlatmamalı
    ekran.show_idle()
    ekran.close()


def test_ayni_tutar_tekrar_gonderilmez():
    sahte = SahteEkran()
    ekran = CustomerDisplayService(sahte)
    ekran.show_total(1000)
    ekran.show_total(1000)
    ekran.show_total(2000)
    assert sahte.cagrilar == [("total", 1000), ("total", 2000)]


def test_basarisiz_yazma_ONBELLEGI_kirletmez():
    """Yazma patlarsa "gösterildi" SANILMAZ; cihaz düzelince aynı tutar gider.

    Önbellek başarısız yazmadan sonra da güncellenseydi, kablosu çıkmış bir
    ekrana yazmak sessizce başarısız olur, servis o tutarı "ekranda" sayar ve
    kablo takıldığında aynı tutar bir daha HİÇ gönderilmezdi — müşteri işlem
    boyunca boş ekrana bakardı.
    """
    sahte = SahteEkran(patlasin=True)
    ekran = CustomerDisplayService(sahte)

    ekran.show_total(1000)                   # kablo çıkık: yazma patlar
    assert sahte.cagrilar == [("total", 1000)]

    sahte.patlasin = False                   # kablo takıldı
    ekran.show_total(1000)                   # AYNI tutar yeniden denenmeli
    assert sahte.cagrilar == [("total", 1000), ("total", 1000)], (
        "başarısız yazma önbelleği kirletti: tutar bir daha gönderilmedi"
    )

    ekran.show_total(1000)                   # artık gerçekten gösteriliyor
    assert len(sahte.cagrilar) == 2, "başarılı yazmadan sonra tekrarlanmaz"


def test_basarisiz_sifirlama_da_ONBELLEGI_kirletmez():
    """Aynı güvence ``show_idle()`` için de geçerlidir."""
    sahte = SahteEkran()
    ekran = CustomerDisplayService(sahte)
    ekran.show_total(1000)

    sahte.patlasin = True
    ekran.show_idle()                        # patlar
    sahte.patlasin = False
    ekran.show_idle()                        # yeniden denenebilmeli
    assert sahte.cagrilar == [
        ("total", 1000), ("idle", None), ("idle", None)
    ]
    ekran.show_idle()                        # artık 0.00 gerçekten ekranda
    assert len(sahte.cagrilar) == 3


def test_seri_ekran_tahmin_yurutmez():
    """Protokol doğrulanmadan seri komut gönderilmez."""
    ekran = SerialCustomerDisplay(port="COM3")
    with pytest.raises(NotImplementedError):
        ekran.show_total(1000)
    with pytest.raises(NotImplementedError):
        ekran.show_idle()


def test_bozuk_ekran_satisi_ETKILEMEZ(services, bira):
    """En kritik söz: ekran arızası satışı bozamaz."""
    services.display.set_display(SahteEkran(patlasin=True))

    sepet = Cart()
    services.cart.add_product(sepet, bira, quantity=3)
    services.display.show_total(sepet.total)          # patlar ama yutulur

    sonuc = services.cart.checkout(sepet, payment_method=PaymentMethod.CASH)
    services.display.show_total(sonuc.total_amount)
    services.display.show_idle()

    assert sonuc.item_count == 3
    assert services.products.get(bira)["current_stock"] == -3
    assert sepet.is_empty
    assert services.db.check_invariants(deep=True) == []
