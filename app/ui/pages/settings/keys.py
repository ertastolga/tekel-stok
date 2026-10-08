"""Ayar anahtarı → bölüm eşlemesi: Qt'suz kaynak ``app.core.ayar_bolumleri``.

Destek paketi (servis katmanı) de bu tabloyu kullandığı için tablo Qt
içermeyen çekirdekte durur; bu modül ayarlar sayfası için onu yeniden verir.
"""
from app.core.ayar_bolumleri import AYAR_BOLUMU, BOLUMLER, IC_AYARLAR, IC_ONEKLER, ic_mi

__all__ = ["AYAR_BOLUMU", "BOLUMLER", "IC_AYARLAR", "IC_ONEKLER", "ic_mi"]
