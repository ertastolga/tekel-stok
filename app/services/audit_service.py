"""Denetim günlüğü: önemli iş değişikliklerinin kalıcı izi.

Kayıtlar Türkçe ve sade cümlelerdir; ama normal kullanıcı günlük işinde bunu
OKUMAZ — Yönetim > Geçmiş altında durur.

``summary_tr`` cümlesini bir SERVİS yazar, asla bir arayüz gereci değil.
"""
from __future__ import annotations

import json
import sqlite3

from app.core.clock import now_utc
from app.core.db import Database


class Actor:
    USER = "USER"
    SYSTEM = "SYSTEM"
    MIGRATION = "MIGRATION"


class AuditService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(
        self,
        action: str,
        summary_tr: str,
        entity_type: str | None = None,
        entity_id: int | None = None,
        details: dict | None = None,
        actor: str = Actor.USER,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Denetim satırı yazar.

        ``conn`` verilirse ÇAĞIRANIN işlemi içinde yazılır — iş kuralı geri
        alınırsa denetim satırı da geri alınır, yani "olmayan bir işlem"
        günlükte görünmez.
        """
        payload = (
            now_utc(),
            actor,
            action,
            entity_type,
            entity_id,
            summary_tr,
            json.dumps(details, ensure_ascii=False) if details else None,
        )
        sql = (
            "INSERT INTO audit_log(created_at_utc, actor, action, entity_type, "
            "entity_id, summary_tr, details_json) VALUES(?,?,?,?,?,?,?)"
        )
        if conn is not None:
            conn.execute(sql, payload)
        else:
            with self.db.transaction() as own:
                own.execute(sql, payload)

    def recent(self, limit: int = 100, offset: int = 0) -> list[sqlite3.Row]:
        """En yeni kayıtlar. Tüm geçmiş ASLA belleğe alınmaz."""
        return self.db.query(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
            (max(1, min(500, limit)), max(0, offset)),
        )

    def for_entity(self, entity_type: str, entity_id: int, limit: int = 50) -> list[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM audit_log WHERE entity_type = ? AND entity_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (entity_type, entity_id, max(1, min(500, limit))),
        )
