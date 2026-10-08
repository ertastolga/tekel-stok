"""Klavye kısayolları — TEK kaynak.

Kısayollar tek yerde tanımlanır; sayfalara dağılmaz. Böylece hem tutarlı
kalırlar hem de kullanıcıya bir yerde topluca gösterilebilirler.

Neden yalnızca F-tuşları ve Ctrl'lü kısayollar?
-----------------------------------------------
Barkod okuyucu klavye gibi yazar. Çıplak bir harf kısayolu olsaydı, okutulan
barkodun içindeki o harf kısayolu tetikler ve ekranı değiştirirdi. F-tuşları ve
değiştiricili kısayollar barkod dizisinde ASLA geçmez, bu yüzden güvenlidir.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Shortcut:
    key: str
    label: str
    action: str
    show_in_footer: bool = False


#: Uygulamanın tüm kısayolları.
SHORTCUTS: tuple[Shortcut, ...] = (
    Shortcut("F1", "Hızlı Satış", "goto:hizli_satis", True),
    Shortcut("F2", "Sepetli Satış", "goto:sepetli_satis", True),
    Shortcut("F3", "Mal Kabul", "goto:stok_girisi", True),
    Shortcut("F4", "Yeni Müşteri", "yeni_musteri", True),
    Shortcut("F5", "Yenile", "yenile"),
    Shortcut("F6", "Ürünler", "goto:urunler"),
    Shortcut("F7", "Analiz", "goto:panel"),
    Shortcut("F8", "Son İşlemi Geri Al", "geri_al", True),
    Shortcut("F9", "Stok Sayımı", "goto:stok_sayimi"),
    Shortcut("F10", "İşlemi Tamamla", "tamamla", True),
    Shortcut("F12", "Barkod Testi", "goto:barkod_testi"),
    Shortcut("Esc", "Geri / Vazgeç", "geri"),
    Shortcut("Ctrl+F", "Ara", "ara"),
    Shortcut("Ctrl+H", "Ana Ekran", "goto:ana_ekran"),
)

#: Ekranda gösterilecek özet (sol menü altı).
FOOTER_HINT = " • ".join(
    f"{s.key} {s.label}" for s in SHORTCUTS if s.show_in_footer
)


def by_action(action: str) -> Shortcut | None:
    for shortcut in SHORTCUTS:
        if shortcut.action == action:
            return shortcut
    return None


def key_for(action: str) -> str:
    shortcut = by_action(action)
    return shortcut.key if shortcut else ""


def label_with_key(action: str, text: str) -> str:
    """Düğme etiketine kısayolu ekler: 'Satışı Tamamla (F10)'."""
    key = key_for(action)
    return f"{text} ({key})" if key else text
