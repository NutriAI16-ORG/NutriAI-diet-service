"""
NutriAI Diet Service - Comprehensive Tests
"""

import uuid
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from models import Document, DietPlan, FoodAllergy

def test_health_endpoint(client):
    """Health check endpoint should return 200 and diet service identification."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "diet-service"


class TestDietPlanDocuments:
    """Tests for fetching documents/allergies needed for diet planning."""

    def test_documents_endpoint_renders(self, authenticated_client):
        """Documents endpoint should return 200 for authenticated users."""
        response = authenticated_client.get("/diet-plan/documents")
        assert response.status_code == 200
        assert "documents" in response.json()
        assert "allergies" in response.json()

    def test_documents_endpoint_requires_auth(self, client):
        """Documents endpoint should return 401 for unauthenticated users."""
        response = client.get("/diet-plan/documents")
        assert response.status_code == 401


class TestDietPlanHistory:
    """Tests for the diet plan history."""

    def test_history_endpoint_renders(self, authenticated_client):
        """History should return 200 for authenticated users."""
        response = authenticated_client.get("/diet-plan/history")
        assert response.status_code == 200

    def test_history_shows_user_plans(self, authenticated_client, db_session, test_user):
        """History should display the user's diet plans."""
        plan = DietPlan(
            id=uuid.uuid4(),
            user_id=test_user.id,
            document_ids=[str(uuid.uuid4())],
            plan_title="Test Diet Plan",
            plan_summary="A test diet plan for unit testing",
            foods_to_eat=[{"food_name": "Vegetables"}, {"food_name": "Lean protein"}],
            foods_to_avoid=[{"food_name": "Processed sugar"}],
            weekly_meal_plan={
                "Monday": {"breakfast": "Oatmeal", "lunch": "Salad", "dinner": "Grilled chicken"},
            },
            nutritional_guidelines={"calories": 2000, "protein": "80g"},
            allergy_notes=["Avoid peanuts"],
            generated_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(plan)
        db_session.commit()

        response = authenticated_client.get("/diet-plan/history")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert data[0]["plan_title"] == "Test Diet Plan"


class TestDietPlanGeneration:
    """Tests for AI diet plan generation."""

    @patch("routes.create_diet_plan")
    def test_generate_diet_plan_success(self, mock_create, authenticated_client, db_session, test_user):
        """Generate should succeed with valid document selection."""
        doc_id = uuid.uuid4()
        doc = Document(
            id=doc_id,
            user_id=test_user.id,
            document_type="lab_report",
            original_filename="lab_results.pdf",
            blob_name="lab-blob.pdf",
            blob_url="https://storage.blob.core.windows.net/lab-blob.pdf",
            ocr_status="completed",
            ocr_content="Blood sugar: 95 mg/dL",
            uploaded_at=datetime.utcnow(),
        )
        db_session.add(doc)
        db_session.commit()

        mock_plan = MagicMock()
        mock_plan.id = uuid.uuid4()
        mock_plan.plan_title = "Generated Diet Plan"
        mock_plan.plan_summary = "A test plan summary"
        mock_plan.foods_to_eat = []
        mock_plan.foods_to_avoid = []
        mock_plan.weekly_meal_plan = {}
        mock_plan.nutritional_guidelines = {}
        mock_plan.allergy_notes = []
        mock_plan.additional_recommendations = []
        mock_create.return_value = mock_plan

        response = authenticated_client.post(
            "/diet-plan/generate",
            json={
                "document_ids": [str(doc_id)],
                "additional_notes": "I prefer vegetarian meals",
            }
        )
        assert response.status_code == 200
        assert response.json()["plan_title"] == "Generated Diet Plan"

    def test_generate_without_documents(self, authenticated_client):
        """Generate should return 400 without selecting any documents."""
        response = authenticated_client.post(
            "/diet-plan/generate",
            json={
                "document_ids": [],
                "additional_notes": "",
            }
        )
        assert response.status_code == 400
        assert "error" in response.json()


class TestDietPlanDetail:
    """Tests for viewing individual diet plan details."""

    def test_view_own_plan(self, authenticated_client, db_session, test_user):
        """Users should be able to view their own diet plans."""
        plan_id = uuid.uuid4()
        plan = DietPlan(
            id=plan_id,
            user_id=test_user.id,
            document_ids=[str(uuid.uuid4())],
            plan_title="My Diet Plan",
            plan_summary="Personalized plan for the test user",
            foods_to_eat=[{"food_name": "Fruits"}, {"food_name": "Vegetables"}],
            foods_to_avoid=[{"food_name": "Allergens"}],
            weekly_meal_plan={},
            nutritional_guidelines={},
            allergy_notes=[],
            generated_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(plan)
        db_session.commit()

        response = authenticated_client.get(f"/diet-plan/{plan_id}")
        assert response.status_code == 200
        assert response.json()["plan_title"] == "My Diet Plan"

    def test_view_nonexistent_plan(self, authenticated_client):
        """Viewing a non-existent plan should return 404."""
        fake_id = uuid.uuid4()
        response = authenticated_client.get(f"/diet-plan/{fake_id}")
        assert response.status_code == 404

    def test_view_other_users_plan(self, authenticated_client, db_session):
        """Users should not be able to view other users' diet plans."""
        other_user_id = uuid.uuid4()
        plan_id = uuid.uuid4()
        plan = DietPlan(
            id=plan_id,
            user_id=other_user_id,
            document_ids=[],
            plan_title="Not My Plan",
            plan_summary="Someone else's plan",
            foods_to_eat=[],
            foods_to_avoid=[],
            weekly_meal_plan={},
            nutritional_guidelines={},
            allergy_notes=[],
            generated_at=datetime.utcnow(),
            is_active=True,
        )
        db_session.add(plan)
        db_session.commit()

        response = authenticated_client.get(f"/diet-plan/{plan_id}")
        assert response.status_code in [403, 404]


class TestAllergyAwareness:
    """Tests for allergy integration in diet planning."""

    def test_allergies_shown_on_documents_page(self, authenticated_client, db_session, test_user):
        """Documents page should display user's food allergies."""
        allergy = FoodAllergy(
            id=uuid.uuid4(),
            user_id=test_user.id,
            allergen_name="Peanuts",
            severity="severe",
            notes="Anaphylaxis risk",
        )
        db_session.add(allergy)
        db_session.commit()

        response = authenticated_client.get("/diet-plan/documents")
        assert response.status_code == 200
        data = response.json()
        assert len(data["allergies"]) > 0
        assert data["allergies"][0]["allergen_name"] == "Peanuts"


class TestDietPlanService:
    """Tests for the diet plan service layer."""

    @patch("services.generate_diet_plan_ai")
    def test_create_diet_plan_includes_profile_data(self, mock_generate, db_session, test_user):
        """create_diet_plan should fetch and pass medical conditions and dietary preferences."""
        from models import PatientProfile
        from services import create_diet_plan

        # Create patient profile
        profile = PatientProfile(
            id=uuid.uuid4(),
            user_id=test_user.id,
            medical_conditions={"conditions": ["Diabetes", "Hypertension"], "other": "Gout"},
            dietary_preferences=["vegetarian"],
        )
        db_session.add(profile)

        # Create completed document
        doc_id = uuid.uuid4()
        doc = Document(
            id=doc_id,
            user_id=test_user.id,
            document_type="lab_report",
            original_filename="lab.pdf",
            blob_name="lab.pdf",
            blob_url="https://storage.blob.core.windows.net/lab.pdf",
            ocr_status="completed",
            ocr_content="Glucose: 150 mg/dL",
            uploaded_at=datetime.utcnow(),
        )
        db_session.add(doc)
        db_session.commit()

        # Mock the AI generator response
        mock_generate.return_value = {
            "plan_title": "AI Tailored Diet Plan",
            "plan_summary": "Summary tailored to diabetes",
            "foods_to_eat": [{"food_name": "Vegetables"}],
            "foods_to_avoid": [{"food_name": "Sugary drinks"}],
            "weekly_meal_plan": {},
            "nutritional_guidelines": {},
            "allergy_notes": [],
            "additional_recommendations": [],
        }

        # Generate plan
        plan = create_diet_plan(
            db=db_session,
            user_id=str(test_user.id),
            document_ids=[str(doc_id)],
            additional_notes="None",
        )

        assert plan is not None
        assert mock_generate.called
        called_args, called_kwargs = mock_generate.call_args
        
        # Verify the profile parameters were passed to generate_diet_plan
        assert called_kwargs["medical_conditions"] == {"conditions": ["Diabetes", "Hypertension"], "other": "Gout"}
        assert called_kwargs["dietary_preferences"] == ["vegetarian"]
