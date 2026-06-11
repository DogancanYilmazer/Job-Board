from uuid import uuid4

from fastapi import APIRouter, Depends
from psycopg2.extras import Json

from database.connection import get_pg_cursor
from models.negotiations import (
    CancelContract,
    FundContract,
    OfferCreate,
    OfferReject,
    PriceProposalCreate,
    RatingCreate,
)
from utils.responses import fail, ok, row_to_dict, rows_to_list
from utils.security import get_current_user, is_admin, same_user

router = APIRouter(tags=["negotiations-contracts-ratings"])

OWNER_CANCELLATION_PERCENTAGE = 20


def get_application_or_fail(cursor, application_id: str):
    cursor.execute(
        """
        SELECT a.*, j.owner_user_id AS job_owner_user_id
        FROM applications a
        JOIN jobs j ON j.id = a.job_id
        WHERE a.id = %s
        """,
        (application_id,),
    )
    application = row_to_dict(cursor.fetchone())
    if not application:
        fail(404, "APPLICATION_NOT_FOUND", "Application not found")
    return application


def get_job_or_fail(cursor, job_id: str):
    cursor.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
    job = row_to_dict(cursor.fetchone())
    if not job:
        fail(404, "JOB_NOT_FOUND", "Job not found")
    return job


def get_contract_or_fail(cursor, contract_id: str):
    cursor.execute("SELECT * FROM contracts WHERE id = %s", (contract_id,))
    contract = row_to_dict(cursor.fetchone())
    if not contract:
        fail(404, "CONTRACT_NOT_FOUND", "Contract not found")
    return contract


def require_job_owner(job, current_user) -> None:
    if not same_user(job["owner_user_id"], current_user["id"]) and not is_admin(current_user):
        fail(403, "FORBIDDEN", "Only the job owner can perform this action")


def require_contract_participant(contract, current_user) -> None:
    if same_user(contract["owner_user_id"], current_user["id"]):
        return
    if same_user(contract["worker_user_id"], current_user["id"]):
        return
    if is_admin(current_user):
        return
    fail(403, "FORBIDDEN", "Only contract participants can perform this action")


def require_contract_party(contract, current_user) -> None:
    if same_user(contract["owner_user_id"], current_user["id"]):
        return
    if same_user(contract["worker_user_id"], current_user["id"]):
        return
    fail(403, "FORBIDDEN", "Only contract participants can perform this action")


def require_contract_owner(contract, current_user) -> None:
    if not same_user(contract["owner_user_id"], current_user["id"]) and not is_admin(current_user):
        fail(403, "FORBIDDEN", "Only the contract owner can perform this action")


def require_offer_applicant(offer, current_user) -> None:
    if not same_user(offer["applicant_user_id"], current_user["id"]) and not is_admin(current_user):
        fail(403, "FORBIDDEN", "Only the offer recipient can perform this action")


def require_proposal_receiver(proposal, current_user) -> None:
    if not proposal.get("receiver_user_id"):
        fail(403, "FORBIDDEN", "This proposal has no receiver")
    if not same_user(proposal["receiver_user_id"], current_user["id"]) and not is_admin(current_user):
        fail(403, "FORBIDDEN", "Only the proposal receiver can perform this action")


@router.post("/jobs/{job_id}/price-proposals", status_code=201)
def create_price_proposal(job_id: str, payload: PriceProposalCreate, current_user=Depends(get_current_user)):
    proposal_id = str(uuid4())
    with get_pg_cursor(commit=True) as cursor:
        job = get_job_or_fail(cursor, job_id)
        proposer_user_id = str(current_user["id"])
        if payload.proposer_user_id and not same_user(payload.proposer_user_id, proposer_user_id):
            fail(403, "FORBIDDEN", "You are not allowed to propose as another user", "proposer_user_id")

        receiver_user_id = payload.receiver_user_id
        if payload.application_id:
            application = get_application_or_fail(cursor, payload.application_id)
            if not same_user(application["job_id"], job_id):
                fail(400, "VALIDATION_ERROR", "Application does not belong to this job", "application_id")
            owner_user_id = str(job["owner_user_id"])
            applicant_user_id = str(application["applicant_user_id"])
            if not (same_user(proposer_user_id, owner_user_id) or same_user(proposer_user_id, applicant_user_id)):
                fail(403, "FORBIDDEN", "Only application participants can create price proposals")
            counterpart_user_id = applicant_user_id if same_user(proposer_user_id, owner_user_id) else owner_user_id
            if receiver_user_id and not same_user(receiver_user_id, counterpart_user_id):
                fail(403, "FORBIDDEN", "Proposal receiver must be the counterpart", "receiver_user_id")
            receiver_user_id = counterpart_user_id
        else:
            if same_user(proposer_user_id, job["owner_user_id"]):
                if not receiver_user_id:
                    fail(400, "VALIDATION_ERROR", "receiver_user_id is required", "receiver_user_id")
            else:
                receiver_user_id = str(job["owner_user_id"])

        if same_user(proposer_user_id, receiver_user_id):
            fail(400, "VALIDATION_ERROR", "Proposer and receiver must be different users", "receiver_user_id")

        cursor.execute(
            """
            INSERT INTO price_proposals (
                id, job_id, application_id, proposer_user_id, receiver_user_id,
                amount_minor, currency, message, status, expires_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s)
            RETURNING *
            """,
            (
                proposal_id,
                job_id,
                payload.application_id,
                proposer_user_id,
                receiver_user_id,
                payload.amount_minor,
                payload.currency,
                payload.message,
                payload.expires_at,
            ),
        )
        proposal = row_to_dict(cursor.fetchone())
    return ok(proposal)


@router.get("/jobs/{job_id}/price-proposals")
def list_price_proposals(job_id: str, current_user=Depends(get_current_user)):
    with get_pg_cursor() as cursor:
        job = get_job_or_fail(cursor, job_id)
        if same_user(job["owner_user_id"], current_user["id"]) or is_admin(current_user):
            cursor.execute(
                "SELECT * FROM price_proposals WHERE job_id = %s ORDER BY created_at DESC",
                (job_id,),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM price_proposals
                WHERE job_id = %s AND (proposer_user_id = %s OR receiver_user_id = %s)
                ORDER BY created_at DESC
                """,
                (job_id, current_user["id"], current_user["id"]),
            )
        proposals = rows_to_list(cursor.fetchall())
    return ok(proposals)


@router.patch("/price-proposals/{proposal_id}/accept")
def accept_price_proposal(proposal_id: str, current_user=Depends(get_current_user)):
    with get_pg_cursor(commit=True) as cursor:
        cursor.execute("SELECT * FROM price_proposals WHERE id = %s", (proposal_id,))
        proposal = row_to_dict(cursor.fetchone())
        if not proposal:
            fail(404, "PRICE_PROPOSAL_NOT_FOUND", "Price proposal not found")
        require_proposal_receiver(proposal, current_user)
        cursor.execute(
            "UPDATE price_proposals SET status = 'ACCEPTED' WHERE id = %s RETURNING *",
            (proposal_id,),
        )
        proposal = row_to_dict(cursor.fetchone())
    return ok({"proposal_id": proposal_id, "status": "ACCEPTED", "next_action": "CREATE_OFFER"})


@router.patch("/price-proposals/{proposal_id}/reject")
def reject_price_proposal(proposal_id: str, current_user=Depends(get_current_user)):
    with get_pg_cursor(commit=True) as cursor:
        cursor.execute("SELECT * FROM price_proposals WHERE id = %s", (proposal_id,))
        proposal = row_to_dict(cursor.fetchone())
        if not proposal:
            fail(404, "PRICE_PROPOSAL_NOT_FOUND", "Price proposal not found")
        require_proposal_receiver(proposal, current_user)
        cursor.execute(
            "UPDATE price_proposals SET status = 'REJECTED' WHERE id = %s RETURNING *",
            (proposal_id,),
        )
        proposal = row_to_dict(cursor.fetchone())
    return ok(proposal)


@router.post("/applications/{application_id}/offer", status_code=201)
def create_offer(application_id: str, payload: OfferCreate, current_user=Depends(get_current_user)):
    offer_id = str(uuid4())
    with get_pg_cursor(commit=True) as cursor:
        application = get_application_or_fail(cursor, application_id)
        job = get_job_or_fail(cursor, application["job_id"])
        require_job_owner(job, current_user)

        owner_user_id = str(job["owner_user_id"])
        if payload.owner_user_id and not same_user(payload.owner_user_id, owner_user_id):
            fail(403, "FORBIDDEN", "Offer owner must match the job owner", "owner_user_id")
        cursor.execute(
            """
            INSERT INTO offers (
                id, application_id, job_id, owner_user_id, applicant_user_id,
                amount_minor, currency, terms, status, expires_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s)
            RETURNING *
            """,
            (
                offer_id,
                application_id,
                application["job_id"],
                owner_user_id,
                application["applicant_user_id"],
                payload.amount_minor,
                payload.currency,
                payload.terms,
                payload.expires_at,
            ),
        )
        offer = row_to_dict(cursor.fetchone())

        cursor.execute(
            "UPDATE applications SET status = 'OFFER', updated_at = NOW() WHERE id = %s",
            (application_id,),
        )
        cursor.execute(
            "UPDATE jobs SET status = 'NEGOTIATING', updated_at = NOW() WHERE id = %s",
            (application["job_id"],),
        )
        cursor.execute(
            """
            INSERT INTO application_status_history (
                id, application_id, from_status, to_status, changed_by_user_id, note
            )
            VALUES (%s, %s, %s, 'OFFER', %s, 'Offer created')
            """,
            (str(uuid4()), application_id, application["status"], current_user["id"]),
        )
    return ok(offer)


@router.post("/offers/{offer_id}/accept")
def accept_offer(offer_id: str, current_user=Depends(get_current_user)):
    contract_id = str(uuid4())
    assignment_id = str(uuid4())
    with get_pg_cursor(commit=True) as cursor:
        cursor.execute("SELECT * FROM offers WHERE id = %s", (offer_id,))
        offer = row_to_dict(cursor.fetchone())
        if not offer:
            fail(404, "OFFER_NOT_FOUND", "Offer not found")
        require_offer_applicant(offer, current_user)

        cursor.execute("UPDATE offers SET status = 'ACCEPTED' WHERE id = %s", (offer_id,))
        cursor.execute(
            "UPDATE applications SET status = 'ACCEPTED', updated_at = NOW() WHERE id = %s",
            (offer["application_id"],),
        )
        cursor.execute(
            """
            INSERT INTO contracts (
                id, job_id, application_id, offer_id, owner_user_id, worker_user_id,
                agreed_amount_minor, currency, escrow_status, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'NOT_FUNDED', 'PENDING_ESCROW')
            RETURNING *
            """,
            (
                contract_id,
                offer["job_id"],
                offer["application_id"],
                offer_id,
                offer["owner_user_id"],
                offer["applicant_user_id"],
                offer["amount_minor"],
                offer["currency"],
            ),
        )
        contract = row_to_dict(cursor.fetchone())
        cursor.execute(
            """
            INSERT INTO job_assignments (
                id, job_id, application_id, contract_id, assigned_to_user_id, visibility
            )
            VALUES (%s, %s, %s, %s, %s, (SELECT taken_visibility FROM jobs WHERE id = %s))
            """,
            (
                assignment_id,
                offer["job_id"],
                offer["application_id"],
                contract_id,
                offer["applicant_user_id"],
                offer["job_id"],
            ),
        )
    return ok(
        {
            "offer_status": "ACCEPTED",
            "contract": {
                "id": contract["id"],
                "status": contract["status"],
                "agreed_amount_minor": contract["agreed_amount_minor"],
                "currency": contract["currency"],
            },
        }
    )


@router.post("/offers/{offer_id}/reject")
def reject_offer(offer_id: str, payload: OfferReject, current_user=Depends(get_current_user)):
    with get_pg_cursor(commit=True) as cursor:
        cursor.execute("SELECT * FROM offers WHERE id = %s", (offer_id,))
        offer = row_to_dict(cursor.fetchone())
        if not offer:
            fail(404, "OFFER_NOT_FOUND", "Offer not found")
        require_offer_applicant(offer, current_user)
        cursor.execute(
            "UPDATE offers SET status = 'REJECTED' WHERE id = %s RETURNING *",
            (offer_id,),
        )
        offer = row_to_dict(cursor.fetchone())
    return ok({"offer": offer, "reason": payload.reason})


@router.post("/contracts/{contract_id}/fund")
def fund_contract(contract_id: str, payload: FundContract, current_user=Depends(get_current_user)):
    ledger_id = str(uuid4())
    with get_pg_cursor(commit=True) as cursor:
        contract = get_contract_or_fail(cursor, contract_id)
        require_contract_owner(contract, current_user)
        if payload.actor_user_id and not same_user(payload.actor_user_id, current_user["id"]) and not is_admin(current_user):
            fail(403, "FORBIDDEN", "You are not allowed to fund as another user", "actor_user_id")
        cursor.execute(
            """
            UPDATE contracts
            SET escrow_status = 'HELD', status = 'ACTIVE', started_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (contract_id,),
        )
        updated = row_to_dict(cursor.fetchone())
        cursor.execute(
            "UPDATE jobs SET status = 'IN_PROGRESS', updated_at = NOW() WHERE id = %s",
            (contract["job_id"],),
        )
        cursor.execute(
            """
            INSERT INTO payment_ledger (
                id, contract_id, actor_user_id, counterparty_user_id,
                type, amount_minor, currency, status, provider_reference, metadata
            )
            VALUES (%s, %s, %s, %s, 'ESCROW_HOLD', %s, %s, 'SUCCEEDED', %s, %s)
            RETURNING *
            """,
            (
                ledger_id,
                contract_id,
                current_user["id"],
                contract["worker_user_id"],
                contract["agreed_amount_minor"],
                contract["currency"],
                payload.payment_method_id,
                Json({"demo": True}),
            ),
        )
        ledger = row_to_dict(cursor.fetchone())
    return ok({"contract_id": updated["id"], "escrow_status": updated["escrow_status"], "payment_ledger_entry": ledger})


@router.post("/contracts/{contract_id}/complete")
def complete_contract(contract_id: str, current_user=Depends(get_current_user)):
    ledger_id = str(uuid4())
    with get_pg_cursor(commit=True) as cursor:
        contract = get_contract_or_fail(cursor, contract_id)
        require_contract_owner(contract, current_user)
        cursor.execute(
            "UPDATE contracts SET status = 'COMPLETED', completed_at = NOW() WHERE id = %s RETURNING *",
            (contract_id,),
        )
        updated = row_to_dict(cursor.fetchone())
        cursor.execute(
            "UPDATE jobs SET status = 'COMPLETED', updated_at = NOW() WHERE id = %s",
            (contract["job_id"],),
        )
        cursor.execute(
            """
            INSERT INTO payment_ledger (
                id, contract_id, actor_user_id, counterparty_user_id,
                type, amount_minor, currency, status
            )
            VALUES (%s, %s, %s, %s, 'ESCROW_RELEASE', %s, %s, 'SUCCEEDED')
            RETURNING type, amount_minor, currency, status
            """,
            (
                ledger_id,
                contract_id,
                current_user["id"],
                contract["worker_user_id"],
                contract["agreed_amount_minor"],
                contract["currency"],
            ),
        )
        payment = row_to_dict(cursor.fetchone())
    return ok({"contract_status": updated["status"], "payment": payment})


@router.post("/contracts/{contract_id}/cancel")
def cancel_contract(contract_id: str, payload: CancelContract, current_user=Depends(get_current_user)):
    cancellation_id = str(uuid4())
    with get_pg_cursor(commit=True) as cursor:
        contract = get_contract_or_fail(cursor, contract_id)
        require_contract_participant(contract, current_user)
        if payload.requested_by_user_id and not same_user(payload.requested_by_user_id, current_user["id"]) and not is_admin(current_user):
            fail(403, "FORBIDDEN", "You are not allowed to cancel as another user", "requested_by_user_id")
        agreed_amount = contract["agreed_amount_minor"] or 0
        currency = contract["currency"]
        role = payload.requested_by_role.upper()
        if not is_admin(current_user):
            expected_role = "OWNER" if same_user(contract["owner_user_id"], current_user["id"]) else "WORKER"
            if role != expected_role:
                fail(403, "FORBIDDEN", "Cancellation role does not match the authenticated user", "requested_by_role")

        if role == "OWNER":
            payout_to_worker = int(agreed_amount * OWNER_CANCELLATION_PERCENTAGE / 100)
            refund_to_owner = agreed_amount - payout_to_worker
            next_status = "CANCELLED_BY_OWNER"
        else:
            payout_to_worker = 0
            refund_to_owner = agreed_amount
            next_status = "CANCELLED_BY_WORKER"

        cursor.execute(
            "UPDATE contracts SET status = %s, cancelled_at = NOW() WHERE id = %s RETURNING *",
            (next_status, contract_id),
        )
        updated = row_to_dict(cursor.fetchone())
        cursor.execute(
            "UPDATE jobs SET status = 'CANCELLED', updated_at = NOW() WHERE id = %s",
            (contract["job_id"],),
        )
        cursor.execute(
            """
            INSERT INTO cancellations (
                id, contract_id, requested_by_user_id, requested_by_role, reason,
                refund_to_owner_minor, payout_to_worker_minor, platform_fee_minor,
                policy_snapshot, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, 'DONE')
            RETURNING *
            """,
            (
                cancellation_id,
                contract_id,
                current_user["id"],
                role,
                payload.reason,
                refund_to_owner,
                payout_to_worker,
                Json({"owner_cancellation_percentage": OWNER_CANCELLATION_PERCENTAGE}),
            ),
        )
        cancellation = row_to_dict(cursor.fetchone())
    return ok(
        {
            "contract_status": updated["status"],
            "refund_to_owner_minor": cancellation["refund_to_owner_minor"],
            "payout_to_worker_minor": cancellation["payout_to_worker_minor"],
            "currency": currency,
            "policy": {"owner_cancellation_percentage": OWNER_CANCELLATION_PERCENTAGE},
        }
    )


@router.post("/contracts/{contract_id}/ratings", status_code=201)
def create_rating(contract_id: str, payload: RatingCreate, current_user=Depends(get_current_user)):
    rating_id = str(uuid4())
    with get_pg_cursor(commit=True) as cursor:
        contract = get_contract_or_fail(cursor, contract_id)
        require_contract_party(contract, current_user)
        if payload.rater_user_id and not same_user(payload.rater_user_id, current_user["id"]):
            fail(403, "FORBIDDEN", "You are not allowed to rate as another user", "rater_user_id")
        if same_user(contract["owner_user_id"], current_user["id"]):
            expected_ratee_id = str(contract["worker_user_id"])
        elif same_user(contract["worker_user_id"], current_user["id"]):
            expected_ratee_id = str(contract["owner_user_id"])
        else:
            expected_ratee_id = str(payload.ratee_user_id)
        if not same_user(payload.ratee_user_id, expected_ratee_id):
            fail(403, "FORBIDDEN", "You can only rate your contract counterparty", "ratee_user_id")
        cursor.execute(
            """
            INSERT INTO ratings (
                id, contract_id, rater_user_id, ratee_user_id, rating, comment, role_context
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                rating_id,
                contract_id,
                current_user["id"],
                payload.ratee_user_id,
                payload.rating,
                payload.comment,
                payload.role_context,
            ),
        )
        rating = row_to_dict(cursor.fetchone())

        cursor.execute(
            "SELECT COALESCE(AVG(rating), 0) AS avg, COUNT(*) AS count FROM ratings WHERE ratee_user_id = %s",
            (payload.ratee_user_id,),
        )
        summary = row_to_dict(cursor.fetchone())
        cursor.execute(
            "UPDATE applicant_profiles SET rating_avg = %s, rating_count = %s WHERE user_id = %s",
            (summary["avg"], summary["count"], payload.ratee_user_id),
        )
        cursor.execute(
            "UPDATE employer_profiles SET rating_avg = %s, rating_count = %s WHERE user_id = %s",
            (summary["avg"], summary["count"], payload.ratee_user_id),
        )
    return ok(rating)
