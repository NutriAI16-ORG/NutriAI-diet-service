"""
Diet Service - API Routes
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Document, FoodAllergy
from services import create_diet_plan, get_diet_plans, get_diet_plan_detail, generate_diet_plan_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diet-plan", tags=["Diet Plans"])


class GenerateRequest(BaseModel):
    document_ids: List[str]
    additional_notes: Optional[str] = None


@router.get("/documents")
async def list_completed_documents(request: Request, db: Session = Depends(get_db)):
    """Get completed documents for diet plan generation."""
    user_id_str = request.headers.get("X-User-ID")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Not authenticated")
    import uuid
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

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


@router.post("/generate")
async def generate_plan(payload: GenerateRequest, request: Request, db: Session = Depends(get_db)):
    user_id_str = request.headers.get("X-User-ID")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Not authenticated")
    import uuid
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    if not payload.document_ids:
        return JSONResponse(status_code=400, content={"error": "Please select at least one document."})

    try:
        plan = create_diet_plan(
            db=db,
            user_id=user_id,
            document_ids=payload.document_ids,
            additional_notes=payload.additional_notes,
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


@router.get("/history")
async def history(request: Request, db: Session = Depends(get_db)):
    user_id_str = request.headers.get("X-User-ID")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Not authenticated")
    import uuid
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

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


@router.get("/{plan_id}")
async def plan_detail(plan_id: str, request: Request, db: Session = Depends(get_db)):
    user_id_str = request.headers.get("X-User-ID")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Not authenticated")
    import uuid
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    try:
        plan_uuid = uuid.UUID(plan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan ID format")

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


@router.get("/{plan_id}/pdf")
async def download_pdf(plan_id: str, request: Request, db: Session = Depends(get_db)):
    user_id_str = request.headers.get("X-User-ID")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Not authenticated")
    import uuid
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    try:
        plan_uuid = uuid.UUID(plan_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid plan ID format")

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
    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate PDF.")
