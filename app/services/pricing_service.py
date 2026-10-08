"""Fiyat Yönetimi: liste, toplu değişiklik önizlemesi, uygulama ve geri alma.

Kurallar (plan §7 M5a, §4 E):
  * Her toplu değişiklik bir GRUP (``price_change_batches``) olarak TEK işlemde
    yazılır; her ürün için fiyat geçmişine eski → yeni satırı düşer.
  * Uygulamadan hemen önce, aynı işlemin İÇİNDE, her ürünün fiyatı önizlemedeki
    eski fiyatla karşılaştırılır; biri bile değiştiyse HİÇBİR ŞEY yazılmaz.
  * Geri alma, grubun SAKLANAN eski fiyatlarını geri koyar — ama yalnızca o
    ürünün son fiyat değişikliği hâlâ bu grupsa ve fiyat hâlâ grubun yazdığı
    fiyatsa. Sonradan elle değiştirilmiş ürünlere dokunulmaz (raporlanır).
    Bir grup yalnızca BİR KEZ geri alınır (benzersiz indeks son savunma hattı).
  * Satış fiyatı geçmişi uydurulmaz: kaydı olmayan ilk fiyat "ilk fiyat (kayıt
    yok)" diye gösterilir, yapay satır yazılmaz.
  * Marj ve öneriler yalnızca BİLİNEN gerçek alış fiyatıyla hesaplanır;
    referans (katalog) alış fiyatı ayrıca ve etiketiyle gösterilir.

Bu servis Qt bilmez.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.core import pricing_math as pm
from app.core.clock import now_utc
from app.core.db import Database
from app.core.errors import FiyatlarDegisti, TopluFiyatHatasi
from app.services.product_service import BILINEN_MALIYET_VAR

# ----- Grup türleri (şemadaki CHECK ile aynı) ------------------------------
TOPLU = "TOPLU"
ICE_AKTARMA = "ICE_AKTARMA"
GERI_ALMA = "GERI_ALMA"
MAL_KABUL = "MAL_KABUL"
GRUP_ADLARI: dict[str, str] = {
    TOPLU: "Toplu değişiklik",
    ICE_AKTARMA: "İçe aktarma",
    GERI_ALMA: "Geri alma",
    MAL_KABUL: "Mal kabul",
}
#: Elle (tek ürün) değişikliklerin zaman çizelgesi adı.
ELLE = "Elle"


@dataclass(frozen=True, slots=True)
class FiyatFiltresi:
    metin: str = ""
    kategori_id: int | None = None
    marka_id: int | None = None
    tedarikci_id: int | None = None
    yalniz_fiyatsiz: bool = False
    yalniz_maliyetsiz: bool = False


@dataclass(frozen=True, slots=True)
class FiyatSatiri:
    product_id: int
    ad: str
    kategori: str
    marka: str
    satis: int | None
    bilinen_maliyet: int | None
    referans_maliyet: int | None
    son_fiyat_degisimi_utc: int | None
    son_alis_utc: int | None

    @property
    def marj_bp(self) -> int | None:
        return pm.marj_bp(self.satis, self.bilinen_maliyet)


@dataclass(frozen=True, slots=True)
class OnizlemeSatiri:
    product_id: int
    ad: str
    eski: int | None
    yeni: int | None
    durum: str
    bilinen_maliyet: int | None

    @property
    def varsayilan_secili(self) -> bool:
        return self.durum == pm.DEGISIR

    @property
    def degisim_bp(self) -> int | None:
        return pm.degisim_bp(self.eski, self.yeni)

    @property
    def yeni_marj_bp(self) -> int | None:
        return pm.marj_bp(self.yeni, self.bilinen_maliyet)


@dataclass(frozen=True, slots=True)
class FiyatDegisikligi:
    """Uygulanacak tek satır: önizlemedeki ESKİ fiyat da taşınır (yarış denetimi)."""

    product_id: int
    eski: int | None
    yeni: int


@dataclass(frozen=True, slots=True)
class GeriAlmaSatiri:
    product_id: int
    ad: str
    grubun_yazdigi: int | None
    geri_konacak: int | None
    simdiki: int | None
    uygun: bool
    neden: str


@dataclass(frozen=True, slots=True)
class ZamanOlayi:
    zaman_utc: int | None
    eski: int | None
    yeni: int | None
    kaynak: str
    aciklama: str


class PricingService:
    def __init__(self, db: Database, products, categories, audit) -> None:
        self.db = db
        self.products = products
        self.categories = categories
        self.audit = audit

    # ===================== Liste =========================================
    def listele(self, filtre: FiyatFiltresi = FiyatFiltresi(), limit: int = 200,
                offset: int = 0) -> list[FiyatSatiri]:
        urunler = self.products.search(
            text=filtre.metin,
            category_id=filtre.kategori_id,
            brand_id=filtre.marka_id,
            supplier_id=filtre.tedarikci_id,
            no_price=filtre.yalniz_fiyatsiz,
            no_known_cost=filtre.yalniz_maliyetsiz,
            limit=limit,
            offset=offset,
        )
        if not urunler:
            return []
        kimlikler = [u["id"] for u in urunler]
        yer = ",".join("?" * len(kimlikler))
        son_degisim = {
            s["product_id"]: s["t"] for s in self.db.query(
                f"SELECT product_id, MAX(changed_at_utc) AS t FROM price_history "
                f" WHERE product_id IN ({yer}) GROUP BY product_id", kimlikler,
            )
        }
        bilinen = {
            s["id"]: s["c"] for s in self.db.query(
                f"SELECT p.id, CASE WHEN {BILINEN_MALIYET_VAR} THEN p.last_purchase_cost "
                f"  END AS c FROM products p WHERE p.id IN ({yer})", kimlikler,
            )
        }
        markalar = {
            s["id"]: s["name"] for s in self.db.query(
                f"SELECT b.id, b.name FROM brands b WHERE b.id IN ("
                f"  SELECT p.brand_id FROM products p WHERE p.id IN ({yer}))", kimlikler,
            )
        }
        yollar = self.categories.paths()
        return [
            FiyatSatiri(
                product_id=u["id"],
                ad=u["name"],
                kategori=yollar.get(u["category_id"], ""),
                marka=markalar.get(u["brand_id"], ""),
                satis=u["sale_price"],
                bilinen_maliyet=bilinen.get(u["id"]),
                referans_maliyet=u["reference_cost"],
                son_fiyat_degisimi_utc=son_degisim.get(u["id"]),
                son_alis_utc=u["last_purchase_at_utc"],
            )
            for u in urunler
        ]

    # ===================== Önizleme ======================================
    def onizle(self, product_ids: list[int], islem: pm.FiyatIslemi) -> list[OnizlemeSatiri]:
        """Hiçbir şey YAZMAZ; her ürün için yeni fiyat ve durumu hesaplar."""
        kimlikler = list(dict.fromkeys(int(p) for p in product_ids))
        if not kimlikler:
            return []
        yer = ",".join("?" * len(kimlikler))
        satirlar = {
            s["id"]: s for s in self.db.query(
                f"SELECT p.id, p.name, p.sale_price, CASE WHEN {BILINEN_MALIYET_VAR} "
                f"  THEN p.last_purchase_cost END AS c FROM products p "
                f" WHERE p.id IN ({yer})", kimlikler,
            )
        }
        sonuc = []
        for pid in kimlikler:
            s = satirlar.get(pid)
            if s is None:
                continue
            hesap = pm.hesapla(islem, s["sale_price"], s["c"])
            sonuc.append(OnizlemeSatiri(pid, s["name"], s["sale_price"], hesap.yeni,
                                        hesap.durum, s["c"]))
        return sonuc

    # ===================== Uygulama ======================================
    def uygula(
        self,
        degisiklikler: list[FiyatDegisikligi],
        tur: str = TOPLU,
        aciklama: str = "",
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """Değişiklikleri TEK işlemde yazar; grubun kimliğini döner.

        Önce her şey doğrulanır (yazmadan); işlemin içinde fiyatlar önizlemeyle
        karşılaştırılır ve biri bile tutmazsa ``FiyatlarDegisti`` — hiçbir şey
        yazılmaz. ``conn`` verilirse çağıranın işlemine katılır (ör. içe aktarma).
        """
        if tur not in GRUP_ADLARI or tur == GERI_ALMA:
            raise ValueError(f"geçersiz grup türü: {tur}")
        satirlar = {}
        for d in degisiklikler:
            if d.product_id in satirlar:
                raise TopluFiyatHatasi("Aynı ürün iki kez değiştirilemez.")
            if not 0 < int(d.yeni) <= pm.EN_YUKSEK_FIYAT:
                raise TopluFiyatHatasi("Geçersiz fiyat: 0 ya da çok yüksek.")
            satirlar[d.product_id] = d
        satirlar = {k: d for k, d in satirlar.items() if d.yeni != d.eski}
        if not satirlar:
            raise TopluFiyatHatasi("Değişecek fiyat yok.")

        if conn is not None:
            return self._yaz(conn, satirlar, tur, aciklama)
        with self.db.transaction() as own:
            return self._yaz(own, satirlar, tur, aciklama)

    def _yaz(self, conn: sqlite3.Connection, satirlar: dict, tur: str, aciklama: str,
             geri_alinan: int | None = None) -> int:
        kimlikler = list(satirlar)
        yer = ",".join("?" * len(kimlikler))
        simdiki = {
            r["id"]: r["sale_price"] for r in conn.execute(
                f"SELECT id, sale_price FROM products WHERE id IN ({yer})", kimlikler,
            ).fetchall()
        }
        uyusmayan = [k for k, d in satirlar.items()
                     if k not in simdiki or simdiki[k] != d.eski]
        if uyusmayan:
            raise FiyatlarDegisti(len(uyusmayan))

        now = now_utc()
        grup = conn.execute(
            "INSERT INTO price_change_batches(created_at_utc, kind, description, "
            "  product_count, reverses_batch_id) VALUES(?,?,?,?,?)",
            (now, tur, aciklama.strip() or None, len(satirlar), geri_alinan),
        ).lastrowid
        conn.executemany(
            "UPDATE products SET sale_price = ?, updated_at_utc = ? WHERE id = ?",
            [(d.yeni, now, k) for k, d in satirlar.items()],
        )
        conn.executemany(
            "INSERT INTO price_history(product_id, old_price, new_price, changed_at_utc, "
            "  source, reason, batch_id) VALUES(?,?,?,?,'BULK',?,?)",
            [(k, d.eski, d.yeni, now, aciklama.strip() or None, grup)
             for k, d in satirlar.items()],
        )
        ozet = (
            f"{len(satirlar)} ürünün fiyatı değişti ({GRUP_ADLARI[tur].lower()})."
            if geri_alinan is None else
            f"{len(satirlar)} ürünün fiyatı geri alındı (grup {geri_alinan})."
        )
        self.audit.record(
            "TOPLU_FIYAT" if geri_alinan is None else "TOPLU_FIYAT_GERI_AL",
            ozet, "price_batch", grup,
            details={"tur": tur, "urun_sayisi": len(satirlar), "geri_alinan": geri_alinan},
            conn=conn,
        )
        return grup

    # ===================== Geri alma =====================================
    def grup(self, batch_id: int) -> sqlite3.Row | None:
        return self.db.query_one(
            "SELECT b.*, (SELECT r.id FROM price_change_batches r "
            "              WHERE r.reverses_batch_id = b.id) AS geri_alan "
            "  FROM price_change_batches b WHERE b.id = ?", (batch_id,),
        )

    def gruplar(self, limit: int = 20) -> list[sqlite3.Row]:
        """Son toplu değişiklikler (yeniden eskiye), geri alınıp alınmadığıyla."""
        return self.db.query(
            "SELECT b.*, (SELECT r.id FROM price_change_batches r "
            "              WHERE r.reverses_batch_id = b.id) AS geri_alan "
            "  FROM price_change_batches b ORDER BY b.id DESC LIMIT ?", (limit,),
        )

    def geri_alma_onizle(self, batch_id: int) -> list[GeriAlmaSatiri]:
        self._geri_alinabilir(self.db.conn, batch_id)
        return self._geri_alma_satirlari(self.db.conn, batch_id)

    def _geri_alinabilir(self, conn: sqlite3.Connection, batch_id: int) -> sqlite3.Row:
        grup = conn.execute(
            "SELECT * FROM price_change_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        if grup is None:
            raise TopluFiyatHatasi("Toplu değişiklik bulunamadı.")
        if grup["kind"] == GERI_ALMA:
            raise TopluFiyatHatasi(
                "Bir geri alma işlemi geri alınamaz. Gerekirse fiyatları yeniden "
                "toplu olarak değiştirin."
            )
        if conn.execute(
            "SELECT 1 FROM price_change_batches WHERE reverses_batch_id = ?", (batch_id,)
        ).fetchone():
            raise TopluFiyatHatasi("Bu toplu değişiklik zaten geri alındı.")
        return grup

    @staticmethod
    def _geri_alma_satirlari(conn: sqlite3.Connection, batch_id: int) -> list[GeriAlmaSatiri]:
        satirlar = conn.execute(
            "SELECT h.id, h.product_id, h.old_price, h.new_price, p.name, p.sale_price, "
            "       (SELECT MAX(x.id) FROM price_history x "
            "         WHERE x.product_id = h.product_id) AS son_id "
            "  FROM price_history h JOIN products p ON p.id = h.product_id "
            " WHERE h.batch_id = ? ORDER BY p.name_norm, h.id", (batch_id,),
        ).fetchall()
        sonuc = []
        for s in satirlar:
            if s["son_id"] != s["id"]:
                uygun, neden = False, "Sonradan yeniden değiştirilmiş; dokunulmayacak."
            elif s["sale_price"] != s["new_price"]:
                uygun, neden = False, "Fiyatı grubun yazdığından farklı; dokunulmayacak."
            else:
                uygun, neden = True, ""
            sonuc.append(GeriAlmaSatiri(
                s["product_id"], s["name"], s["new_price"], s["old_price"],
                s["sale_price"], uygun, neden,
            ))
        return sonuc

    def geri_al(self, batch_id: int) -> tuple[int, int, int]:
        """Grubu geri alır: (yeni grup kimliği, geri alınan, dokunulmayan)."""
        with self.db.transaction() as conn:
            self._geri_alinabilir(conn, batch_id)
            satirlar = self._geri_alma_satirlari(conn, batch_id)
            uygun = [s for s in satirlar if s.uygun]
            if not uygun:
                raise TopluFiyatHatasi(
                    "Geri alınabilecek fiyat kalmadı: bu ürünlerin hepsi sonradan "
                    "yeniden değiştirilmiş."
                )
            degisiklikler = {
                s.product_id: _GeriKoyma(s.product_id, s.simdiki, s.geri_konacak)
                for s in uygun
            }
            yeni_grup = self._yaz(
                conn, degisiklikler, GERI_ALMA, f"Grup {batch_id} geri alındı",
                geri_alinan=batch_id,
            )
            return yeni_grup, len(uygun), len(satirlar) - len(uygun)

    # ===================== Zaman çizelgesi ===============================
    def zaman_cizelgesi(self, product_id: int) -> list[ZamanOlayi]:
        """Ürünün fiyat geçmişi (yeniden eskiye). Kaydı olmayan ilk fiyat ayrıca."""
        urun = self.products.get(product_id)
        if urun is None:
            return []
        satirlar = self.db.query(
            "SELECT h.*, b.kind, b.description AS grup_aciklama FROM price_history h "
            "  LEFT JOIN price_change_batches b ON b.id = h.batch_id "
            " WHERE h.product_id = ? ORDER BY h.changed_at_utc DESC, h.id DESC",
            (product_id,),
        )
        olaylar = [
            ZamanOlayi(
                s["changed_at_utc"], s["old_price"], s["new_price"],
                GRUP_ADLARI.get(s["kind"], ELLE) if s["batch_id"] else ELLE,
                s["reason"] or s["grup_aciklama"] or "",
            )
            for s in satirlar
        ]
        ilk = satirlar[-1]["old_price"] if satirlar else urun["sale_price"]
        if ilk is not None:
            olaylar.append(ZamanOlayi(
                None, None, ilk, "ilk fiyat (kayıt yok)",
                "Bu fiyatın ne zaman girildiği kayıtlı değil.",
            ))
        return olaylar


@dataclass(frozen=True, slots=True)
class _GeriKoyma:
    """Geri almada yazılacak satır (yeni fiyat ``None`` olabilir: fiyatsız ürün)."""

    product_id: int
    eski: int | None
    yeni: int | None
