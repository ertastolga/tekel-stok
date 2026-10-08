"""Sepetli Satış: taslak sepet ve atomik ödeme.

Sepet bir TASLAKTIR. Sepette ürün varken stok ve ciro DEĞİŞMEZ; hiçbir şey
satılmış sayılmaz. Yalnızca "Satışı Tamamla" tek bir işlemde her şeyi yazar.

Taslak diske kaydedilir ki elektrik kesilse ya da uygulama kapansa bile
kaybolmasın. Ama açılışta KENDİLİĞİNDEN TAMAMLANMAZ — yarım kalmış bir
finansal işlem kullanıcı onayı olmadan asla işlenmez; kullanıcıya "Devam Et"
ya da "Sepeti Sil" seçeneği sunulur.

Fiyat bütünlüğü (V1.2): ekranda görünen = ödemesi alınan = kaydedilen.
Sepet satırı fiyatı okutma anında yakalar; fiyat sonradan değişirse
``validate`` bunu bildirir, ``checkout`` aynı işlem içinde yeniden denetler ve
uyuşmazlıkta HİÇBİR ŞEY yazmaz (``FiyatDegisti``). Fiyat asla sessizce
düzeltilmez: ``apply_current_prices`` açık bir kullanıcı eylemidir.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field

from app.core.clock import local_now, now_utc
from app.core.db import Database
from app.core.errors import (
    BekletmeSiniri,
    BosSepet,
    EskiOturumSepeti,
    FiyatDegisti,
    FiyatiYokUrun,
    PasifUrun,
)
from app.core.money import format_tl
from app.services.sale_service import SaleLineSpec

log = logging.getLogger(__name__)


@dataclass(slots=True)
class CartLine:
    product_id: int
    product_name: str
    quantity: int
    unit_price: int
    barcode_used: str | None = None
    multiplier: int = 1

    @property
    def line_total(self) -> int:
        return self.unit_price * self.quantity


@dataclass(slots=True)
class Cart:
    """Bellekteki sepet. Arayüz bu nesneyi çizer, SQL yazmaz."""

    draft_id: int | None = None
    lines: list[CartLine] = field(default_factory=list)
    #: Sepetin ait olduğu veritabanı açılışı (``Database.generation``).
    generation: int | None = None

    @property
    def total(self) -> int:
        return sum(line.line_total for line in self.lines)

    @property
    def item_count(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def is_empty(self) -> bool:
        return not self.lines

    def find(self, product_id: int) -> CartLine | None:
        for line in self.lines:
            if line.product_id == product_id:
                return line
        return None

    def add(
        self,
        product_id: int,
        product_name: str,
        unit_price: int,
        quantity: int = 1,
        barcode_used: str | None = None,
        multiplier: int = 1,
    ) -> CartLine:
        """Aynı ürün tekrar okutulursa MEVCUT SATIRIN adedi artar.

        Böylece dükkân sahibi tek bir şişeyi 10 kez okutabilir; miktar kutusuna
        tıklayıp "10" yazmak zorunda kalmaz.
        """
        line = self.find(product_id)
        if line is None:
            line = CartLine(
                product_id, product_name, quantity, unit_price, barcode_used, multiplier
            )
            self.lines.append(line)
        else:
            line.quantity += quantity
        return line

    def set_quantity(self, product_id: int, quantity: int) -> None:
        line = self.find(product_id)
        if line is None:
            return
        if quantity <= 0:
            self.lines.remove(line)
        else:
            line.quantity = quantity

    def remove(self, product_id: int) -> None:
        line = self.find(product_id)
        if line is not None:
            self.lines.remove(line)

    def clear(self) -> None:
        self.lines.clear()


#: Taslak türleri (şema v2). AUTOSAVE: üzerinde çalışılan sepetin otomatik
#: kaydı (açılışta "devam et?" sorulur). PARKED: kasiyerin beklettiği sepet.
TASLAK_OTOMATIK = "AUTOSAVE"
TASLAK_BEKLEYEN = "PARKED"

#: Aynı anda en fazla bu kadar sepet bekletilir (kasa ekranı sade kalsın).
BEKLETME_SINIRI = 9

#: Sepet satırı sorun türleri (Türkçe tanımlayıcılar).
SORUN_FIYAT_DEGISTI = "FIYAT_DEGISTI"
SORUN_PASIF = "PASIF"
SORUN_FIYATSIZ = "FIYATSIZ"
SORUN_BULUNAMADI = "BULUNAMADI"


@dataclass(frozen=True, slots=True)
class LineIssue:
    """Ödemeden önce çözülmesi gereken bir sepet satırı sorunu."""

    product_id: int
    product_name: str
    kind: str
    cart_price: int
    current_price: int | None = None

    @property
    def message(self) -> str:
        if self.kind == SORUN_FIYAT_DEGISTI:
            return (
                f"Fiyat değişti: {format_tl(self.cart_price)} → "
                f"{format_tl(self.current_price or 0)}"
            )
        if self.kind == SORUN_PASIF:
            return "Ürün kullanımdan kaldırılmış — sepetten çıkarın"
        if self.kind == SORUN_FIYATSIZ:
            return "Ürünün satış fiyatı silinmiş — sepetten çıkarın"
        return "Ürün bulunamadı — sepetten çıkarın"


class CartService:
    def __init__(self, db: Database, settings, sales, products) -> None:
        self.db = db
        self.settings = settings
        self.sales = sales
        self.products = products

    # -- Sepet kurma -------------------------------------------------------
    def new_cart(self) -> Cart:
        """Bu veritabanı açılışına ait boş sepet."""
        return Cart(generation=self.db.generation)

    def add_product(self, cart: Cart, product_id: int, quantity: int = 1,
                    barcode_used: str | None = None, multiplier: int = 1) -> CartLine:
        """Ürünü sepete ekler; fiyat ve durum burada doğrulanır.

        Fiyatı olmayan ya da pasif ürün sepete BİLE girmez — kasada sürpriz
        olmasın diye hata en erken noktada verilir.
        """
        urun = self.products.get(product_id)
        if urun is None:
            raise PasifUrun()
        if not urun["is_active"]:
            raise PasifUrun(urun["name"])
        if urun["sale_price"] is None:
            raise FiyatiYokUrun(urun["name"])
        if cart.generation is None:
            cart.generation = self.db.generation
        return cart.add(
            product_id, urun["name"], int(urun["sale_price"]), quantity,
            barcode_used, multiplier,
        )

    # -- Fiyat bütünlüğü ---------------------------------------------------
    def validate(self, cart: Cart) -> list[LineIssue]:
        """Sepeti GÜNCEL ürün kayıtlarıyla karşılaştırır (tek sorgu).

        Ödeme onayından HEMEN önce, taslak geri yüklenince ve sepet her
        değiştiğinde çağrılır. Hiçbir şeyi düzeltmez; yalnızca bildirir.
        """
        return self._sorunlar(self.db.conn, cart)

    def _sorunlar(self, conn: sqlite3.Connection, cart: Cart) -> list[LineIssue]:
        if cart.is_empty:
            return []
        kimlikler = sorted({line.product_id for line in cart.lines})
        yer = ",".join("?" * len(kimlikler))
        guncel = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                f"SELECT id, is_active, sale_price FROM products WHERE id IN ({yer})",
                kimlikler,
            )
        }
        sorunlar: list[LineIssue] = []
        for line in cart.lines:
            kayit = guncel.get(line.product_id)
            if kayit is None:
                tur, fiyat = SORUN_BULUNAMADI, None
            elif not kayit[0]:
                tur, fiyat = SORUN_PASIF, None
            elif kayit[1] is None:
                tur, fiyat = SORUN_FIYATSIZ, None
            elif int(kayit[1]) != line.unit_price:
                tur, fiyat = SORUN_FIYAT_DEGISTI, int(kayit[1])
            else:
                continue
            sorunlar.append(
                LineIssue(line.product_id, line.product_name, tur, line.unit_price, fiyat)
            )
        return sorunlar

    def apply_current_prices(self, cart: Cart) -> int:
        """AÇIK kullanıcı eylemi: fiyatı değişen satırlara güncel fiyatı yazar.

        Pasif / fiyatsız / silinmiş ürün satırlarına dokunmaz (onlar sepetten
        çıkarılmalıdır). Değişen satır sayısını döner.
        """
        degisen = 0
        for sorun in self.validate(cart):
            if sorun.kind != SORUN_FIYAT_DEGISTI or sorun.current_price is None:
                continue
            line = cart.find(sorun.product_id)
            if line is not None:
                line.unit_price = sorun.current_price
                degisen += 1
        return degisen

    # -- Taslak kalıcılığı -------------------------------------------------
    def save_draft(self, cart: Cart, label: str | None = None,
                   kind: str = TASLAK_OTOMATIK) -> int:
        """Sepeti diske yazar. Stok ve ciroya HİÇBİR ETKİSİ YOKTUR.

        * Taslak yazısı veriyi "değişti" saymaz (``mutating=False``): sepet
          her değiştiğinde kaydedilir ve bu, otomatik yedeği tetiklememelidir.
        * Yalnızca AÇIK (``OPEN``) taslak güncellenir; kapanmış bir taslağa
          (satışa dönüşmüş, silinmiş) asla yazılmaz — yenisi açılır.
        * Başka bir veritabanı açılışına ait sepet (ör. yedek geri yüklendi)
          reddedilir: eski sepet YENİ veriye karışmaz.
        """
        if cart.generation is None:
            cart.generation = self.db.generation
        elif cart.generation != self.db.generation:
            log.warning(
                "Sepet taslağı kaydedilmedi: sepet açılışı %s, veritabanı açılışı %s",
                cart.generation, self.db.generation,
            )
            raise EskiOturumSepeti()
        now = now_utc()
        with self.db.transaction(mutating=False) as conn:
            if cart.draft_id is not None:
                guncellenen = conn.execute(
                    "UPDATE cart_drafts SET updated_at_utc = ?, label = COALESCE(?, label), "
                    "  kind = ? WHERE id = ? AND status = 'OPEN'",
                    (now, label, kind, cart.draft_id),
                ).rowcount
                if guncellenen == 0:
                    cart.draft_id = None
            if cart.draft_id is None:
                cart.draft_id = conn.execute(
                    "INSERT INTO cart_drafts(label, status, created_at_utc, updated_at_utc, "
                    "  kind) VALUES(?, 'OPEN', ?, ?, ?)",
                    (label, now, now, kind),
                ).lastrowid
            conn.execute(
                "DELETE FROM cart_draft_lines WHERE draft_id = ?", (cart.draft_id,)
            )
            conn.executemany(
                "INSERT INTO cart_draft_lines(draft_id, line_no, product_id, quantity, "
                "  unit_price, product_name_snapshot, barcode_used, barcode_multiplier) "
                "VALUES(?,?,?,?,?,?,?,?)",
                [
                    (cart.draft_id, sira, line.product_id, line.quantity, line.unit_price,
                     line.product_name, line.barcode_used, max(1, int(line.multiplier)))
                    for sira, line in enumerate(cart.lines, start=1)
                ],
            )
        return cart.draft_id

    # -- Bekleyen sepetler (F1) --------------------------------------------
    def park(self, cart: Cart) -> int:
        """Sepeti BEKLETİR: "Müşteri n · 14:32" adıyla saklanır.

        Kasiyer yeni müşteriye hemen başlayabilir; bekleyen sepet yeniden
        açılınca fiyatları doğrulanır, ASLA kendiliğinden onarılmaz. Çağıran,
        bekletilen sepetin yerine boş bir sepet koyar.
        """
        if cart.is_empty:
            raise BosSepet()
        if self.parked_count() >= BEKLETME_SINIRI:
            raise BekletmeSiniri(BEKLETME_SINIRI)
        an = local_now()
        bugun = self.settings.calendar().today()
        sira = self._bugun_bekletilen(bugun) + 1
        etiket = f"Müşteri {sira} · {an.strftime('%H:%M')}"
        draft_id = self.save_draft(cart, label=etiket, kind=TASLAK_BEKLEYEN)
        with self.db.transaction(mutating=False) as conn:
            conn.execute(
                "UPDATE cart_drafts SET parked_at_utc = ? WHERE id = ?",
                (now_utc(), draft_id),
            )
        return draft_id

    def _bugun_bekletilen(self, bugun: str) -> int:
        """Bu iş gününde bekletilmiş sepet sayısı (etiket numarası için).

        Yalnızca son 36 saatte bekletilenlere bakılır (bir iş günü en çok ~25
        saattir): satışa dönen taslaklar tabloda kalır ve tablo yıllar içinde
        satış sayısı kadar büyür; arama ``ix_cart_drafts_parked`` ile sınırlıdır.
        """
        takvim = self.settings.calendar()
        satirlar = self.db.query(
            "SELECT parked_at_utc FROM cart_drafts WHERE kind = 'PARKED' "
            "  AND parked_at_utc IS NOT NULL AND parked_at_utc >= ? "
            " ORDER BY parked_at_utc DESC LIMIT 200",
            (now_utc() - 36 * 3600,),
        )
        from datetime import datetime

        return sum(
            1 for r in satirlar
            if takvim.business_date_for(datetime.fromtimestamp(r["parked_at_utc"])) == bugun
        )

    def parked_count(self) -> int:
        return int(self.db.scalar(
            "SELECT COUNT(*) FROM cart_drafts WHERE status = 'OPEN' AND kind = 'PARKED'",
            default=0,
        ))

    def parked_carts(self) -> list[sqlite3.Row]:
        """Bekleyen sepetler, bekletilme sırasıyla (eski önce)."""
        return self.db.query(
            "SELECT d.*, "
            "  (SELECT COUNT(*) FROM cart_draft_lines l WHERE l.draft_id = d.id) AS satir_sayisi, "
            "  (SELECT COALESCE(SUM(l.quantity), 0) FROM cart_draft_lines l "
            "     WHERE l.draft_id = d.id) AS urun_adedi, "
            "  (SELECT COALESCE(SUM(l.quantity * l.unit_price), 0) FROM cart_draft_lines l "
            "     WHERE l.draft_id = d.id) AS toplam "
            "  FROM cart_drafts d WHERE d.status = 'OPEN' AND d.kind = 'PARKED' "
            " ORDER BY d.parked_at_utc, d.id"
        )

    def resume_parked(self, draft_id: int) -> tuple[Cart, list[LineIssue]]:
        """Bekleyen sepeti açar: üzerinde çalışılan sepet olur (AUTOSAVE).

        Saklanan birim fiyatlar KORUNUR; güncel kayıtlarla farkı ``validate``
        bildirir (fiyat değişti / pasif / fiyatsız / silinmiş). Hiçbiri
        kendiliğinden düzeltilmez.
        """
        with self.db.transaction(mutating=False) as conn:
            acik = conn.execute(
                "UPDATE cart_drafts SET kind = 'AUTOSAVE', updated_at_utc = ? "
                " WHERE id = ? AND status = 'OPEN' AND kind = 'PARKED'",
                (now_utc(), draft_id),
            ).rowcount
        if not acik:
            raise BosSepet()
        cart = self.load_draft(draft_id)
        return cart, self.validate(cart)

    def autosave(self, cart: Cart) -> int | None:
        """Sepetin GÜNCEL hâlini diske yansıtır (sayfa bunu gecikmeli çağırır).

        Boşalmış bir sepetin taslağı iptal edilir: aksi hâlde "−" / "✕" ile
        boşaltılan sepet, bir sonraki açılışta hayalet bir taslak olarak geri
        gelirdi.
        """
        if cart.is_empty:
            if cart.draft_id is not None:
                self.discard_draft(cart.draft_id)
                cart.draft_id = None
            return None
        return self.save_draft(cart)

    def open_drafts(self, kind: str | None = None) -> list[sqlite3.Row]:
        """Açık taslaklar; ``kind`` verilirse yalnızca o tür (kurtarma AUTOSAVE)."""
        kosul = "" if kind is None else " AND d.kind = ?"
        return self.db.query(
            "SELECT d.*, (SELECT COUNT(*) FROM cart_draft_lines l "
            "               WHERE l.draft_id = d.id) AS satir_sayisi "
            "  FROM cart_drafts d WHERE d.status = 'OPEN'" + kosul +
            " ORDER BY d.updated_at_utc DESC",
            () if kind is None else (kind,),
        )

    def load_draft(self, draft_id: int) -> Cart:
        rows = self.db.query(
            "SELECT l.*, p.name FROM cart_draft_lines l "
            "  LEFT JOIN products p ON p.id = l.product_id "
            " WHERE l.draft_id = ? ORDER BY l.line_no",
            (draft_id,),
        )
        cart = Cart(draft_id=draft_id, generation=self.db.generation)
        for row in rows:
            cart.lines.append(
                CartLine(
                    row["product_id"],
                    row["name"] or row["product_name_snapshot"] or "?",
                    row["quantity"], row["unit_price"],
                    row["barcode_used"], int(row["barcode_multiplier"] or 1),
                )
            )
        return cart

    def discard_draft(self, draft_id: int) -> None:
        """AÇIK taslağı iptal eder; kapanmış taslağa dokunmaz."""
        with self.db.transaction(mutating=False) as conn:
            iptal = conn.execute(
                "UPDATE cart_drafts SET status = 'CANCELLED', updated_at_utc = ? "
                " WHERE id = ? AND status = 'OPEN'",
                (now_utc(), draft_id),
            ).rowcount
            if iptal:
                conn.execute(
                    "DELETE FROM cart_draft_lines WHERE draft_id = ?", (draft_id,)
                )

    # -- Ödeme -------------------------------------------------------------
    def checkout(
        self,
        cart: Cart,
        payment_method: str | None = None,
        discount_total: int = 0,
        rounding_adjustment: int = 0,
    ):
        """Sepeti ATOMİK olarak satışa çevirir.

        Satış, stok hareketleri, özet tabloları ve taslağın kapatılması AYNI
        işlemdedir: ya hepsi olur ya hiçbiri.

        Sepetteki fiyatlar, satış yazılmadan HEMEN önce AYNI işlem içinde
        güncel fiyatlarla karşılaştırılır: uyuşmazlıkta ``FiyatDegisti`` ve tam
        geri alma. Böylece kaydedilen tutar, ekranda görünen ve ödemesi alınan
        tutarın ta kendisidir.
        """
        if cart.is_empty:
            raise BosSepet()

        with self.db.transaction() as conn:
            fiyat_sorunlari = [
                s for s in self._sorunlar(conn, cart) if s.kind == SORUN_FIYAT_DEGISTI
            ]
            if fiyat_sorunlari:
                raise FiyatDegisti(fiyat_sorunlari)
            sonuc = self.sales.commit_sale(
                [
                    SaleLineSpec(
                        line.product_id, line.quantity, line.barcode_used, line.multiplier
                    )
                    for line in cart.lines
                ],
                mode="SEPET",
                payment_method=payment_method,
                discount_total=discount_total,
                rounding_adjustment=rounding_adjustment,
            )
            if cart.draft_id is not None:
                conn.execute(
                    "DELETE FROM cart_draft_lines WHERE draft_id = ?", (cart.draft_id,)
                )
                conn.execute(
                    "UPDATE cart_drafts SET status = 'CHECKED_OUT', updated_at_utc = ?, "
                    "  checked_out_sale_id = ? WHERE id = ?",
                    (now_utc(), sonuc.sale_id, cart.draft_id),
                )
        cart.clear()
        cart.draft_id = None
        return sonuc
