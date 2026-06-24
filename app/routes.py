"""
Diet Service - API Routes
"""

import uuid
import logging
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_db
from app.models import Document, FoodAllergy
from app.services import create_diet_plan, get_diet_plans, get_diet_plan_detail, generate_diet_plan_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diet-plan", tags=["Diet Plans"])

# ── Shared error message constants ────────────────────────────────────────────
MSG_NOT_AUTHENTICATED = "Not authenticated"
MSG_INVALID_USER_ID = "Invalid user ID format"

# ── Annotated dependency alias ─────────────────────────────────────────────────
DbSession = Annotated[Session, Depends(get_db)]


def _parse_user_id(request: Request) -> uuid.UUID:
    """Extract and validate X-User-ID header, raising HTTPException on failure."""
    user_id_str = request.headers.get("X-User-ID")
    if not user_id_str:
        raise HTTPException(status_code=401, detail=MSG_NOT_AUTHENTICATED)
    try:
        return uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=MSG_INVALID_USER_ID)


def _parse_plan_id(plan_id: str) -> uuid.UUID:
    """Parse and validate a plan UUID string, raising HTTPException on failure."""
    try:
        return uuid.UUID(plan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan ID format")


@router.get(
    "/documents",
    responses={
        401: {"description": MSG_NOT_AUTHENTICATED},
        400: {"description": MSG_INVALID_USER_ID},
    },
)
async def list_completed_documents(request: Request, db: DbSession):
    """Get completed documents for diet plan generation."""
    user_id = _parse_user_id(request)

    documents = (
        db.query(Document)
        .filter(Document.user_id == user_id, Document.ocr_status == "completed")
        .order_by(Document.uploaded_at.desc())
        .all()
    )

    allergies = db.query(FoodAllergy).filter(FoodAllergy.user_id == user_id).all()

    return {
        "documents": [
            {
                "id": str(doc.id),
                "original_filename": doc.original_filename,
                "document_type": doc.document_type,
                "uploaded_at": doc.uploaded_at.isoformat(),
            }
            for doc in documents
        ],
        "allergies": [
            {
                "id": str(a.id),
                "allergen_name": a.allergen_name,
                "severity": a.severity,
                "notes": a.notes,
            }
            for a in allergies
        ],
    }


@router.post(
    "/generate",
    responses={
        401: {"description": MSG_NOT_AUTHENTICATED},
        400: {"description": "Bad request — no documents selected or invalid user ID"},
        503: {"description": "AI diet plan service temporarily unavailable"},
    },
)
async def generate_plan(payload: "GenerateRequest", request: Request, db: DbSession, background_tasks: BackgroundTasks):
    user_id = _parse_user_id(request)

    if not payload.document_ids:
        return JSONResponse(status_code=400, content={"error": "Please select at least one document."})

    try:
        plan = create_diet_plan(
            db=db,
            user_id=user_id,
            document_ids=payload.document_ids,
            additional_notes=payload.additional_notes,
            background_tasks=background_tasks,
        )

        if not plan:
            return JSONResponse(
                status_code=503,
                content={"error": "We're sorry! Our AI diet plan service is currently unavailable. Please try again later or contact support if the issue persists."},
            )

        return {
            "message": "Diet plan generated successfully!",
            "plan_id": str(plan.id),
            "plan_title": plan.plan_title,
            "plan_summary": plan.plan_summary,
            "foods_to_eat": plan.foods_to_eat,
            "foods_to_avoid": plan.foods_to_avoid,
            "weekly_meal_plan": plan.weekly_meal_plan,
            "nutritional_guidelines": plan.nutritional_guidelines,
            "allergy_notes": plan.allergy_notes,
            "additional_recommendations": plan.additional_recommendations or [],
        }

    except Exception as e:
        logger.error(f"Error generating diet plan: {e}")
        return JSONResponse(status_code=503, content={"error": "We're sorry! Our AI diet plan service is temporarily unavailable. Please try again in a few minutes."})


@router.get(
    "/history",
    responses={
        401: {"description": MSG_NOT_AUTHENTICATED},
        400: {"description": MSG_INVALID_USER_ID},
    },
)
async def history(request: Request, db: DbSession):
    user_id = _parse_user_id(request)

    plans = get_diet_plans(db, user_id)
    return [
        {
            "id": str(p.id),
            "plan_title": p.plan_title,
            "plan_summary": p.plan_summary,
            "foods_to_eat_count": len(p.foods_to_eat) if p.foods_to_eat else 0,
            "foods_to_avoid_count": len(p.foods_to_avoid) if p.foods_to_avoid else 0,
            "generated_at": p.generated_at.isoformat(),
            "is_active": p.is_active,
        }
        for p in plans
    ]


@router.get(
    "/{plan_id}",
    responses={
        401: {"description": MSG_NOT_AUTHENTICATED},
        400: {"description": "Invalid user ID or plan ID format"},
        404: {"description": "Diet plan not found"},
    },
)
async def plan_detail(plan_id: str, request: Request, db: DbSession):
    user_id = _parse_user_id(request)
    plan_uuid = _parse_plan_id(plan_id)

    plan = get_diet_plan_detail(db, plan_uuid, user_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Diet plan not found.")

    return {
        "id": str(plan.id),
        "plan_title": plan.plan_title,
        "plan_summary": plan.plan_summary,
        "foods_to_eat": plan.foods_to_eat,
        "foods_to_avoid": plan.foods_to_avoid,
        "weekly_meal_plan": plan.weekly_meal_plan,
        "nutritional_guidelines": plan.nutritional_guidelines,
        "allergy_notes": plan.allergy_notes,
        "additional_recommendations": plan.additional_recommendations or [],
        "generated_at": plan.generated_at.isoformat(),
        "is_active": plan.is_active,
        "document_ids": plan.document_ids or [],
    }


@router.get(
    "/{plan_id}/pdf",
    responses={
        401: {"description": MSG_NOT_AUTHENTICATED},
        400: {"description": "Invalid user ID or plan ID format"},
        404: {"description": "Diet plan not found"},
        500: {"description": "Failed to generate PDF"},
    },
)
async def download_pdf(plan_id: str, request: Request, db: DbSession):
    user_id = _parse_user_id(request)
    plan_uuid = _parse_plan_id(plan_id)

    plan = get_diet_plan_detail(db, plan_uuid, user_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Diet plan not found.")

    try:
        pdf_bytes = generate_diet_plan_pdf(plan)
        filename = f"diet_plan_{plan.generated_at.strftime('%Y%m%d')}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except (SQLAlchemyError, ValueError, OSError) as e:
        logger.error(f"Error generating PDF: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate PDF.")


class GenerateRequest(BaseModel):
    document_ids: List[str]
    additional_notes: Optional[str] = None
