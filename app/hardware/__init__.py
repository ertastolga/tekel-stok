"""Donanım soyutlamaları.

Qt'suz ve veritabanı bilmez. Buradaki her bileşen İSTEĞE BAĞLIDIR: cihaz yoksa
ya da bozuksa uygulama tam olarak eskisi gibi çalışır.
"""
from app.hardware.customer_display import (
    CustomerDisplay,
    CustomerDisplayService,
    NullCustomerDisplay,
    SerialCustomerDisplay,
)

__all__ = [
    "CustomerDisplay",
    "CustomerDisplayService",
    "NullCustomerDisplay",
    "SerialCustomerDisplay",
]
