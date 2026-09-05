"""İş kuralları katmanı.

Bu paket ASLA ``PySide6`` içe aktarmaz — bir test bunu denetler. Arayüz iş
kuralı SQL'i çalıştırmaz; her işlem buradaki servislerden geçer ve her işlem
kendi ``BEGIN IMMEDIATE`` sınırını kendisi açar.
"""
