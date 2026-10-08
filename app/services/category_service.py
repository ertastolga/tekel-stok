"""Kategoriler: en çok iki düzeyli, Türkçe duyarlı, geçmişe saygılı.

Kurallar (plan §4 B, §5.10):
  * En çok İKİ düzey (üst > alt). Alt kategorinin altına kategori eklenemez.
  * Aynı üst kategori altında aynı ad (Türkçe/aksan duyarsız: "Bira", "BİRA",
    "bira ") YASAKTIR — tek SERT engel budur.
  * Benzer adlar ("biralar", "Viskiler", başka üstte aynı ad, 1–2 harf farkı)
    yalnızca UYARIDIR; hiçbir şey kendiliğinden birleştirilmez.
  * Kullanımdaki alt kategorisi olan kategori kaldırılamaz (hiçbir şey
    ulaşılmaz hâle gelmez). Kaldırılan kategorinin ürünleri kategorisini korur.
  * Birleştirme ürünleri hedefe taşır ve kaynağı kaldırır (denetim kaydıyla).
  * Şablon: yeni kurulumlar §6.1 ağacıyla gelir. Mevcut kurulumda HİÇBİR ŞEY
    kendiliğinden değişmez; "Şablondan eksikleri ekle" önce önizleme gösterir,
    yeniden adlandırma ve ürün taşıma isteğe bağlıdır; tekrar çalıştırmak
    hiçbir şey eklemez.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from app.core.clock import now_utc
from app.core.errors import DomainError
from app.core.schema import KATEGORI_SABLONU
from app.core.tr import normalize_name

#: Şablondaki üst kategorilerin mevcut kurulumlardaki eski adları.
SABLON_ESADLARI = {"Soğuk İçecek": ("İçecekler",)}


class KategoriHatasi(DomainError):
    """Kategori işlemi yapılamadı (ileti kullanıcıya gösterilir)."""


@dataclass(frozen=True, slots=True)
class KategoriDugumu:
    row: sqlite3.Row
    urun_sayisi: int
    toplam_urun: int
    altlar: list["KategoriDugumu"] = field(default_factory=list)

    @property
    def id(self) -> int:
        return int(self.row["id"])

    @property
    def name(self) -> str:
        return self.row["name"]

    @property
    def active(self) -> bool:
        return bool(self.row["active"])


#: Şablon adımı türleri (Türkçe tanımlayıcılar).
ADIM_EKLE = "EKLE"
ADIM_YENIDEN_ADLANDIR = "YENIDEN_ADLANDIR"
ADIM_TASI = "TASI"
ADIM_URUN_TASI = "URUN_TASI"
#: Kullanıcının açıkça seçmesi gereken adımlar.
ISTEGE_BAGLI = {ADIM_YENIDEN_ADLANDIR, ADIM_URUN_TASI}


@dataclass(slots=True)
class SablonAdimi:
    tur: str
    aciklama: str
    ad: str = ""
    ust_ad: str | None = None
    kategori_id: int | None = None
    hedef_ad: str | None = None
    secili: bool = True


def _mesafe(a: str, b: str) -> int:
    """Levenshtein uzaklığı (kısa adlar için; kategori sayısı küçüktür)."""
    if a == b:
        return 0
    onceki = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        simdiki = [i]
        for j, cb in enumerate(b, start=1):
            simdiki.append(min(
                onceki[j] + 1, simdiki[j - 1] + 1, onceki[j - 1] + (ca != cb),
            ))
        onceki = simdiki
    return onceki[-1]


def _cogul_govde(ad: str) -> str | None:
    for ek in ("lar", "ler"):
        if ad.endswith(ek) and len(ad) > len(ek) + 1:
            return ad[: -len(ek)]
    return None


def _esik(kisa_uzunluk: int) -> int:
    """§5.10: kısa ad ≤ 4 karakterse uzaklık uyarısı yok; 5–7 → 1; ≥ 8 → 2."""
    if kisa_uzunluk <= 4:
        return -1
    return 1 if kisa_uzunluk <= 7 else 2


class CategoryService:
    def __init__(self, db, audit) -> None:
        self.db = db
        self.audit = audit

    # ===================== Okuma =========================================
    def get(self, category_id: int) -> sqlite3.Row | None:
        return self.db.query_one("SELECT * FROM categories WHERE id = ?", (category_id,))

    def _gerekli(self, category_id: int) -> sqlite3.Row:
        satir = self.get(category_id)
        if satir is None:
            raise KategoriHatasi("Kategori bulunamadı.")
        return satir

    def path(self, category_id: int | None) -> str:
        if category_id is None:
            return ""
        satir = self.get(category_id)
        if satir is None:
            return ""
        if satir["parent_id"] is None:
            return satir["name"]
        ust = self.get(satir["parent_id"])
        return f"{ust['name']} > {satir['name']}" if ust else satir["name"]

    def tree(self, include_inactive: bool = False) -> list[KategoriDugumu]:
        """Üst kategoriler ve altları, ürün sayılarıyla (yalnızca aktif ürünler).

        ``toplam_urun`` üst kategoride altların ürünlerini de içerir.
        """
        satirlar = self.db.query(
            "SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.category_id = c.id "
            "                AND p.is_active = 1) AS urun "
            "  FROM categories c ORDER BY IFNULL(c.parent_id, 0), c.sort_order, c.name_norm"
        )
        if not include_inactive:
            satirlar = [s for s in satirlar if s["active"]]
        altlar: dict[int, list[sqlite3.Row]] = {}
        for satir in satirlar:
            if satir["parent_id"] is not None:
                altlar.setdefault(satir["parent_id"], []).append(satir)
        agac = []
        for satir in satirlar:
            if satir["parent_id"] is not None:
                continue
            cocuklar = [
                KategoriDugumu(c, int(c["urun"]), int(c["urun"]))
                for c in altlar.get(satir["id"], [])
            ]
            agac.append(KategoriDugumu(
                satir, int(satir["urun"]),
                int(satir["urun"]) + sum(c.urun_sayisi for c in cocuklar), cocuklar,
            ))
        return agac

    def recent_for_products(self, limit: int = 5) -> list[sqlite3.Row]:
        """Son eklenen ürünlerde kullanılan aktif kategoriler (hızlı seçim)."""
        return self.db.query(
            "SELECT c.* FROM categories c JOIN ("
            "  SELECT category_id, MAX(id) AS son FROM products "
            "   WHERE category_id IS NOT NULL GROUP BY category_id"
            ") k ON k.category_id = c.id WHERE c.active = 1 "
            " ORDER BY k.son DESC LIMIT ?",
            (max(1, limit),),
        )

    def uncategorized_count(self) -> int:
        return int(self.db.scalar(
            "SELECT COUNT(*) FROM products WHERE is_active = 1 AND category_id IS NULL",
            default=0,
        ))

    def search(self, text: str) -> list[tuple[sqlite3.Row, str]]:
        """(kategori, yol) — Türkçe/aksan duyarsız alt dizi araması."""
        igne = normalize_name(text)
        if not igne:
            return []
        satirlar = self.db.query(
            "SELECT * FROM categories WHERE active = 1 AND name_norm LIKE ? "
            " ORDER BY name_norm LIMIT 50",
            (f"%{igne}%",),
        )
        return [(s, self.path(s["id"])) for s in satirlar]

    # ===================== Benzerlik uyarıları ===========================
    def similar_names(self, name: str, parent_id: int | None = None,
                      exclude_id: int | None = None) -> list[str]:
        """§5.10: engellemeyen, sade Türkçe benzerlik uyarıları."""
        ad = normalize_name(name)
        if not ad:
            return []
        uyarilar: list[str] = []
        ust = self.get(parent_id) if parent_id is not None else None
        for satir in self.db.query("SELECT * FROM categories WHERE active = 1"):
            if exclude_id is not None and satir["id"] == exclude_id:
                continue
            diger = satir["name_norm"]
            ayni_ust = satir["parent_id"] == parent_id
            # Üst/alt aynı ad (Tütün > Tütün, Diğer > Diğer) uyarı değildir —
            # her iki yönde de (alt eklenirken üstü, üst denetlenirken altı).
            if ust is not None and satir["id"] == ust["id"]:
                continue
            if exclude_id is not None and satir["parent_id"] == exclude_id:
                continue
            yol = self.path(satir["id"])
            if diger == ad:
                if not ayni_ust:
                    uyarilar.append(f"Aynı ad başka yerde de var: {yol}.")
                continue
            govde_a, govde_b = _cogul_govde(ad), _cogul_govde(diger)
            if (govde_a and govde_a == diger) or (govde_b and govde_b == ad):
                uyarilar.append(f"Tekil/çoğul benzeri var: {yol}.")
                continue
            kelimeler_a, kelimeler_b = set(ad.split()), set(diger.split())
            if kelimeler_a <= kelimeler_b or kelimeler_b <= kelimeler_a:
                continue                         # tam kelime içerme: uyarı yok
            esik = _esik(min(len(ad), len(diger)))
            if esik >= 0 and _mesafe(ad, diger) <= esik:
                uyarilar.append(f"Çok benzer bir ad var: {yol}.")
        return uyarilar

    # ===================== Yazma =========================================
    def _ad_denetle(self, conn, ad: str, parent_id: int | None,
                    exclude_id: int | None = None) -> str:
        ad = (ad or "").strip()
        if not ad:
            raise KategoriHatasi("Kategori adı boş olamaz.")
        ayni = conn.execute(
            "SELECT id, active FROM categories WHERE IFNULL(parent_id, 0) = ? "
            "  AND name_norm = ?",
            (parent_id or 0, normalize_name(ad)),
        ).fetchone()
        if ayni is not None and ayni["id"] != exclude_id:
            if not ayni["active"]:
                raise KategoriHatasi(
                    f"\"{ad}\" adlı kategori kullanımdan kaldırılmış. Yeniden "
                    "kullanıma alabilirsiniz."
                )
            raise KategoriHatasi(f"Bu yerde \"{ad}\" adlı bir kategori zaten var.")
        return ad

    def _ust_denetle(self, conn, parent_id: int | None) -> None:
        if parent_id is None:
            return
        ust = conn.execute(
            "SELECT * FROM categories WHERE id = ?", (parent_id,)
        ).fetchone()
        if ust is None:
            raise KategoriHatasi("Üst kategori bulunamadı.")
        if ust["parent_id"] is not None:
            raise KategoriHatasi(
                "Kategoriler en çok iki düzeydir: alt kategorinin altına kategori "
                "eklenemez."
            )
        if not ust["active"]:
            raise KategoriHatasi("Üst kategori kullanımdan kaldırılmış.")

    def create(self, name: str, parent_id: int | None = None) -> int:
        with self.db.transaction() as conn:
            self._ust_denetle(conn, parent_id)
            ad = self._ad_denetle(conn, name, parent_id)
            sira = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM categories "
                " WHERE IFNULL(parent_id, 0) = ?",
                (parent_id or 0,),
            ).fetchone()[0]
            kimlik = conn.execute(
                "INSERT INTO categories(parent_id, name, name_norm, sort_order, "
                "  created_at_utc) VALUES(?,?,?,?,?)",
                (parent_id, ad, normalize_name(ad), sira, now_utc()),
            ).lastrowid
            self.audit.record("KATEGORI_EKLE", f"\"{ad}\" kategorisi eklendi.",
                              "category", kimlik, conn=conn)
            return kimlik

    def rename(self, category_id: int, name: str) -> None:
        with self.db.transaction() as conn:
            satir = self._gerekli(category_id)
            ad = self._ad_denetle(conn, name, satir["parent_id"], exclude_id=category_id)
            conn.execute(
                "UPDATE categories SET name = ?, name_norm = ? WHERE id = ?",
                (ad, normalize_name(ad), category_id),
            )
            self.audit.record(
                "KATEGORI_AD", f"\"{satir['name']}\" kategorisinin adı \"{ad}\" oldu.",
                "category", category_id, conn=conn,
            )

    def deactivate(self, category_id: int) -> None:
        """Kaldırır (pasif). Kullanımdaki alt kategorisi varsa REDDEDER."""
        with self.db.transaction() as conn:
            satir = self._gerekli(category_id)
            alt = conn.execute(
                "SELECT COUNT(*) FROM categories WHERE parent_id = ? AND active = 1",
                (category_id,),
            ).fetchone()[0]
            if alt:
                raise KategoriHatasi(
                    "Bu kategorinin kullanımdaki alt kategorileri var. Önce onları "
                    "kaldırın ya da başka bir üst kategoriye taşıyın."
                )
            conn.execute("UPDATE categories SET active = 0 WHERE id = ?", (category_id,))
            self.audit.record(
                "KATEGORI_KALDIR", f"\"{satir['name']}\" kategorisi kullanımdan kaldırıldı.",
                "category", category_id, conn=conn,
            )

    def reactivate(self, category_id: int) -> None:
        with self.db.transaction() as conn:
            satir = self._gerekli(category_id)
            if satir["parent_id"] is not None:
                ust = self.get(satir["parent_id"])
                if ust is not None and not ust["active"]:
                    raise KategoriHatasi(
                        "Önce üst kategoriyi yeniden kullanıma alın."
                    )
            conn.execute("UPDATE categories SET active = 1 WHERE id = ?", (category_id,))
            self.audit.record(
                "KATEGORI_GERI_AL", f"\"{satir['name']}\" kategorisi yeniden kullanımda.",
                "category", category_id, conn=conn,
            )

    def move(self, category_id: int, new_parent_id: int | None) -> None:
        """Kategoriyi başka bir üstün altına (ya da üst düzeye) taşır."""
        with self.db.transaction() as conn:
            satir = self._gerekli(category_id)
            if new_parent_id == category_id:
                raise KategoriHatasi("Kategori kendi altına taşınamaz.")
            if new_parent_id is not None:
                self._ust_denetle(conn, new_parent_id)
                cocuk = conn.execute(
                    "SELECT COUNT(*) FROM categories WHERE parent_id = ?", (category_id,)
                ).fetchone()[0]
                if cocuk:
                    raise KategoriHatasi(
                        "Alt kategorileri olan bir kategori başka bir kategorinin "
                        "altına taşınamaz (en çok iki düzey)."
                    )
            self._ad_denetle(conn, satir["name"], new_parent_id, exclude_id=category_id)
            conn.execute(
                "UPDATE categories SET parent_id = ? WHERE id = ?",
                (new_parent_id, category_id),
            )
            self.audit.record(
                "KATEGORI_TASI", f"\"{satir['name']}\" kategorisi taşındı: "
                f"{self.path(category_id)}.", "category", category_id, conn=conn,
            )

    def merge(self, source_id: int, target_id: int) -> int:
        """Kaynağın ürünlerini hedefe taşır ve kaynağı kaldırır; taşınan sayıyı döner."""
        if source_id == target_id:
            raise KategoriHatasi("Bir kategori kendisiyle birleştirilemez.")
        with self.db.transaction() as conn:
            kaynak = self._gerekli(source_id)
            hedef = self._gerekli(target_id)
            if not hedef["active"]:
                raise KategoriHatasi("Hedef kategori kullanımdan kaldırılmış.")
            if hedef["parent_id"] == source_id:
                raise KategoriHatasi("Bir kategori kendi alt kategorisine birleştirilemez.")
            alt = conn.execute(
                "SELECT COUNT(*) FROM categories WHERE parent_id = ? AND active = 1",
                (source_id,),
            ).fetchone()[0]
            if alt:
                raise KategoriHatasi(
                    "Alt kategorileri olan bir kategori birleştirilemez; önce alt "
                    "kategorileri taşıyın."
                )
            tasinan = conn.execute(
                "UPDATE products SET category_id = ?, updated_at_utc = ? "
                " WHERE category_id = ?",
                (target_id, now_utc(), source_id),
            ).rowcount
            conn.execute("UPDATE categories SET active = 0 WHERE id = ?", (source_id,))
            self.audit.record(
                "KATEGORI_BIRLESTIR",
                f"\"{kaynak['name']}\" kategorisi \"{hedef['name']}\" ile birleştirildi "
                f"({tasinan} ürün taşındı).",
                "category", source_id, details={"hedef": target_id, "urun": tasinan},
                conn=conn,
            )
            return tasinan

    # ===================== Şablon ========================================
    def _bul(self, ad: str, parent_id: int | None) -> sqlite3.Row | None:
        return self.db.query_one(
            "SELECT * FROM categories WHERE IFNULL(parent_id, 0) = ? AND name_norm = ?",
            (parent_id or 0, normalize_name(ad)),
        )

    def template_preview(self) -> list[SablonAdimi]:
        """Şablonda olup bu kurulumda olmayanlar. Hiçbir şey YAZILMAZ."""
        adimlar: list[SablonAdimi] = []
        for ust_ad, cocuklar in KATEGORI_SABLONU:
            ust = self._bul(ust_ad, None)
            if ust is None:
                for es in SABLON_ESADLARI.get(ust_ad, ()):
                    eski = self._bul(es, None)
                    if eski is not None:
                        ust = eski
                        adimlar.append(SablonAdimi(
                            ADIM_YENIDEN_ADLANDIR,
                            f"\"{es}\" üst kategorisinin adı \"{ust_ad}\" olsun "
                            "(isteğe bağlı)",
                            ad=ust_ad, kategori_id=eski["id"], secili=False,
                        ))
                        break
            if ust is None:
                adimlar.append(SablonAdimi(
                    ADIM_EKLE, f"Üst kategori ekle: {ust_ad}", ad=ust_ad))
            ust_id = ust["id"] if ust is not None else None
            gorunen_ust = ust["name"] if ust is not None else ust_ad
            for cocuk in cocuklar:
                if ust_id is not None and self._bul(cocuk, ust_id) is not None:
                    continue
                baska = self.db.query_one(
                    "SELECT * FROM categories WHERE name_norm = ? AND parent_id IS NOT NULL "
                    "   AND IFNULL(parent_id, 0) <> ? AND active = 1",
                    (normalize_name(cocuk), ust_id or 0),
                )
                if baska is not None and not (
                    normalize_name(cocuk) == normalize_name(gorunen_ust)
                ):
                    adimlar.append(SablonAdimi(
                        ADIM_TASI,
                        f"Mevcut \"{self.path(baska['id'])}\" kategorisini "
                        f"\"{gorunen_ust}\" altına taşı (yeniden oluşturmadan)",
                        ad=cocuk, ust_ad=ust_ad, kategori_id=baska["id"],
                    ))
                    continue
                adimlar.append(SablonAdimi(
                    ADIM_EKLE, f"Alt kategori ekle: {gorunen_ust} > {cocuk}",
                    ad=cocuk, ust_ad=ust_ad,
                ))
        diger = self._bul("Diğer", None)
        if diger is not None:
            dogrudan = int(self.db.scalar(
                "SELECT COUNT(*) FROM products WHERE category_id = ?", (diger["id"],),
                default=0,
            ))
            if dogrudan:
                adimlar.append(SablonAdimi(
                    ADIM_URUN_TASI,
                    f"Doğrudan \"Diğer\" üst kategorisindeki {dogrudan} ürünü "
                    "\"Diğer > Diğer\" alt kategorisine taşı (isteğe bağlı)",
                    ad="Diğer", ust_ad="Diğer", kategori_id=diger["id"], secili=False,
                ))
        return adimlar

    def apply_template(self, adimlar: list[SablonAdimi]) -> int:
        """Seçili adımları TEK işlemde uygular; uygulanan adım sayısını döner."""
        uygulanan = 0
        with self.db.transaction() as conn:
            ust_kimlik: dict[str, int] = {}

            def ust_bul(ad: str) -> int | None:
                if ad in ust_kimlik:
                    return ust_kimlik[ad]
                satir = self._bul(ad, None)
                if satir is None:
                    for es in SABLON_ESADLARI.get(ad, ()):
                        satir = self._bul(es, None)
                        if satir is not None:
                            break
                return None if satir is None else satir["id"]

            for adim in (a for a in adimlar if a.secili and a.tur == ADIM_YENIDEN_ADLANDIR):
                self.rename(adim.kategori_id, adim.ad)
                uygulanan += 1
            for adim in (a for a in adimlar if a.secili and a.tur == ADIM_EKLE
                         and a.ust_ad is None):
                if self._bul(adim.ad, None) is None:
                    ust_kimlik[adim.ad] = self.create(adim.ad)
                    uygulanan += 1
            for adim in (a for a in adimlar if a.secili and a.tur in (ADIM_EKLE, ADIM_TASI)
                         and a.ust_ad is not None):
                ust_id = ust_bul(adim.ust_ad)
                if ust_id is None or self._bul(adim.ad, ust_id) is not None:
                    continue
                if adim.tur == ADIM_TASI:
                    self.move(adim.kategori_id, ust_id)
                else:
                    self.create(adim.ad, ust_id)
                uygulanan += 1
            for adim in (a for a in adimlar if a.secili and a.tur == ADIM_URUN_TASI):
                alt = self._bul("Diğer", adim.kategori_id)
                if alt is None:
                    continue
                conn.execute(
                    "UPDATE products SET category_id = ?, updated_at_utc = ? "
                    " WHERE category_id = ?",
                    (alt["id"], now_utc(), adim.kategori_id),
                )
                uygulanan += 1
            if uygulanan:
                self.audit.record(
                    "KATEGORI_SABLON", f"Kategori şablonundan {uygulanan} adım uygulandı.",
                    conn=conn,
                )
        return uygulanan
