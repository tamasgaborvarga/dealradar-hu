from __future__ import annotations

from typing import Any

from dealradar.core.enums import Actor
from dealradar.db.models import AuditLog, Setting
from dealradar.db.repositories.base import Repository


class AuditLogRepository(Repository[AuditLog]):
    model = AuditLog

    def record(
        self,
        *,
        actor: Actor,
        entity: str,
        entity_id: str,
        action: str,
        before: Any = None,
        after: Any = None,
    ) -> AuditLog:
        return self.add(
            AuditLog(
                actor=actor,
                entity=entity,
                entity_id=entity_id,
                action=action,
                before=before,
                after=after,
            )
        )


class SettingsRepository(Repository[Setting]):
    model = Setting

    def get_value(self, key: str, default: Any = None) -> Any:
        row = self.get(key)
        return default if row is None else row.value

    def set_value(self, key: str, value: Any, actor: Actor) -> None:
        """Create or update a setting and write an audit entry in the same transaction."""
        row = self.get(key)
        before = None if row is None else row.value
        if row is None:
            self.add(Setting(key=key, value=value))
            action = "create"
        else:
            row.value = value
            self.session.flush()
            action = "update"
        AuditLogRepository(self.session).record(
            actor=actor, entity="settings", entity_id=key, action=action, before=before, after=value
        )
