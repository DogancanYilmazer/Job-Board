from typing import Any, Dict, Optional
from uuid import uuid4

from psycopg2.extras import Json


def log_admin_action(
    cursor: Any,
    admin_user_id: str,
    action_type: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    cursor.execute(
        """
        INSERT INTO admin_activity_logs (id, admin_user_id, action_type, target_type, target_id, description, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            str(uuid4()),
            admin_user_id,
            action_type,
            target_type,
            target_id,
            description,
            Json(metadata or {}),
        ),
    )
