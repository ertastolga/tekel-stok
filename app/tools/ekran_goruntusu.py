"""Ekran görüntüsü aracı (V1.2 M12b, plan §7): her ana sayfanın GERÇEK çizimi.

Görsel inceleme için bir örnek dükkân verisiyle uygulamayı açar ve her ana
sayfayı (Kasa durumları, katmanlar ve pencereler dahil) belirlenen
çözünürlüklerde PNG olarak kaydeder.

Güvenlik (plan §2):
  * ``TEKEL_DATA_DIR`` doğrulanmış bir karalama klasörü olmalıdır; gerçek veri
    klasörüyle çalışmayı REDDEDER (``veri_guvenligi``). Örnek veri bu
    klasörde üretilir; başka hiçbir veriye dokunulmaz.
  * Pencere ekranda GÖSTERİLMEZ (``WA_DontShowOnScreen``); sesler kapalıdır,
    saat sabittir (``ORNEK_AN``), modal pencereler beklemez.

Çizim Windows'un gerçek platform eklentisiyle yapılır (offscreen eklentisi bu
makinede yazı tiplerini çizemez). Her ölçek ayrı süreçte çalışır: Qt ölçek
çarpanı ``QApplication`` kurulmadan önce belirlenmelidir.

Kullanım::

    set TEKEL_DATA_DIR=C:\\karalama\\ekran
    python -m app.tools.ekran_goruntusu --cikti C:\\karalama\\ekran\\png
    python -m app.tools.ekran_goruntusu --cikti ... --profil 1366x768
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

#: Örnek verinin "şimdi"si: ekran görüntüleri her çalıştırmada aynıdır.
ORNEK_AN = datetime(2026, 10, 8, 19, 5)
ORNEK_GUN_SAYISI = 14


@dataclass(frozen=True)
class Profil:
    """Pencerenin İSTEMCİ alanı (mantıksal piksel) ve görünüm."""

    genislik: int
    yukseklik: int
    olcek: float = 1.0
    tema: str = "LIGHT"
    yazi: int = 100
    aciklama: str = ""


#: Ekranı kaplayan pencere (görev çubuğu 48 + başlık 30 piksel düşülmüş).
PROFILLER: dict[str, Profil] = {
    "1000x600": Profil(1000, 600, aciklama="En küçük desteklenen pencere"),
    "1092x614_125": Profil(1092, 614, 1.25,
                           aciklama="1366×768 ekran, %125 ölçek (mantıksal 1092×614)"),
    "1366x768": Profil(1366, 690, aciklama="1366×768 ekran, ekranı kaplayan pencere"),
    "1536x864_125": Profil(1536, 786, 1.25,
                           aciklama="1920×1080 ekran, %125 ölçek (15,6\" AVAPOS olası)"),
    "1920x1080": Profil(1920, 1002, aciklama="1920×1080 ekran, %100"),
    "1366x768_koyu": Profil(1366, 690, tema="DARK", aciklama="Koyu tema"),
    "1366x768_yazi130": Profil(1366, 690, yazi=130, aciklama="Yazı ölçeği %130"),
}


# ===================== Örnek dükkân =======================================
#: (ad, fiyat TL, alt kategori, marka, stok, alış TL)
URUNLER = [
    ("Efes Pilsen 50 cl Kutu", 65, "Bira", "Efes", 96, 48),
    ("Tuborg Gold 50 cl Kutu", 70, "Bira", "Tuborg", 72, 52),
    ("Bomonti Filtresiz 50 cl Kutu", 75, "Bira", "Bomonti", 40, 55),
    ("Carlsberg 33 cl Şişe", 60, "Bira", "Carlsberg", 24, 43),
    ("Efes Malt 50 cl Kutu", 68, "Bira", "Efes", 3, 50),
    ("Yeni Rakı 70 cl", 1150, "Rakı", "Yeni Rakı", 12, 920),
    ("Tekirdağ Altın Seri 70 cl", 1350, "Rakı", "Tekirdağ", 6, 1080),
    ("Beylerbeyi Göbek 70 cl", 1450, "Rakı", "Beylerbeyi", 4, 1160),
    ("Johnnie Walker Red Label 70 cl", 1650, "Viski", "Johnnie Walker", 5, 1320),
    ("Jack Daniel's Old No.7 70 cl", 2100, "Viski", "Jack Daniel's", 3, 1690),
    ("Jack Daniel's Tennessee Honey Likörlü Viski 70 cl Hediye Kutulu", 2350, "Viski",
     "Jack Daniel's", 2, 1880),
    ("Chivas Regal 12 Yıl 70 cl", 2600, "Viski", "Chivas", 2, 2080),
    ("Absolut Vodka 70 cl", 1300, "Votka", "Absolut", 6, 1040),
    ("İstanblue Votka 70 cl", 690, "Votka", "İstanblue", 8, 550),
    ("Kavaklıdere Yakut 75 cl", 420, "Şarap", "Kavaklıdere", 10, 330),
    ("Doluca DLC Öküzgözü 75 cl", 560, "Şarap", "Doluca", 6, 440),
    ("Gordon's London Dry Gin 70 cl", 1100, "Cin", "Gordon's", 4, 880),
    ("Baileys Original 70 cl", 1250, "Likör", "Baileys", 3, 1000),
    ("Marlboro Touch Blue", 100, "Sigara", "Marlboro", 60, 92),
    ("Parliament Night Blue", 105, "Sigara", "Parliament", 50, 97),
    ("Camel Yellow", 95, "Sigara", "Camel", 40, 87),
    ("Winston Slender Blue", 92, "Sigara", "Winston", 0, 85),
    ("Café Crème Original 10'lu", 210, "Puro / Sigarillo", "Café Crème", 6, 170),
    ("Golden Virginia Sarmalık Tütün 30 g", 180, "Tütün", "Golden Virginia", 8, 145),
    ("OCB Sigara Kağıdı", 25, "Tütün Aksesuarı", "OCB", 30, 15),
    ("Coca-Cola 1 L", 45, "Kola", "Coca-Cola", 36, 30),
    ("Coca-Cola Zero 330 ml Kutu", 30, "Kola", "Coca-Cola", 48, 19),
    ("Pepsi 1 L", 40, "Kola", "Pepsi", 24, 27),
    ("Uludağ Gazoz 250 ml", 20, "Gazoz", "Uludağ", 24, 12),
    ("Red Bull 250 ml", 65, "Enerji İçeceği", "Red Bull", 30, 46),
    ("Monster Energy 500 ml", 75, "Enerji İçeceği", "Monster", 2, 53),
    ("Cappy Vişne 1 L", 50, "Meyve Suyu", "Cappy", 12, 34),
    ("Erikli Su 0,5 L", 10, "Su", "Erikli", 120, 5),
    ("Hayat Su 1,5 L", 15, "Su", "Hayat", 48, 8),
    ("Beypazarı Maden Suyu 200 ml", 12, "Soda", "Beypazarı", 60, 7),
    ("Lay's Klasik 107 g", 45, "Cips", "Lay's", 20, 31),
    ("Doritos Nacho 113 g", 50, "Cips", "Doritos", 14, 35),
    ("Ruffles Original 107 g", 45, "Cips", "Ruffles", 0, 31),
    ("Peyman Bahçeden Karışık Kuruyemiş 140 g", 120, "Kuruyemiş", "Peyman", 10, 85),
    ("Ülker Çikolatalı Gofret 36 g", 15, "Çikolata", "Ülker", 48, 9),
    ("Milka Sütlü Çikolata 80 g", 55, "Çikolata", "Milka", 18, 38),
    ("Snickers 50 g", 30, "Çikolata", "Snickers", 24, 20),
    ("Eti Burçak 131 g", 25, "Bisküvi", "Eti", 20, 16),
    ("Ülker Krakerim 100 g", 18, "Kraker", "Ülker", 15, 11),
    ("Haribo Altın Ayıcık 80 g", 35, "Şekerleme", "Haribo", 16, 24),
    ("First Sensations Nane 27 g", 20, "Sakız", "First", 30, 13),
    ("BIC Maxi Çakmak", 35, "Çakmak", "BIC", 40, 22),
    ("Duracell AA Pil 4'lü", 160, "Pil", "Duracell", 8, 115),
    ("Kristal Buz 2 kg", 40, "Buz", "Kristal", 0, 20),
]
TEDARIKCILER = ["Efes Dağıtım", "Mey Diageo Bayi", "Philip Morris Bayi",
                "Coca-Cola İçecek", "Atıştırmalık Toptan"]
#: Ekranda okutulan barkodlar (indeks → URUNLER sırası).
BARKOD = {i: None for i in range(len(URUNLER))}


def _ean13(govde12: str) -> str:
    toplam = sum(int(r) * (3 if i % 2 else 1) for i, r in enumerate(govde12))
    return govde12 + str((10 - toplam % 10) % 10)


def barkod(i: int) -> str:
    return _ean13(f"8690{i + 1:08d}")


class _Saat:
    def __init__(self, an: datetime) -> None:
        self.an = an

    def __call__(self) -> datetime:
        return self.an

    def tekduze(self) -> float:
        return self.an.timestamp()


def ornek_dukkan(yol: Path) -> Path:
    """Gerçekçi bir tekel bayii: ~50 ürün, 14 günlük satış, alış, sayım,
    fiyat değişikliği, geri alma ve bekleyen sepet. Belirlenimci."""
    from app.core import clock
    from app.core.db import open_database
    from app.core.models import PaymentMethod
    from app.services.cart_service import Cart
    from app.services.container import build_services

    yol.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261008)
    ilk_gun = (ORNEK_AN - timedelta(days=ORNEK_GUN_SAYISI - 1)).replace(hour=8, minute=0)
    saat = _Saat(ilk_gun)
    with clock.use_clock(yerel=saat, tekduze=saat.tekduze):
        svc = build_services(open_database(yol))
        try:
            svc.settings.set("shop_name", "Örnek Tekel Bayii")
            kategori = {r["name"]: r["id"] for r in svc.db.query(
                "SELECT id, name FROM categories WHERE parent_id IS NOT NULL")}
            tedarikci = [svc.suppliers.create(ad) for ad in TEDARIKCILER]
            urunler = []
            for i, (ad, fiyat, kat, marka, stok, alis) in enumerate(URUNLER):
                urunler.append(svc.products.quick_create(
                    ad, fiyat * 100, barcode=barkod(i), initial_stock=stok + 20,
                    purchase_cost=alis * 100, category_id=kategori.get(kat),
                    brand_name=marka, location_id=1 + i % 8))
            agirlik = [1.0 / (i % 17 + 1) for i in range(len(urunler))]
            satislar: list[int] = []
            for g in range(ORNEK_GUN_SAYISI):
                gun = ilk_gun + timedelta(days=g)
                saat.an = gun.replace(hour=8, minute=30)
                if g in (3, ORNEK_GUN_SAYISI - 1):          # haftalık mal kabul
                    fis = svc.purchases.start_draft(
                        supplier_id=tedarikci[g % len(tedarikci)], invoice_no=f"A-{1040 + g}")
                    for j in rng.sample(range(len(urunler)), 6):
                        artis = 1.08 if g == ORNEK_GUN_SAYISI - 1 and j % 2 == 0 else 1.0
                        svc.purchases.add_line(fis, urunler[j], 24,
                                               int(URUNLER[j][5] * 100 * artis))
                    svc.purchases.commit(fis)
                if g == 6:
                    for j in (0, 1, 18):
                        svc.products.set_price(urunler[j], (URUNLER[j][1] + 5) * 100)
                if g == ORNEK_GUN_SAYISI - 5:
                    oturum = svc.counts.start([1])
                    for r in svc.db.query(
                            "SELECT p.id, p.current_stock FROM products p JOIN product_locations "
                            "l ON l.product_id = p.id AND l.location_id = 1 AND l.active = 1"):
                        svc.counts.set_counted(oturum, r["id"], 1,
                                               max(0, r["current_stock"] - rng.randint(0, 2)))
                    svc.counts.commit(oturum)
                adet = rng.randint(28, 46) if g < ORNEK_GUN_SAYISI - 1 else 31
                anlar = sorted(gun.replace(hour=9) + timedelta(
                    seconds=rng.randint(0, 10 * 3600 if g == ORNEK_GUN_SAYISI - 1 else 14 * 3600))
                    for _ in range(adet))
                for an in anlar:
                    saat.an = an
                    secilen = list(dict.fromkeys(
                        rng.choices(urunler, agirlik, k=rng.choice([1, 1, 2, 2, 3, 4]))))
                    if rng.random() < 0.7:
                        sepet = Cart()
                        for pid in secilen:
                            svc.cart.add_product(sepet, pid, quantity=rng.choice([1, 1, 2, 3]))
                        svc.cart.autosave(sepet)
                        yontem = PaymentMethod.CASH if rng.random() < 0.55 else PaymentMethod.CARD
                        satislar.append(svc.cart.checkout(sepet, payment_method=yontem).sale_id)
                    else:
                        satislar.append(svc.sales.quick_sale(secilen[0]).sale_id)
                if g in (5, 9):
                    svc.sales.reverse_sale(satislar[-3])
                if g == ORNEK_GUN_SAYISI - 1:
                    svc.sales.reverse_sale(satislar[-40])      # önceki günden: günler arası
            saat.an = ORNEK_AN - timedelta(minutes=12)
            sepet = Cart()
            svc.cart.add_product(sepet, urunler[5])
            svc.cart.add_product(sepet, urunler[25], quantity=2)
            svc.cart.park(sepet)
        finally:
            svc.close()
    for ek in ("-wal", "-shm"):
        Path(str(yol) + ek).unlink(missing_ok=True)
    return yol


# ===================== Sahneler ===========================================
class Baglam:
    def __init__(self, uygulama, pencere, services, cikti: Path) -> None:
        self.uyg = uygulama
        self.pencere = pencere
        self.svc = services
        self.cikti = cikti
        self.son_kutu = None          # yakalanan son modal pencere

    def isle(self, tur: int = 3) -> None:
        for _ in range(tur):
            self.uyg.processEvents()

    def git(self, anahtar: str):
        self.pencere.go_to(anahtar)
        self.isle()
        return self.pencere.pages[anahtar]

    def pid(self, i: int) -> int:
        return int(self.svc.db.scalar(
            "SELECT product_id FROM product_barcodes WHERE barcode_norm = ?", (barkod(i),)))


def _pencere_goster(pencere) -> None:
    from PySide6.QtCore import Qt

    pencere.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    pencere.show()


def _ayri_pencere(b: Baglam, pencere):
    """Bir iletişim penceresini ekranda göstermeden çizer."""
    _pencere_goster(pencere)
    b.isle(4)
    return pencere


def _sahne_listesi():
    from app.scanner.scan_event import ScanEvent

    def ana_ekran(b):
        b.git("ana_ekran")

    def sepet_bos(b):
        sayfa = b.git("sepetli_satis")
        sayfa.cart = b.svc.cart.new_cart()
        sayfa._rebuild_rows()
        sayfa._render()
        sayfa._show_ready()

    def sepet_dolu(b):
        sayfa = b.git("sepetli_satis")
        for i in (0, 0, 18, 10, 39, 25):
            sayfa.handle_scan(ScanEvent(code=barkod(i)))
            b.isle(1)

    def sepet_urun_ara(b):
        sayfa = b.git("sepetli_satis")
        sayfa.open_search()
        b.isle()
        sayfa._search_panel.set_query("efes")
        sayfa._search_panel.search_now()

    def sepet_bekleyenler(b):
        sayfa = b.git("sepetli_satis")
        sayfa.close_overlay()
        sayfa.show_parked()

    def sepet_para_ustu(b):
        sayfa = b.git("sepetli_satis")
        sayfa.close_overlay()
        b.svc.settings.set("cash_change_calculator", 1)
        sayfa.cash_pressed()

    def sepet_satis_tamam(b):
        sayfa = b.git("sepetli_satis")
        sayfa.close_overlay()
        b.svc.settings.set("cash_change_calculator", 0)
        sayfa.complete("NAKIT")

    def sepet_fiyat_degisti(b):
        sayfa = b.git("sepetli_satis")
        sayfa.handle_scan(ScanEvent(code=barkod(1)))
        sayfa.handle_scan(ScanEvent(code=barkod(26)))
        b.isle()
        eski = int(b.svc.db.scalar("SELECT sale_price FROM products WHERE id = ?",
                                   (b.pid(1),)))
        b.svc.products.set_price(b.pid(1), eski + 700)   # okutulduktan SONRA değişti
        sayfa.cash_pressed()                         # ret: fiyat değişti
        b.isle()

    def sepet_tanimsiz_barkod(b):
        sayfa = b.git("sepetli_satis")
        sayfa.apply_current_prices()
        sayfa.handle_scan(ScanEvent(code="8699999999993"))

    def hizli_urun_formu(b):
        from app.ui.dialogs.unknown_barcode import UnknownBarcodeDialog

        return _ayri_pencere(b, UnknownBarcodeDialog("8691234567895", b.svc, b.pencere))

    def hizli_satis(b):
        sayfa = b.git("hizli_satis")
        for i in (18, 32, 0):
            sayfa.handle_scan(ScanEvent(code=barkod(i)))
            b.isle(1)

    def fiyat_gor(b):
        sayfa = b.git("fiyat_kontrol")
        sayfa.show_price_for(barkod(9))

    def hizli_stok(b):
        sayfa = b.git("hizli_stok")
        sayfa.scan_code(barkod(30))

    def mal_kabul(b):
        sayfa = b.git("stok_girisi")
        for i in (0, 0, 19, 26, 37):
            sayfa.handle_scan(ScanEvent(code=barkod(i)))
            b.isle(1)
        sayfa.select_line(0)
        sayfa.set_selected_cost(5600)

    def stok_sayimi(b):
        b.git("stok_sayimi")

    def stok_durumu(b):
        b.git("stok_durumu")

    def analiz_genel(b):
        b.git("panel")

    def analiz_sekmeler(b):
        sayfa = b.git("panel")
        sonuc = {}
        for i in range(1, sayfa.tabs.count()):
            sayfa.tabs.setCurrentIndex(i)
            b.isle(4)
            ad = f"analiz_{i}_{_dosya_adi(sayfa.tabs.tabText(i))}"
            sonuc[ad] = b.pencere.grab()
        sayfa.tabs.setCurrentIndex(0)
        return sonuc

    def urunler(b):
        sayfa = b.git("urunler")
        sayfa.table.selectRow(2) if hasattr(sayfa, "table") else None

    def urun_duzenle(b):
        from app.ui.dialogs.product_edit import MODE_EDIT, ProductEditDialog

        return _ayri_pencere(b, ProductEditDialog(b.svc, b.pid(10), MODE_EDIT, b.pencere))

    def kategoriler(b):
        b.git("kategoriler")

    def fiyatlar(b):
        b.git("fiyatlar")

    def fiyat_onizleme(b):
        sayfa = b.git("fiyatlar")
        sayfa.table.selectRow(0)
        sayfa.table.selectRow(1) if False else None
        sayfa.preview_selected()

    def ice_aktar(b):
        b.git("ice_aktar")

    def ice_aktar_onizleme(b):
        sayfa = b.git("ice_aktar")
        csv = b.cikti.parent / "ornek_liste.csv"
        satirlar = ["Barkod;Ürün adı;Satış fiyatı;Kategori"]
        for i, (ad, fiyat, kat, *_r) in enumerate(URUNLER[:12]):
            satirlar.append(f"{barkod(i)};{ad};{fiyat + 5},00;{kat}")
        satirlar.append("8690000000123;Yeni Ürün Örneği 1 L;55,00;Kola")
        satirlar.append("12345;Hatalı Barkod;10,00;Su")
        csv.write_text("\n".join(satirlar), encoding="utf-8-sig")
        sayfa.load_file(csv)
        b.isle()
        sayfa.preview()

    def tedarikciler(b):
        b.git("tedarikciler")

    def gecmis(b):
        sayfa = b.git("gecmis")
        sayfa.sales_table.selectRow(1)

    def ayarlar_bolumleri(b):
        sayfa = b.git("ayarlar")
        sonuc = {}
        for kimlik in ("kasa", "gorunum", "yedekleme", "guvenlik"):
            sayfa.show_section(kimlik)
            b.isle(3)
            sonuc[f"ayarlar_{kimlik}"] = b.pencere.grab()
        return sonuc

    def sistem_durumu(b):
        b.git("sistem_durumu")

    def barkod_testi(b):
        sayfa = b.git("barkod_testi")
        for i in (0, 18):
            sayfa.handle_scan(ScanEvent(code=barkod(i)))
            b.isle(1)

    def pin_penceresi(b):
        from app.ui.dialogs.pin_dialog import PinDialog

        return _ayri_pencere(b, PinDialog(b.svc.security, "Toplu fiyat değişikliği", b.pencere))

    def onay_penceresi(b):
        sayfa = b.git("gecmis")
        b.son_kutu = None
        sayfa.sales_table.selectRow(5)
        sayfa._reverse_sale()
        return b.son_kutu

    return [
        ("ana_ekran", ana_ekran), ("sepet_bos", sepet_bos), ("sepet_dolu", sepet_dolu),
        ("sepet_urun_ara", sepet_urun_ara), ("sepet_bekleyenler", sepet_bekleyenler),
        ("sepet_para_ustu", sepet_para_ustu), ("sepet_satis_tamam", sepet_satis_tamam),
        ("sepet_fiyat_degisti", sepet_fiyat_degisti),
        ("sepet_tanimsiz_barkod", sepet_tanimsiz_barkod),
        ("hizli_urun_formu", hizli_urun_formu), ("hizli_satis", hizli_satis),
        ("fiyat_gor", fiyat_gor), ("hizli_stok", hizli_stok), ("mal_kabul", mal_kabul),
        ("stok_sayimi", stok_sayimi), ("stok_durumu", stok_durumu),
        ("analiz_genel", analiz_genel), ("analiz_sekmeler", analiz_sekmeler),
        ("urunler", urunler), ("urun_duzenle", urun_duzenle), ("kategoriler", kategoriler),
        ("fiyatlar", fiyatlar), ("fiyat_onizleme", fiyat_onizleme),
        ("ice_aktar", ice_aktar), ("ice_aktar_onizleme", ice_aktar_onizleme),
        ("tedarikciler", tedarikciler), ("gecmis", gecmis),
        ("ayarlar_bolumleri", ayarlar_bolumleri), ("sistem_durumu", sistem_durumu),
        ("barkod_testi", barkod_testi), ("pin_penceresi", pin_penceresi),
        ("onay_penceresi", onay_penceresi),
    ]


def _dosya_adi(metin: str) -> str:
    tablo = str.maketrans("çğıöşüÇĞİÖŞÜ âî", "cgiosuCGIOSU_ai")
    return "".join(c for c in metin.translate(tablo).lower() if c.isalnum() or c == "_")


def kirpilan_yazilar(kok) -> list[tuple[str, int, int]]:
    """Görünür düğme, etiket ve giriş alanlarından yazısı DİKEYDE kırpılanlar:
    (metin, gerek, mevcut).

    Stil sayfasındaki ``min-height`` gerecin açık en küçük yüksekliği olur;
    yer daralınca (ör. kaydırılan menü) yerleşim düğmeyi doğal yüksekliğinin
    altına, o en küçük değere sıkıştırır. İçerik alanı yazı satırından kısa
    kalırsa g/y/ç/ş'nin alt kısmı kesilir (M12d son kapı: menü %130'da
    "Avarlar", "Gecmis" okunuyordu).
    """
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import (
        QComboBox, QLabel, QLineEdit, QPushButton, QStyle, QStyleOptionButton,
        QStyleOptionComboBox, QStyleOptionFrame,
    )

    sonuc = []
    for dugme in kok.findChildren(QPushButton):
        if not dugme.isVisible() or not dugme.text().strip():
            continue
        secenek = QStyleOptionButton()
        dugme.initStyleOption(secenek)
        icerik = dugme.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, secenek, dugme)
        olcum = QFontMetrics(dugme.font())
        satir = olcum.height()
        if icerik.height() < satir:
            sonuc.append((dugme.text().strip(), satir, icerik.height()))
        # Yatayda: QPushButton yazıyı kısaltmaz; dar düğmede baş ve son harfler
        # kesilir (M12d: %130'da "üncel fiyatları uygu").
        en = max(olcum.horizontalAdvance(s) for s in dugme.text().split("\n"))
        if not dugme.icon().isNull():
            en += dugme.iconSize().width() + 4
        if icerik.width() + 1 < en:
            sonuc.append((f"{dugme.text().strip()} (genişlik)", en, icerik.width()))
    for etiket in kok.findChildren(QLabel):
        if not etiket.isVisible() or not etiket.text().strip():
            continue
        if etiket.pixmap() is not None and not etiket.pixmap().isNull():
            continue
        if etiket.wordWrap():
            # heightForWidth kenar boşluklarını da içerir: tüm yükseklikle karşılaştır.
            gerek, mevcut = etiket.heightForWidth(etiket.width()), etiket.height()
        else:
            gerek = QFontMetrics(etiket.font()).height()
            mevcut = etiket.contentsRect().height()
        if gerek > 0 and mevcut + 1 < gerek:
            sonuc.append((etiket.text().strip()[:40], gerek, mevcut))
    # Tek satırlık giriş: yazı alanı = stil içerik alanı − 1'er px iç boşluk
    # (sayı kutusu ve düzenlenebilir açılır kutunun içindeki QLineEdit dahil).
    for alan in kok.findChildren(QLineEdit):
        if not alan.isVisible():
            continue
        secenek = QStyleOptionFrame()
        alan.initStyleOption(secenek)
        yazi = alan.style().subElementRect(
            QStyle.SubElement.SE_LineEditContents, secenek, alan).height() - 2
        satir = QFontMetrics(alan.font()).height()
        if yazi < satir:
            ad = alan.placeholderText() or type(alan.parent()).__name__
            sonuc.append((ad, satir, yazi))
    for kutu in kok.findChildren(QComboBox):
        if not kutu.isVisible() or kutu.isEditable():
            continue
        secenek = QStyleOptionComboBox()
        kutu.initStyleOption(secenek)
        alan = kutu.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, secenek,
            QStyle.SubControl.SC_ComboBoxEditField, kutu)
        satir = QFontMetrics(kutu.font()).height()
        if alan.height() < satir:
            sonuc.append((kutu.currentText() or "QComboBox", satir, alan.height()))
    return sonuc


def tasmalar(b: Baglam) -> list[dict]:
    """Yerel çizimde taşma denetimi: hiçbir sayfa alanından GENİŞ olmamalı
    (yatay kaydırma yok); Kasa sayfaları ayrıca alanından UZUN olmamalı (Kasa
    kaydırılmaz; diğer sayfalar dikeyde kaydırılabilir). M12d: hiçbir görünür
    düğmenin (sayfa ve menü) yazısı dikeyde kırpılmamalı."""
    sonuc = []
    alan = b.pencere.stack.size()
    for anahtar in list(b.pencere.pages):
        sayfa = b.git(anahtar)
        gerek = sayfa.minimumSizeHint()
        kasa = getattr(sayfa, "kasa_sayfasi", False)
        if gerek.width() > alan.width():
            sonuc.append({"sayfa": anahtar, "yon": "yatay", "gerek": gerek.width(),
                          "mevcut": alan.width()})
        if kasa and gerek.height() > alan.height():
            sonuc.append({"sayfa": anahtar, "yon": "dikey", "gerek": gerek.height(),
                          "mevcut": alan.height()})
        for metin, satir, icerik in kirpilan_yazilar(sayfa):
            sonuc.append({"sayfa": anahtar, "yon": f"yazı kırpılıyor '{metin}'",
                          "gerek": satir, "mevcut": icerik})
    # Menü, bütün öğeleri görünürken (en kalabalık hâli) bir kez denetlenir;
    # kayıtlı açık/kapalı durumu değişmez, sonra eski hâline döner.
    for dugme in b.pencere.nav_buttons.values():
        dugme.setVisible(True)
    b.isle()
    for metin, satir, icerik in kirpilan_yazilar(b.pencere.nav_scroll.widget()):
        sonuc.append({"sayfa": "menü", "yon": f"yazı kırpılıyor '{metin}'",
                      "gerek": satir, "mevcut": icerik})
    b.pencere.apply_nav_visibility()
    b.isle()
    return sonuc


# ===================== Profil çalıştırma (çocuk süreç) =====================
def _profil_calistir(ad: str, cikti: Path, ornek: Path, yalnizca_tasma: bool = False) -> dict:
    profil = PROFILLER[ad]
    if os.name == "nt":
        os.environ["QT_QPA_PLATFORM"] = "windows"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    if profil.olcek != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(profil.olcek)
    else:
        os.environ.pop("QT_SCALE_FACTOR", None)

    from app import config
    from app.tools import veri_guvenligi

    karalama = veri_guvenligi.karalama_klasoru()
    veri = karalama / f"ekran_{ad}"
    if veri.exists():
        shutil.rmtree(veri)
    veri.mkdir(parents=True)
    shutil.copyfile(ornek, veri / config.DB_FILE_NAME)
    os.environ[config.ENV_DATA_DIR] = str(veri)

    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    uyg = QApplication.instance() or QApplication([])
    from app.core import clock
    from app.ui import sound, theme

    theme.gorunumu_uygula(profil.tema, profil.yazi, "NORMAL")
    theme.apply_theme(uyg)
    sound.yapilandir(False)

    cikti.mkdir(parents=True, exist_ok=True)
    kayit = {"profil": ad, "aciklama": profil.aciklama, "sahneler": [], "hatalar": {}}
    saat = _Saat(ORNEK_AN)
    with clock.use_clock(yerel=saat, tekduze=saat.tekduze):
        from app.services.container import create_services
        from app.ui.main_window import MainWindow

        svc = create_services()
        b = Baglam(uyg, None, svc, cikti)

        def kirpma_kaydet(yer: str, kok) -> None:
            for metin, gerek, mevcut in kirpilan_yazilar(kok):
                kayit["tasmalar"].append({"sayfa": yer, "yon": f"yazı kırpılıyor '{metin}'",
                                          "gerek": gerek, "mevcut": mevcut})

        def kutu_exec(kutu):
            _pencere_goster(kutu)
            b.isle(3)
            kirpma_kaydet("onay penceresi", kutu)
            b.son_kutu = kutu.grab()
            kutu.hide()
            return QMessageBox.StandardButton.Cancel

        QMessageBox.exec = kutu_exec
        QMessageBox.clickedButton = lambda self: None
        QDialog.exec = lambda self: QDialog.DialogCode.Rejected

        pencere = MainWindow(svc)
        b.pencere = pencere
        _pencere_goster(pencere)
        pencere.resize(profil.genislik, profil.yukseklik)
        b.isle(5)
        kayit["boyut"] = list(pencere.size().toTuple())
        kayit["piksel_orani"] = pencere.devicePixelRatioF()
        kayit["tasmalar"] = tasmalar(b)
        sahneler = [] if yalnizca_tasma else _sahne_listesi()
        for sira, (sahne_adi, islev) in enumerate(sahneler, start=1):
            try:
                sonuc = islev(b)
                b.isle(4)
                # Her sahnenin DURUMU da denetlenir (açık katman, pencere,
                # değişen fiyat düğmesi gibi yalnızca o anda görünenler).
                if sonuc is None:
                    kirpma_kaydet(f"sahne {sahne_adi}", pencere)
                elif hasattr(sonuc, "findChildren"):
                    kirpma_kaydet(f"sahne {sahne_adi}", sonuc)
                if sonuc is None:
                    sonuc = {sahne_adi: pencere.grab()}
                elif not isinstance(sonuc, dict):
                    gorsel = sonuc.grab() if hasattr(sonuc, "grab") else sonuc
                    if hasattr(sonuc, "close"):
                        sonuc.close()
                    sonuc = {sahne_adi: gorsel}
                for alt, gorsel in sonuc.items():
                    dosya = cikti / f"{sira:02d}_{alt}.png"
                    gorsel.save(str(dosya))
                    kayit["sahneler"].append(dosya.name)
            except Exception:
                kayit["hatalar"][sahne_adi] = traceback.format_exc(limit=3)
        pencere.close()
        svc.close()
    (cikti / "sahneler.json").write_text(json.dumps(kayit, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    return kayit


# ===================== Komut satırı ======================================
def main(argv: list[str] | None = None) -> int:
    from app.tools import veri_guvenligi

    ayr = argparse.ArgumentParser(description="TekelStok ekran görüntüleri")
    ayr.add_argument("--cikti", required=True)
    ayr.add_argument("--profil", choices=sorted(PROFILLER), action="append")
    ayr.add_argument("--ornek", help="hazır örnek veri (yoksa üretilir)")
    ayr.add_argument("--yalnizca-tasma", action="store_true",
                     help="görüntü almadan yalnızca taşma denetimi (hızlı)")
    args = ayr.parse_args(argv)
    try:
        karalama = veri_guvenligi.karalama_klasoru()
        cikti = Path(args.cikti).resolve()
        gercek = veri_guvenligi.gercek_veri_klasoru()
        if gercek is not None and (cikti == gercek or gercek in cikti.parents):
            raise veri_guvenligi.GercekVeriKlasoruHatasi(
                "Ekran görüntüleri gerçek veri klasörüne yazılamaz.")
    except veri_guvenligi.GercekVeriKlasoruHatasi as hata:
        print(f"REDDEDİLDİ: {hata}", file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    ornek = Path(args.ornek) if args.ornek else karalama / "ekran_ornek.db"
    if not ornek.exists():
        bas = time.perf_counter()
        ornek_dukkan(ornek)
        print(f"Örnek veri üretildi: {ornek} ({time.perf_counter() - bas:.1f} sn)")

    profiller = args.profil or list(PROFILLER)
    if len(profiller) == 1:
        kayit = _profil_calistir(profiller[0], cikti / profiller[0], ornek,
                                 yalnizca_tasma=args.yalnizca_tasma)
        print(f"{profiller[0]}: {len(kayit['sahneler'])} görüntü, "
              f"{len(kayit['hatalar'])} hata, piksel oranı {kayit.get('piksel_orani')}, "
              f"taşma {len(kayit['tasmalar'])}")
        for tasma in kayit["tasmalar"]:
            print(f"  TAŞMA {tasma['sayfa']} {tasma['yon']}: {tasma['gerek']} > "
                  f"{tasma['mevcut']}")
        for sahne, iz in kayit["hatalar"].items():
            print(f"  HATA {sahne}: {iz.strip().splitlines()[-1]}")
        return 0 if not kayit["hatalar"] and not kayit["tasmalar"] else 1
    durum = 0
    for ad in profiller:                           # her ölçek ayrı süreçte
        komut = [sys.executable, "-m", "app.tools.ekran_goruntusu", "--cikti", str(cikti),
                 "--profil", ad, "--ornek", str(ornek)]
        if args.yalnizca_tasma:
            komut.append("--yalnizca-tasma")
        sonuc = subprocess.run(komut, cwd=str(Path(__file__).resolve().parents[2]))
        durum = durum or sonuc.returncode
    if not args.yalnizca_tasma:
        dizin = temas_sayfasi(cikti, profiller)
        print(f"Dizin: {dizin}")
    return durum


def temas_sayfasi(cikti: Path, profiller: list[str]) -> Path:
    """Bütün görüntüleri profil profil gösteren tek HTML sayfası (yerel dosya)."""
    import html

    parcalar = ["<!doctype html><html lang='tr'><head><meta charset='utf-8'>",
                "<title>TekelStok ekran görüntüleri</title><style>",
                "body{font-family:'Segoe UI',sans-serif;margin:16px;background:#eef1f5}",
                "h2{margin-top:32px}figure{display:inline-block;margin:6px;width:320px;"
                "vertical-align:top}img{width:320px;border:1px solid #ccc;background:#fff}"
                "figcaption{font-size:12px;color:#444}</style></head><body>",
                "<h1>TekelStok — ekran görüntüleri</h1>"]
    for ad in profiller:
        klasor = cikti / ad
        if not klasor.exists():
            continue
        profil = PROFILLER[ad]
        parcalar.append(f"<h2>{html.escape(ad)} — {html.escape(profil.aciklama)}</h2>")
        for png in sorted(klasor.glob("*.png")):
            yol = f"{ad}/{png.name}"
            parcalar.append(f"<figure><a href='{yol}'><img src='{yol}' loading='lazy'></a>"
                            f"<figcaption>{html.escape(png.stem)}</figcaption></figure>")
    parcalar.append("</body></html>")
    dizin = cikti / "index.html"
    dizin.write_text("".join(parcalar), encoding="utf-8")
    return dizin


if __name__ == "__main__":
    sys.exit(main())
