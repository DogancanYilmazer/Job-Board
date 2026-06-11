from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder


def _clean(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, dict):
        return {key: _clean(val) for key, val in value.items()}
    return value


def ok(data: Any = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "data": jsonable_encoder(_clean(data)),
        "meta": meta or {},
        "errors": [],
    }


def row_to_dict(row: Any) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows: Iterable[Any]) -> List[Dict[str, Any]]:
    return [dict(row) for row in rows]


def fail(
    status_code: int,
    code: str,
    message: str,
    field: Optional[str] = None,
) -> None:
    error = {"code": code, "message": message}
    if field:
        error["field"] = field
    raise HTTPException(
        status_code=status_code,
        detail={"data": None, "meta": {}, "errors": [error]},
    )
