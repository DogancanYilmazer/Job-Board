from datetime import datetime, timezone
from uuid import uuid4

from bson import ObjectId
from fastapi import APIRouter, Depends
from pymongo.errors import DuplicateKeyError

from database.connection import get_mongo_db, get_pg_cursor
from models.mongo_models import (
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    SavedJobCreate,
    SearchHistoryCreate,
)
from utils.responses import fail, ok, row_to_dict, rows_to_list
from utils.security import get_current_user, is_admin, require_same_user_or_admin, same_user

router = APIRouter(tags=["mongo-features"])


def now_utc():
    return datetime.now(timezone.utc)


def mongo_to_dict(document):
    if not document:
        return None
    item = dict(document)
    if "_id" in item:
        item["id"] = str(item.pop("_id"))
    for key, value in list(item.items()):
        if isinstance(value, ObjectId):
            item[key] = str(value)
        elif isinstance(value, datetime):
            item[key] = value.isoformat()
    return item


def get_job_summary(job_id: str):
    with get_pg_cursor() as cursor:
        cursor.execute(
            """
            SELECT id, title, status
            FROM jobs
            WHERE id = %s
            """,
            (job_id,),
        )
        job = row_to_dict(cursor.fetchone())
    if not job:
        return None
    job["match_score"] = None
    return job


def target_user_id(requested_user_id, current_user) -> str:
    user_id = requested_user_id or str(current_user["id"])
    require_same_user_or_admin(user_id, current_user)
    return str(user_id)


def require_conversation_participant(conversation, current_user, allow_admin: bool = True) -> None:
    if allow_admin and is_admin(current_user):
        return
    if same_user(conversation["owner_user_id"], current_user["id"]):
        return
    if same_user(conversation["applicant_user_id"], current_user["id"]):
        return
    fail(403, "FORBIDDEN", "You are not allowed to access this conversation")


# ---------------------------------------------------------------------------
# Saved Jobs
# ---------------------------------------------------------------------------
@router.post("/saved-jobs", status_code=201)
def save_job(payload: SavedJobCreate, current_user=Depends(get_current_user)):
    user_id = target_user_id(payload.user_id, current_user)
    if not get_job_summary(payload.job_id):
        fail(404, "JOB_NOT_FOUND", "Job not found", "job_id")

    mongo_db = get_mongo_db()
    document = {
        "user_id": user_id,
        "job_id": payload.job_id,
        "note": payload.note,
        "tags": payload.tags,
        "saved_at": now_utc(),
    }
    try:
        result = mongo_db.saved_jobs.insert_one(document)
    except DuplicateKeyError:
        fail(409, "JOB_ALREADY_SAVED", "This job is already saved")

    document["_id"] = result.inserted_id
    return ok(mongo_to_dict(document))


@router.get("/saved-jobs")
def list_saved_jobs(user_id: str = "", limit: int = 50, current_user=Depends(get_current_user)):
    user_id = target_user_id(user_id, current_user)
    mongo_db = get_mongo_db()
    cursor = mongo_db.saved_jobs.find({"user_id": user_id}).sort("saved_at", -1).limit(limit)
    items = []
    for document in cursor:
        item = mongo_to_dict(document)
        item["job"] = get_job_summary(item["job_id"])
        items.append(item)
    return ok(items)


@router.delete("/saved-jobs/{job_id}", status_code=204)
def remove_saved_job(job_id: str, user_id: str = "", current_user=Depends(get_current_user)):
    user_id = target_user_id(user_id, current_user)
    mongo_db = get_mongo_db()
    mongo_db.saved_jobs.delete_one({"user_id": user_id, "job_id": job_id})
    return None


# ---------------------------------------------------------------------------
# Search History
# ---------------------------------------------------------------------------
@router.post("/search-history", status_code=201)
def create_search_history(payload: SearchHistoryCreate, current_user=Depends(get_current_user)):
    user_id = target_user_id(payload.user_id, current_user)
    mongo_db = get_mongo_db()
    document = {
        "user_id": user_id,
        "query": payload.query,
        "filters": payload.filters,
        "result_count": payload.result_count,
        "clicked_job_ids": payload.clicked_job_ids,
        "created_at": now_utc(),
    }
    result = mongo_db.search_history.insert_one(document)
    document["_id"] = result.inserted_id
    return ok(mongo_to_dict(document))


@router.get("/search-history")
def get_search_history(user_id: str = "", limit: int = 50, current_user=Depends(get_current_user)):
    user_id = target_user_id(user_id, current_user)
    mongo_db = get_mongo_db()
    items = [
        mongo_to_dict(document)
        for document in mongo_db.search_history.find({"user_id": user_id})
        .sort("created_at", -1)
        .limit(limit)
    ]
    return ok(items)


@router.delete("/search-history", status_code=204)
def clear_search_history(user_id: str = "", current_user=Depends(get_current_user)):
    user_id = target_user_id(user_id, current_user)
    mongo_db = get_mongo_db()
    mongo_db.search_history.delete_many({"user_id": user_id})
    return None


# ---------------------------------------------------------------------------
# Conversations  (fully MongoDB — previously hybrid PG+Mongo)
# ---------------------------------------------------------------------------
def _build_conversation_doc(
    job_id: str,
    owner_user_id: str,
    applicant_user_id: str,
    application_id: str | None = None,
) -> dict:
    return {
        "job_id": job_id,
        "application_id": application_id,
        "owner_user_id": owner_user_id,
        "applicant_user_id": applicant_user_id,
        "status": "ACTIVE",
        "last_message_at": None,
        "created_at": now_utc(),
    }


@router.post("/conversations", status_code=201)
def create_or_get_conversation(payload: ConversationCreate, current_user=Depends(get_current_user)):
    with get_pg_cursor() as cursor:
        cursor.execute("SELECT * FROM jobs WHERE id = %s", (payload.job_id,))
        job = row_to_dict(cursor.fetchone())
        if not job:
            fail(404, "JOB_NOT_FOUND", "Job not found", "job_id")

        owner_user_id = str(job["owner_user_id"])
        if payload.owner_user_id and not same_user(payload.owner_user_id, owner_user_id):
            fail(403, "FORBIDDEN", "Conversation owner must match the job owner", "owner_user_id")
        applicant_user_id = payload.applicant_user_id

        if payload.application_id:
            cursor.execute(
                "SELECT * FROM applications WHERE id = %s AND job_id = %s",
                (payload.application_id, payload.job_id),
            )
            application = row_to_dict(cursor.fetchone())
            if not application:
                fail(404, "APPLICATION_NOT_FOUND", "Application not found", "application_id")
            if applicant_user_id and not same_user(applicant_user_id, application["applicant_user_id"]):
                fail(403, "FORBIDDEN", "Conversation applicant must match the application applicant", "applicant_user_id")
            applicant_user_id = str(application["applicant_user_id"])

        if not applicant_user_id:
            fail(400, "VALIDATION_ERROR", "applicant_user_id is required when application_id is not sent", "applicant_user_id")
        if not is_admin(current_user) and not (
            same_user(current_user["id"], owner_user_id) or same_user(current_user["id"], applicant_user_id)
        ):
            fail(403, "FORBIDDEN", "Only conversation participants can create this conversation")

    mongo_db = get_mongo_db()
    existing = mongo_db.conversations.find_one({
        "job_id": payload.job_id,
        "application_id": payload.application_id,
        "owner_user_id": owner_user_id,
        "applicant_user_id": applicant_user_id,
    })
    if existing:
        return ok(mongo_to_dict(existing))

    doc = _build_conversation_doc(
        job_id=payload.job_id,
        owner_user_id=owner_user_id,
        applicant_user_id=applicant_user_id,
        application_id=payload.application_id,
    )
    result = mongo_db.conversations.insert_one(doc)
    doc["_id"] = result.inserted_id
    return ok(mongo_to_dict(doc))


@router.get("/conversations")
def list_conversations(user_id: str = "", current_user=Depends(get_current_user)):
    user_id = target_user_id(user_id, current_user)
    mongo_db = get_mongo_db()

    query = {
        "$or": [
            {"owner_user_id": user_id},
            {"applicant_user_id": user_id},
        ]
    }
    cursor = (
        mongo_db.conversations.find(query)
        .sort("last_message_at", -1)
    )

    items = []
    for document in cursor:
        item = mongo_to_dict(document)
        job = get_job_summary(item["job_id"])
        item["job_title"] = job["title"] if job else None
        items.append(item)
    return ok(items)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, current_user=Depends(get_current_user)):
    mongo_db = get_mongo_db()
    from bson.objectid import ObjectId
    try:
        conversation = mongo_db.conversations.find_one({"_id": ObjectId(conversation_id)})
    except Exception:
        fail(404, "CONVERSATION_NOT_FOUND", "Conversation not found")
    if not conversation:
        fail(404, "CONVERSATION_NOT_FOUND", "Conversation not found")
    require_conversation_participant(conversation, current_user)
    return ok(mongo_to_dict(conversation))


@router.patch("/conversations/{conversation_id}")
def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    current_user=Depends(get_current_user),
):
    mongo_db = get_mongo_db()
    from bson.objectid import ObjectId
    try:
        conversation = mongo_db.conversations.find_one({"_id": ObjectId(conversation_id)})
    except Exception:
        fail(404, "CONVERSATION_NOT_FOUND", "Conversation not found")
    if not conversation:
        fail(404, "CONVERSATION_NOT_FOUND", "Conversation not found")
    require_conversation_participant(conversation, current_user, allow_admin=False)

    updates = {}
    if payload.status is not None:
        updates["status"] = payload.status
    if payload.last_message_at is not None:
        try:
            updates["last_message_at"] = datetime.fromisoformat(payload.last_message_at.replace("Z", "+00:00"))
        except ValueError:
            fail(400, "VALIDATION_ERROR", "last_message_at must be an ISO date", "last_message_at")

    if updates:
        mongo_db.conversations.update_one(
            {"_id": ObjectId(conversation_id)},
            {"$set": updates},
        )
        conversation.update(updates)

    return ok(mongo_to_dict(conversation))


# ---------------------------------------------------------------------------
# Messages  (already MongoDB — only removed PG dependency)
# ---------------------------------------------------------------------------
@router.get("/conversations/{conversation_id}/messages")
def get_messages(conversation_id: str, before: str = "", limit: int = 30, current_user=Depends(get_current_user)):
    mongo_db = get_mongo_db()
    from bson.objectid import ObjectId
    try:
        conversation = mongo_db.conversations.find_one({"_id": ObjectId(conversation_id)})
    except Exception:
        fail(404, "CONVERSATION_NOT_FOUND", "Conversation not found")
    if not conversation:
        fail(404, "CONVERSATION_NOT_FOUND", "Conversation not found")
    require_conversation_participant(conversation, current_user)

    query = {"conversation_id": conversation_id, "deleted_at": None}
    if before:
        try:
            before_date = datetime.fromisoformat(before.replace("Z", "+00:00"))
        except ValueError:
            fail(400, "VALIDATION_ERROR", "before must be an ISO date", "before")
        query["created_at"] = {"$lt": before_date}

    documents = list(
        mongo_db.chat_messages.find(query).sort("created_at", -1).limit(min(max(limit, 1), 100))
    )
    items = [mongo_to_dict(document) for document in documents]
    next_cursor = items[-1]["created_at"] if items else None
    return ok(items, meta={"next_cursor": next_cursor})


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def send_message(conversation_id: str, payload: MessageCreate, current_user=Depends(get_current_user)):
    mongo_db = get_mongo_db()
    from bson.objectid import ObjectId
    try:
        conversation = mongo_db.conversations.find_one({"_id": ObjectId(conversation_id)})
    except Exception:
        fail(404, "CONVERSATION_NOT_FOUND", "Conversation not found")
    if not conversation:
        fail(404, "CONVERSATION_NOT_FOUND", "Conversation not found")
    require_conversation_participant(conversation, current_user, allow_admin=False)
    if payload.sender_user_id and not same_user(payload.sender_user_id, current_user["id"]):
        fail(403, "FORBIDDEN", "You are not allowed to send messages as another user")
    sender_user_id = str(current_user["id"])

    created_at = now_utc()
    document = {
        "conversation_id": conversation_id,
        "sender_user_id": sender_user_id,
        "body": payload.body,
        "attachments": [item.dict() for item in payload.attachments],
        "read_by": [sender_user_id],
        "created_at": created_at,
        "edited_at": None,
        "deleted_at": None,
    }
    result = mongo_db.chat_messages.insert_one(document)
    document["_id"] = result.inserted_id

    # Update last_message_at in MongoDB conversation
    mongo_db.conversations.update_one(
        {"_id": ObjectId(conversation_id)},
        {"$set": {"last_message_at": created_at}},
    )
    return ok(mongo_to_dict(document))
