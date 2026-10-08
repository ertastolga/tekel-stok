"""Ürün listesi içe aktarma: önizleme, doğrulama, çakışma politikası, atomik yazma.

Akış (plan §6.2): dosya → sütunlar → eşleme → ÖNİZLEME → doğrulama → sorun
özeti → çakışma politikası → onay → atomik içe aktarma.

Kurallar:
  * Önizleme HİÇBİR ŞEY yazmaz. Her satırın durumu: ``YENI`` (eklenecek),
    ``GUNCELLE`` (eşleşen ürün değişecek), ``AYNI`` (eşleşen ürün zaten aynı),
    ``CAKISMA`` (dosyada tekrarlanan / kaldırılmış ürüne ait barkod),
    ``GECERSIZ`` (eksik zorunlu alan, geçersiz barkod/fiyat), ``ATLANDI``
    (politika gereği dokunulmayacak).
  * Uygulamadan ÖNCE otomatik "içe aktarma öncesi" yedeği alınır; alınamazsa
    hiçbir şey yazılmaz. Sonra her şey TEK işlemde yazılır: biri bile
    başarısız olursa hiçbiri yazılmaz.
  * Fiyat değişiklikleri "İçe aktarma" grubu olarak fiyat geçmişine yazılır
    (Fiyat Yönetimi'nden geri alınabilir). Alış fiyatı sütunu YALNIZCA
    referans (katalog) alış fiyatına yazılır; stok değerine, son alışa ve
    maliyete ASLA girmez.
  * Boş hücre hiçbir zaman var olan bilginin üzerine yazmaz. Güncellenecek
    alanları kullanıcı seçer (varsayılan: satış ve alış fiyatı).
  * Barkod ASLA kendiliğinden düzeltilmez; sıfırla tamamlama yalnızca satır
    satır kabul edilen bir öneridir.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.errors import DomainError, GecersizFiyat
from app.core.tr import normalize_name
from app.importers import alanlar as al
from app.importers.okuyucu import Tablo
from app.services.pricing_service import ICE_AKTARMA, FiyatDegisikligi
from app.services.product_service import YeniUrun

log = logging.getLogger(__name__)

# ----- Satır durumları ------------------------------------------------------
YENI = "YENI"
GUNCELLE = "GUNCELLE"
AYNI = "AYNI"
CAKISMA = "CAKISMA"
GECERSIZ = "GECERSIZ"
ATLANDI = "ATLANDI"
DURUM_ADLARI: dict[str, str] = {
    YENI: "Yeni ürün",
    GUNCELLE: "Güncellenecek",
    AYNI: "Değişiklik yok",
    CAKISMA: "Çakışma",
    GECERSIZ: "Geçersiz",
    ATLANDI: "Atlandı",
}

# ----- Çakışma politikaları -------------------------------------------------
YALNIZ_YENI = "YALNIZ_YENI"
YALNIZ_GUNCELLE = "YALNIZ_GUNCELLE"
EKLE_VE_GUNCELLE = "EKLE_VE_GUNCELLE"
POLITIKA_ADLARI: dict[str, str] = {
    YALNIZ_YENI: "Yalnızca yeni ürünleri ekle (eşleşenlere dokunma)",
    YALNIZ_GUNCELLE: "Yalnızca eşleşen ürünleri güncelle",
    EKLE_VE_GUNCELLE: "Yenileri ekle ve eşleşenleri güncelle",
}

#: Güncellenebilen alanlar ve varsayılan seçim.
GUNCELLENEBILIR = (al.AD, al.SATIS, al.KATEGORI, al.MARKA, al.AILE, al.TEDARIKCI,
                   al.ALIS, al.KDV)
VARSAYILAN_GUNCELLENECEK = frozenset({al.SATIS, al.ALIS})
ICE_AKTARMA_YEDEK_ONEKI = "ice_aktarma_oncesi_"


@dataclass
class PlanSatiri:
    satir_no: int                       # dosyadaki satır (başlık 1. satır)
    durum: str
    barkod: str | None = None
    ad: str | None = None
    alanlar: dict = field(default_factory=dict)
    product_id: int | None = None
    farklar: dict = field(default_factory=dict)     # alan → (eski, yeni)
    sorunlar: list[str] = field(default_factory=list)
    uyarilar: list[str] = field(default_factory=list)
    sifir_onerisi: str | None = None
    #: Sayımlar için ayrıntı: "barkod", "zorunlu", "fiyat" ya da None.
    hata_turu: str | None = None


@dataclass
class IceAktarmaPlani:
    satirlar: list[PlanSatiri]
    politika: str
    esleme: dict[str, int]

    def sayilar(self) -> dict[str, int]:
        """Önizleme sayıları (plan §6.2)."""
        say = lambda d: sum(1 for s in self.satirlar if s.durum == d)  # noqa: E731
        return {
            "toplam": len(self.satirlar),
            "yeni": say(YENI),
            "eslesen": sum(1 for s in self.satirlar if s.product_id is not None),
            "guncellenecek": say(GUNCELLE),
            "ayni": say(AYNI),
            "cakisma": say(CAKISMA),
            "gecersiz_barkod": sum(1 for s in self.satirlar if s.hata_turu == "barkod"),
            "eksik_zorunlu": sum(1 for s in self.satirlar if s.hata_turu == "zorunlu"),
            "gecersiz_fiyat": sum(1 for s in self.satirlar if s.hata_turu == "fiyat"),
            "gecersiz": say(GECERSIZ),
            "atlanan": say(ATLANDI),
        }

    def yazilacak(self) -> list[PlanSatiri]:
        return [s for s in self.satirlar if s.durum in (YENI, GUNCELLE)]


@dataclass(frozen=True)
class IceAktarmaSonucu:
    yeni: int
    guncellenen: int
    atlanan: int
    yedek_yolu: str
    fiyat_grubu: int | None


class ImportService:
    def __init__(self, db, products, barcodes, catalog, categories, suppliers,
                 pricing, backup, audit) -> None:
        self.db = db
        self.products = products
        self.barcodes = barcodes
        self.catalog = catalog
        self.categories = categories
        self.suppliers = suppliers
        self.pricing = pricing
        self.backup = backup
        self.audit = audit

    # ===================== Önizleme ======================================
    def onizle(
        self,
        tablo: Tablo,
        esleme: dict[str, int],
        politika: str = EKLE_VE_GUNCELLE,
        varsayilan_kategori_id: int | None = None,
        sifir_onerisi_kabul: frozenset[int] = frozenset(),
    ) -> IceAktarmaPlani:
        """Hiçbir şey YAZMAZ. ``sifir_onerisi_kabul``: önerisi kabul edilen satır no'ları."""
        if politika not in POLITIKA_ADLARI:
            raise ValueError(f"bilinmeyen politika: {politika}")
        eksik = [al.ALAN_ADLARI[a] for a in (al.BARKOD,) if a not in esleme]
        if eksik:
            raise DomainError(f"'{eksik[0]}' sütunu seçilmedi; barkod olmadan ürün "
                              "eşleştirilemez.")
        barkodlar = self._barkod_haritasi()
        kategoriler = self._kategori_haritasi()
        urunler = {
            u["id"]: u for u in self.db.query(
                "SELECT p.*, b.name AS marka, f.name AS aile, s.name AS tedarikci "
                "  FROM products p LEFT JOIN brands b ON b.id = p.brand_id "
                "  LEFT JOIN product_families f ON f.id = p.family_id "
                "  LEFT JOIN suppliers s ON s.id = p.default_supplier_id")
        }
        gorulen: dict[str, int] = {}
        satirlar = []
        for sira, ham in enumerate(tablo.satirlar, start=2):
            satir = self._satir(sira, ham, tablo, esleme, kategoriler,
                                varsayilan_kategori_id, sira in sifir_onerisi_kabul)
            if satir.durum != GECERSIZ:
                self._eslestir(satir, barkodlar, urunler, gorulen, politika,
                               varsayilan_kategori_id)
            satirlar.append(satir)
        return IceAktarmaPlani(satirlar, politika, dict(esleme))

    def _barkod_haritasi(self) -> dict[str, tuple[int, bool]]:
        """barkod_norm / gtin14 → (ürün, etkin mi). Tek sorgu."""
        harita: dict[str, tuple[int, bool]] = {}
        for b in self.db.query(
            "SELECT b.barcode_norm, b.gtin14, b.product_id, p.is_active "
            "  FROM product_barcodes b JOIN products p ON p.id = b.product_id "
            " WHERE b.active = 1 OR p.is_active = 0 ORDER BY b.active"
        ):
            deger = (b["product_id"], bool(b["is_active"]))
            harita[b["barcode_norm"]] = deger
            if b["gtin14"]:
                harita.setdefault("#" + b["gtin14"], deger)
        return harita

    def _kategori_haritasi(self) -> dict[str, int | None]:
        """"üst > alt" ve tekil "alt" adı (normalize) → kategori; belirsiz ad → None."""
        harita: dict[str, int | None] = {}
        satirlar = self.db.query(
            "SELECT c.id, c.name, c.parent_id, u.name AS ust FROM categories c "
            "  LEFT JOIN categories u ON u.id = c.parent_id WHERE c.active = 1")
        for s in satirlar:
            ad = normalize_name(s["name"])
            if s["ust"]:
                harita[f"{normalize_name(s['ust'])}>{ad}"] = s["id"]
            harita[ad] = None if ad in harita else s["id"]
        return harita

    def _satir(self, sira, ham, tablo, esleme, kategoriler, varsayilan_kategori,
               sifir_kabul) -> PlanSatiri:
        satir = PlanSatiri(sira, YENI)
        deger = lambda alan: tablo.hucre(ham, esleme.get(alan))  # noqa: E731

        barkod = al.barkod_hucresi(deger(al.BARKOD))
        if barkod.hata:
            return self._gecersiz(satir, barkod.hata, "barkod")
        if barkod.metin is None:
            return self._gecersiz(satir, "barkod eksik", "zorunlu")
        satir.barkod = barkod.metin
        if barkod.sayisal:
            satir.uyarilar.append("barkod sayı olarak kaydedilmiş: baştaki sıfırlar "
                                  "kaybolmuş olabilir")
        if barkod.oneri:
            if sifir_kabul:
                satir.uyarilar.append(f"barkod {barkod.metin} → {barkod.oneri} "
                                      "(sıfırla tamamlama kabul edildi)")
                satir.barkod = barkod.oneri
            else:
                satir.sifir_onerisi = barkod.oneri

        satir.ad = al.metin_hucresi(deger(al.AD))
        if satir.ad:
            satir.alanlar[al.AD] = satir.ad
        try:
            satis = al.fiyat_hucresi(deger(al.SATIS))
            if satis is not None and satis <= 0:
                raise GecersizFiyat()
        except DomainError:
            return self._gecersiz(satir, "geçersiz satış fiyatı", "fiyat")
        if satis is not None:
            satir.alanlar[al.SATIS] = satis
        try:
            alis = al.fiyat_hucresi(deger(al.ALIS))
        except DomainError:
            return self._gecersiz(satir, "geçersiz alış fiyatı", "fiyat")
        if alis is not None:
            satir.alanlar[al.ALIS] = alis
        try:
            kdv = al.kdv_hucresi(deger(al.KDV))
        except DomainError:
            return self._gecersiz(satir, "geçersiz KDV oranı", None)
        if kdv is not None:
            satir.alanlar[al.KDV] = kdv
        for alan in (al.MARKA, al.AILE, al.TEDARIKCI):
            metin = al.metin_hucresi(deger(alan))
            if metin:
                satir.alanlar[alan] = metin

        kategori_metni = al.metin_hucresi(deger(al.KATEGORI))
        if kategori_metni:
            kategori = self._kategori_bul(kategori_metni, kategoriler)
            if kategori is not None:
                satir.alanlar[al.KATEGORI] = kategori
            else:
                satir.uyarilar.append(
                    f"'{kategori_metni}' kategorisi bulunamadı"
                    + ("; varsayılan kategori kullanılacak" if varsayilan_kategori else ""))
        return satir

    @staticmethod
    def _kategori_bul(metin: str, kategoriler: dict) -> int | None:
        for ayirici in (">", "/", "\\"):
            if ayirici in metin:
                ust, _, alt = metin.partition(ayirici)
                return kategoriler.get(f"{normalize_name(ust.strip())}>"
                                       f"{normalize_name(alt.strip())}")
        return kategoriler.get(normalize_name(metin))

    @staticmethod
    def _gecersiz(satir: PlanSatiri, neden: str, tur: str | None) -> PlanSatiri:
        satir.durum = GECERSIZ
        satir.sorunlar.append(neden)
        satir.hata_turu = tur
        return satir

    def _eslestir(self, satir, barkodlar, urunler, gorulen, politika,
                  varsayilan_kategori) -> None:
        anahtar = satir.barkod
        if anahtar in gorulen:
            satir.durum = CAKISMA
            satir.sorunlar.append(f"aynı barkod {gorulen[anahtar]}. satırda da var")
            return
        gorulen[anahtar] = satir.satir_no
        bulunan = barkodlar.get(anahtar)
        if bulunan is None:
            gtin = self.barcodes.canonical(anahtar)
            if gtin:
                bulunan = barkodlar.get("#" + gtin)
        if bulunan is not None and not bulunan[1]:
            satir.durum = CAKISMA
            satir.product_id = bulunan[0]
            satir.sorunlar.append("barkod kullanımdan kaldırılmış bir ürüne ait "
                                  "(önce o ürünü yeniden kullanıma alın)")
            return

        if bulunan is None:
            if politika == YALNIZ_GUNCELLE:
                satir.durum = ATLANDI
                satir.sorunlar.append("yeni ürün (politika: yalnızca güncelle)")
                return
            eksikler = [al.ALAN_ADLARI[a] for a in (al.AD, al.SATIS) if a not in satir.alanlar]
            if eksikler:
                self._gecersiz(satir, f"eksik zorunlu alan: {', '.join(eksikler)}",
                               "zorunlu")
                return
            if al.KATEGORI not in satir.alanlar:
                if varsayilan_kategori is None:
                    self._gecersiz(satir, "kategori yok (varsayılan kategori seçin)",
                                   "zorunlu")
                    return
                satir.alanlar[al.KATEGORI] = varsayilan_kategori
            satir.durum = YENI
            return

        satir.product_id = bulunan[0]
        urun = urunler[bulunan[0]]
        if politika == YALNIZ_YENI:
            satir.durum = ATLANDI
            satir.sorunlar.append("var olan ürün (politika: yalnızca yeni)")
            return
        mevcut = {
            al.AD: urun["name"], al.SATIS: urun["sale_price"],
            al.KATEGORI: urun["category_id"], al.MARKA: urun["marka"],
            al.AILE: urun["aile"], al.TEDARIKCI: urun["tedarikci"],
            al.ALIS: urun["reference_cost"], al.KDV: urun["vat_rate"],
        }
        for alan, yeni in satir.alanlar.items():
            eski = mevcut.get(alan)
            ayni = (normalize_name(str(eski or "")) == normalize_name(str(yeni))
                    if alan in (al.MARKA, al.AILE, al.TEDARIKCI) else eski == yeni)
            if not ayni:
                satir.farklar[alan] = (eski, yeni)
        satir.durum = GUNCELLE if satir.farklar else AYNI

    # ===================== Uygulama ======================================
    def uygula(
        self,
        plan: IceAktarmaPlani,
        dosya_adi: str,
        sha256: str,
        guncellenecek: frozenset[str] = VARSAYILAN_GUNCELLENECEK,
    ) -> IceAktarmaSonucu:
        """Önce güvenlik yedeği, sonra TEK işlemde yazar (hepsi ya da hiçbiri)."""
        yeniler = [s for s in plan.satirlar if s.durum == YENI]
        guncellenecekler = [
            s for s in plan.satirlar
            if s.durum == GUNCELLE and any(a in guncellenecek for a in s.farklar)
        ]
        if not yeniler and not guncellenecekler:
            raise DomainError("İçe aktarılacak değişiklik yok.")

        yedek = self.backup.create_safety_backup(ICE_AKTARMA_YEDEK_ONEKI)
        grup = None
        with self.db.transaction() as conn:
            for s in yeniler:
                a = s.alanlar
                self.products.add_product(YeniUrun(
                    name=a[al.AD], sale_price=a[al.SATIS], category_id=a[al.KATEGORI],
                    barcode=s.barkod, brand_name=a.get(al.MARKA),
                    family_name=a.get(al.AILE),
                    supplier_id=self.suppliers.ensure(a.get(al.TEDARIKCI)),
                    vat_rate=a.get(al.KDV), reference_cost=a.get(al.ALIS),
                ))
            fiyatlar = []
            for s in guncellenecekler:
                self._guncelle(s, guncellenecek, fiyatlar)
            if fiyatlar:
                grup = self.pricing.uygula(fiyatlar, tur=ICE_AKTARMA,
                                           aciklama=f"İçe aktarma: {dosya_adi}", conn=conn)
            atlanan = len(plan.satirlar) - len(yeniler) - len(guncellenecekler)
            self.audit.record(
                "ICE_AKTARMA",
                f"{dosya_adi}: {len(yeniler)} yeni ürün, {len(guncellenecekler)} "
                f"güncelleme, {atlanan} satır yazılmadı.",
                "import", None,
                details={"dosya": dosya_adi, "sha256": sha256, "yeni": len(yeniler),
                         "guncellenen": len(guncellenecekler), "atlanan": atlanan,
                         "politika": plan.politika, "fiyat_grubu": grup,
                         "alanlar": sorted(guncellenecek), "yedek": str(yedek)},
                conn=conn,
            )
        return IceAktarmaSonucu(len(yeniler), len(guncellenecekler), atlanan, str(yedek),
                                grup)

    def _guncelle(self, s: PlanSatiri, guncellenecek, fiyatlar: list) -> None:
        pid = s.product_id
        alanlar: dict = {}
        for alan, (eski, yeni) in s.farklar.items():
            if alan not in guncellenecek:
                continue
            if alan == al.SATIS:
                fiyatlar.append(FiyatDegisikligi(pid, eski, yeni))
            elif alan == al.ALIS:
                self.products.set_reference_cost(pid, yeni)
            elif alan == al.AD:
                alanlar["name"] = yeni
            elif alan == al.KATEGORI:
                alanlar["category_id"] = yeni
            elif alan == al.KDV:
                alanlar["vat_rate"] = yeni
            elif alan == al.MARKA:
                alanlar["brand_id"] = self.catalog.ensure_brand(yeni)
            elif alan == al.AILE:
                alanlar["family_id"] = self.catalog.ensure_family(yeni)
            elif alan == al.TEDARIKCI:
                alanlar["default_supplier_id"] = self.suppliers.ensure(yeni)
        if alanlar:
            self.products.update(pid, **alanlar)


def hata_raporu_satirlari(plan: IceAktarmaPlani) -> list[list[str]]:
    """Yazılmayan satırlar ve nedenleri (CSV hata raporu için)."""
    satirlar = [["Satır", "Durum", "Barkod", "Ürün adı", "Neden"]]
    for s in plan.satirlar:
        if s.durum in (GECERSIZ, CAKISMA, ATLANDI) or s.uyarilar or s.sifir_onerisi:
            satirlar.append([
                str(s.satir_no), DURUM_ADLARI[s.durum], s.barkod or "", s.ad or "",
                "; ".join(s.sorunlar + s.uyarilar
                          + ([f"öneri: {s.sifir_onerisi}"] if s.sifir_onerisi else [])),
            ])
    return satirlar
