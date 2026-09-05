"""Merkezi barkod okuyucu altyapısı.

Uygulamada barkod işleme mantığı TEK yerdedir. Her ekranın kendi kırılgan
klavye kodunu yazması yerine:

    USB okuyucu -> ScannerService (uygulama düzeyi olay süzgeci)
                -> ScanEvent (benzersiz scan_id ile)
                -> ScanRouter (sıra + etkin işleyici + idempotans)
                -> ekrana özgü eylem
"""
from app.scanner.scan_event import ScanEvent
from app.scanner.scan_router import RouterMode, ScanRouter

__all__ = ["ScanEvent", "ScanRouter", "RouterMode"]
