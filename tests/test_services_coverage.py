import uuid
import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from app.models import Document, DietPlan, FoodAllergy, User, PatientProfile


class TestGeneratePlanExceptionPath:

    @patch("app.routes.create_diet_plan", side_effect=RuntimeError("Unexpected failure"))
    def test_generate_plan_exception_returns_503(self, mock_create, authenticated_client, db_session, test_user):
        doc_id = uuid.uuid4()
        doc = Document(
            id=doc_id, user_id=test_user.id, document_type="lab_report",
            original_filename="lab.pdf", blob_name="lab.pdf",
            blob_url="https://example.com/lab.pdf",
            ocr_status="completed", ocr_content="Glucose: 150",
            uploaded_at=datetime.utcnow(),
        )
        db_session.add(doc)
        db_session.commit()
        response = authenticated_client.post(
            "/diet-plan/generate",
            json={"document_ids": [str(doc_id)], "additional_notes": ""},
        )
        assert response.status_code == 503
        assert "error" in response.json()

    @patch("app.routes.create_diet_plan", return_value=None)
    def test_generate_plan_none_returns_503(self, mock_create, authenticated_client, db_session, test_user):
        doc_id = uuid.uuid4()
        doc = Document(
            id=doc_id, user_id=test_user.id, document_type="lab_report",
            original_filename="lab.pdf", blob_name="lab.pdf",
            blob_url="https://example.com/lab.pdf",
            ocr_status="completed", ocr_content="Glucose: 150",
            uploaded_at=datetime.utcnow(),
        )
        db_session.add(doc)
        db_session.commit()
        response = authenticated_client.post(
            "/diet-plan/generate",
            json={"document_ids": [str(doc_id)]},
        )
        assert response.status_code == 503

    def test_generate_plan_invalid_user_id(self, client):
        client.headers["X-User-ID"] = "not-a-uuid"
        response = client.post("/diet-plan/generate", json={"document_ids": [str(uuid.uuid4())]})
        assert response.status_code == 400

    def test_generate_plan_no_auth(self, client):
        response = client.post("/diet-plan/generate", json={"document_ids": [str(uuid.uuid4())]})
        assert response.status_code == 401


class TestRoutesPlanIdValidation:

    def test_plan_detail_invalid_plan_id(self, authenticated_client):
        response = authenticated_client.get("/diet-plan/not-a-valid-uuid")
        assert response.status_code == 400

    def test_pdf_download_invalid_plan_id(self, authenticated_client):
        response = authenticated_client.get("/diet-plan/bad-uuid/pdf")
        assert response.status_code == 400

    def test_pdf_download_plan_not_found(self, authenticated_client):
        fake_id = str(uuid.uuid4())
        response = authenticated_client.get(f"/diet-plan/{fake_id}/pdf")
        assert response.status_code == 404

    def test_pdf_download_success(self, authenticated_client, db_session, test_user):
        plan_id = uuid.uuid4()
        plan = DietPlan(
            id=plan_id, user_id=test_user.id, document_ids=[],
            plan_title="PDF Plan", plan_summary="Summary",
            foods_to_eat=[{"food_name": "Oats", "reason": "Fiber", "portion_size": "1 cup", "timing": "Morning"}],
            foods_to_avoid=[{"food_name": "Sugar", "reason": "Diabetes", "risk_level": "high"}],
            weekly_meal_plan={"monday": {"breakfast": "Oatmeal", "lunch": "Rice", "dinner": "Chicken", "snacks": "Apple"}},
            nutritional_guidelines={"daily_calories": 2000, "protein_grams": 60, "carbs_grams": 250, "fats_grams": 65, "fiber_grams": 30, "water_liters": 2.5},
            allergy_notes=["Avoid peanuts"],
            additional_recommendations=["Exercise daily"],
            generated_at=datetime.utcnow(), is_active=True,
        )
        db_session.add(plan)
        db_session.commit()
        response = authenticated_client.get(f"/diet-plan/{plan_id}/pdf")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

    def test_history_requires_auth(self, client):
        response = client.get("/diet-plan/history")
        assert response.status_code == 401

    def test_plan_detail_requires_auth(self, client):
        fake_id = str(uuid.uuid4())
        response = client.get(f"/diet-plan/{fake_id}")
        assert response.status_code == 401


class TestTruncateToTokens:

    def test_short_text_unchanged(self):
        from app.services import truncate_to_tokens
        text = "Short text"
        assert truncate_to_tokens(text, max_tokens=100) == text

    def test_long_text_truncated_at_space(self):
        from app.services import truncate_to_tokens
        text = "word " * 20
        result = truncate_to_tokens(text, max_tokens=10)
        assert "[Content truncated due to length]" in result
        assert len(result) < len(text)

    def test_long_text_no_space_near_end(self):
        from app.services import truncate_to_tokens
        text = "a b c d e" + "X" * 50
        result = truncate_to_tokens(text, max_tokens=5)
        assert "[Content truncated due to length]" in result


class TestBuildAllergySection:

    def test_no_allergies(self):
        from app.services import _build_allergy_section
        result = _build_allergy_section([])
        assert "No known food allergies" in result

    def test_allergy_with_notes(self):
        from app.services import _build_allergy_section
        allergies = [{"allergen_name": "Peanuts", "severity": "severe", "notes": "Anaphylaxis"}]
        result = _build_allergy_section(allergies)
        assert "Peanuts" in result
        assert "Anaphylaxis" in result

    def test_allergy_without_notes(self):
        from app.services import _build_allergy_section
        allergies = [{"allergen_name": "Shellfish", "severity": "mild", "notes": ""}]
        result = _build_allergy_section(allergies)
        assert "Shellfish" in result
        assert "Notes:" not in result


class TestBuildConditionsSection:

    def test_no_conditions_none(self):
        from app.services import _build_conditions_section
        assert _build_conditions_section(None) == ""

    def test_no_conditions_empty_list(self):
        from app.services import _build_conditions_section
        assert _build_conditions_section([]) == ""

    def test_dict_with_other(self):
        from app.services import _build_conditions_section
        result = _build_conditions_section({"conditions": ["Diabetes"], "other": "Gout"})
        assert "Diabetes" in result
        assert "Gout" in result

    def test_dict_without_other(self):
        from app.services import _build_conditions_section
        result = _build_conditions_section({"conditions": ["Hypertension"], "other": ""})
        assert "Hypertension" in result

    def test_list_form(self):
        from app.services import _build_conditions_section
        result = _build_conditions_section(["Diabetes", "Anemia"])
        assert "Diabetes" in result

    def test_all_none_strings_filtered(self):
        from app.services import _build_conditions_section
        assert _build_conditions_section(["None", ""]) == ""

    def test_dict_all_none_strings(self):
        from app.services import _build_conditions_section
        assert _build_conditions_section({"conditions": ["None"], "other": ""}) == ""


class TestBuildPreferencesSection:

    def test_empty(self):
        from app.services import _build_preferences_section
        assert _build_preferences_section([]) == ""
        assert _build_preferences_section(None) == ""

    def test_with_values(self):
        from app.services import _build_preferences_section
        result = _build_preferences_section(["vegetarian", "gluten-free"])
        assert "vegetarian" in result


class TestBuildSystemPrompt:

    def test_enhanced(self):
        from app.services import build_system_prompt
        result = build_system_prompt([], enhanced=True)
        assert "at least 5 foods" in result

    def test_basic(self):
        from app.services import build_system_prompt
        result = build_system_prompt([])
        assert "clinical nutritionist" in result


class TestValidateFoodList:

    def test_empty_list(self):
        from app.services import _validate_food_list
        assert _validate_food_list({"foods": []}, "foods", ["food_name"]) is False

    def test_not_a_list(self):
        from app.services import _validate_food_list
        assert _validate_food_list({"foods": "string"}, "foods", ["food_name"]) is False

    def test_item_not_dict(self):
        from app.services import _validate_food_list
        assert _validate_food_list({"foods": ["string1"]}, "foods", ["food_name"]) is False

    def test_missing_field(self):
        from app.services import _validate_food_list
        data = {"foods": [{"food_name": "Oats"}]}
        assert _validate_food_list(data, "foods", ["food_name", "reason"]) is False

    def test_valid(self):
        from app.services import _validate_food_list
        data = {"foods": [{"food_name": "Oats", "reason": "Fiber"}]}
        assert _validate_food_list(data, "foods", ["food_name", "reason"]) is True


class TestValidateDietPlanJson:

    def test_empty_dict(self):
        from app.services import validate_diet_plan_json
        assert validate_diet_plan_json({}) is False

    def test_guidelines_not_dict(self):
        from app.services import validate_diet_plan_json
        data = {
            "plan_title": "T", "plan_summary": "S",
            "foods_to_eat": [{"food_name": "X", "reason": "R", "portion_size": "1", "timing": "M"}],
            "foods_to_avoid": [{"food_name": "Y", "reason": "R", "risk_level": "high"}],
            "weekly_meal_plan": {}, "nutritional_guidelines": "bad",
            "allergy_notes": [], "additional_recommendations": [],
        }
        assert validate_diet_plan_json(data) is False

    def test_valid(self):
        from app.services import validate_diet_plan_json
        data = {
            "plan_title": "T", "plan_summary": "S",
            "foods_to_eat": [{"food_name": "X", "reason": "R", "portion_size": "1", "timing": "M"}],
            "foods_to_avoid": [{"food_name": "Y", "reason": "R", "risk_level": "high"}],
            "weekly_meal_plan": {}, "nutritional_guidelines": {},
            "allergy_notes": [], "additional_recommendations": [],
        }
        assert validate_diet_plan_json(data) is True


class TestGenerateDietPlanAiBranches:

    def test_empty_config_returns_none(self):
        from app.services import generate_diet_plan_ai
        with patch("app.services.settings") as s:
            s.AZURE_OPENAI_KEY = ""
            s.AZURE_OPENAI_ENDPOINT = ""
            result = generate_diet_plan_ai("ocr", [])
        assert result is None

    def test_placeholder_key_returns_none(self):
        from app.services import generate_diet_plan_ai
        with patch("app.services.settings") as s:
            s.AZURE_OPENAI_KEY = "your-key"
            s.AZURE_OPENAI_ENDPOINT = "https://real.com"
            result = generate_diet_plan_ai("ocr", [])
        assert result is None

    @patch("app.services.get_openai_client")
    def test_json_decode_error_returns_none(self, mock_get_client):
        from app.services import generate_diet_plan_ai
        mc = MagicMock()
        mock_get_client.return_value = mc
        choice = MagicMock()
        choice.message.content = "BAD JSON"
        resp = MagicMock()
        resp.choices = [choice]
        mc.chat.completions.create.return_value = resp
        assert generate_diet_plan_ai("ocr", []) is None

    @patch("app.services.get_openai_client")
    def test_openai_exception_returns_none(self, mock_get_client):
        from app.services import generate_diet_plan_ai
        mc = MagicMock()
        mock_get_client.return_value = mc
        mc.chat.completions.create.side_effect = Exception("API error")
        assert generate_diet_plan_ai("ocr", []) is None

    @patch("app.services.get_openai_client")
    def test_additional_notes_in_prompt(self, mock_get_client):
        from app.services import generate_diet_plan_ai
        mc = MagicMock()
        mock_get_client.return_value = mc
        valid = {
            "plan_title": "P", "plan_summary": "S",
            "foods_to_eat": [{"food_name": "Oats", "reason": "Fiber", "portion_size": "1c", "timing": "AM"}],
            "foods_to_avoid": [{"food_name": "Sugar", "reason": "Diabetes", "risk_level": "high"}],
            "weekly_meal_plan": {}, "nutritional_guidelines": {},
            "allergy_notes": [], "additional_recommendations": [],
        }
        choice = MagicMock()
        choice.message.content = json.dumps(valid)
        resp = MagicMock()
        resp.choices = [choice]
        mc.chat.completions.create.return_value = resp
        result = generate_diet_plan_ai("ocr", [], additional_notes="Low sodium please")
        assert result is not None
        call_kwargs = mc.chat.completions.create.call_args
        msgs = call_kwargs[1]["messages"] if call_kwargs[1] else call_kwargs[0][1]
        user_msg = next(m["content"] for m in msgs if m["role"] == "user")
        assert "Low sodium please" in user_msg


class TestFetchDocuments:

    def test_invalid_uuid_skipped(self, db_session, test_user):
        from app.services import _fetch_documents
        docs, combined = _fetch_documents(db_session, test_user.id, ["not-a-uuid"])
        assert docs == []

    def test_no_ocr_content_skipped(self, db_session, test_user):
        doc_id = uuid.uuid4()
        doc = Document(
            id=doc_id, user_id=test_user.id, document_type="lab_report",
            original_filename="lab.pdf", blob_name="lab.pdf",
            blob_url="https://example.com/lab.pdf",
            ocr_status="completed", ocr_content=None,
            uploaded_at=datetime.utcnow(),
        )
        db_session.add(doc)
        db_session.commit()
        from app.services import _fetch_documents
        docs, _ = _fetch_documents(db_session, test_user.id, [str(doc_id)])
        assert docs == []

    def test_pending_status_skipped(self, db_session, test_user):
        doc_id = uuid.uuid4()
        doc = Document(
            id=doc_id, user_id=test_user.id, document_type="lab_report",
            original_filename="lab.pdf", blob_name="lab.pdf",
            blob_url="https://example.com/lab.pdf",
            ocr_status="pending", ocr_content="text",
            uploaded_at=datetime.utcnow(),
        )
        db_session.add(doc)
        db_session.commit()
        from app.services import _fetch_documents
        docs, _ = _fetch_documents(db_session, test_user.id, [str(doc_id)])
        assert docs == []


class TestCreateDietPlanBranches:

    @patch("app.services.generate_diet_plan_ai")
    @patch("app.services.publish_meal_reminders")
    def test_no_background_tasks_direct_publish(self, mock_pub, mock_gen, db_session, test_user):
        from app.services import create_diet_plan
        doc_id = uuid.uuid4()
        doc = Document(
            id=doc_id, user_id=test_user.id, document_type="lab_report",
            original_filename="lab.pdf", blob_name="lab.pdf",
            blob_url="https://example.com/lab.pdf",
            ocr_status="completed", ocr_content="Glucose: 150",
            uploaded_at=datetime.utcnow(),
        )
        db_session.add(doc)
        db_session.commit()
        mock_gen.return_value = {
            "plan_title": "Plan", "plan_summary": "Test",
            "foods_to_eat": [{"food_name": "Oats"}],
            "foods_to_avoid": [{"food_name": "Sugar"}],
            "weekly_meal_plan": {}, "nutritional_guidelines": {},
            "allergy_notes": [], "additional_recommendations": [],
        }
        mock_pub.return_value = None
        plan = create_diet_plan(db=db_session, user_id=str(test_user.id), document_ids=[str(doc_id)], background_tasks=None)
        assert plan is not None
        assert mock_pub.called

    @patch("app.services.generate_diet_plan_ai", return_value=None)
    def test_ai_none_returns_none(self, mock_gen, db_session, test_user):
        from app.services import create_diet_plan
        doc_id = uuid.uuid4()
        doc = Document(
            id=doc_id, user_id=test_user.id, document_type="lab_report",
            original_filename="lab.pdf", blob_name="lab.pdf",
            blob_url="https://example.com/lab.pdf",
            ocr_status="completed", ocr_content="text",
            uploaded_at=datetime.utcnow(),
        )
        db_session.add(doc)
        db_session.commit()
        plan = create_diet_plan(db=db_session, user_id=str(test_user.id), document_ids=[str(doc_id)])
        assert plan is None

    def test_empty_docs_returns_none(self, db_session, test_user):
        from app.services import create_diet_plan
        assert create_diet_plan(db=db_session, user_id=str(test_user.id), document_ids=[]) is None

    def test_uuid_obj_user_id(self, db_session, test_user):
        from app.services import create_diet_plan
        assert create_diet_plan(db=db_session, user_id=test_user.id, document_ids=[]) is None


class TestPublishMealRemindersBranches:

    def test_plan_not_found(self, db_session):
        from app.services import publish_meal_reminders
        publish_meal_reminders(uuid.uuid4(), "user@example.com")

    @patch("app.services.settings.AZURE_SERVICE_BUS_CONNECTION_STRING", "Endpoint=sb://test")
    @patch("azure.servicebus.ServiceBusClient")
    def test_first_plan_sends_welcome(self, mock_sb, db_session, test_user):
        from app.services import publish_meal_reminders
        plan = DietPlan(
            id=uuid.uuid4(), user_id=test_user.id, plan_title="First",
            foods_to_eat=[{"food_name": "A", "portion_size": "1", "timing": "M", "reason": "R"},
                          {"food_name": "B", "portion_size": "1", "timing": "M", "reason": "R"},
                          {"food_name": "C", "portion_size": "1", "timing": "M", "reason": "R"}],
            foods_to_avoid=[{"food_name": "X", "reason": "R", "risk_level": "high"}],
            weekly_meal_plan={"monday": {"breakfast": "Oats", "lunch": "Rice", "dinner": "Chicken", "snacks": "Apple"}},
            generated_at=datetime.utcnow(),
        )
        db_session.add(plan)
        db_session.commit()
        sender = MagicMock()
        client = MagicMock()
        mock_sb.from_connection_string.return_value = client
        client.get_topic_sender.return_value = sender
        publish_meal_reminders(plan.id, "user@example.com", is_first_plan=True)
        assert sender.send_messages.called

    @patch("app.services.settings.AZURE_SERVICE_BUS_CONNECTION_STRING", "Endpoint=sb://test")
    @patch("azure.servicebus.ServiceBusClient")
    def test_past_plan_no_messages(self, mock_sb, db_session, test_user):
        from app.services import publish_meal_reminders
        plan = DietPlan(
            id=uuid.uuid4(), user_id=test_user.id, plan_title="Old",
            foods_to_eat=[], foods_to_avoid=[], weekly_meal_plan={},
            generated_at=datetime(2020, 1, 1),
        )
        db_session.add(plan)
        db_session.commit()
        sender = MagicMock()
        client = MagicMock()
        mock_sb.from_connection_string.return_value = client
        client.get_topic_sender.return_value = sender
        publish_meal_reminders(plan.id, "user@example.com")


class TestGetDietPlanHelpers:

    def test_get_plans_string_user_id(self, db_session, test_user):
        from app.services import get_diet_plans
        result = get_diet_plans(db_session, str(test_user.id))
        assert isinstance(result, list)

    def test_get_plan_detail_string_ids(self, db_session, test_user):
        from app.services import get_diet_plan_detail
        plan_id = uuid.uuid4()
        plan = DietPlan(
            id=plan_id, user_id=test_user.id, plan_title="Detail",
            foods_to_eat=[], foods_to_avoid=[], weekly_meal_plan={},
            nutritional_guidelines={}, allergy_notes=[],
            generated_at=datetime.utcnow(), is_active=True,
        )
        db_session.add(plan)
        db_session.commit()
        result = get_diet_plan_detail(db_session, str(plan_id), str(test_user.id))
        assert result is not None

    def test_get_plan_detail_wrong_user(self, db_session, test_user):
        from app.services import get_diet_plan_detail
        plan_id = uuid.uuid4()
        plan = DietPlan(
            id=plan_id, user_id=test_user.id, plan_title="Private",
            foods_to_eat=[], foods_to_avoid=[], weekly_meal_plan={},
            nutritional_guidelines={}, allergy_notes=[],
            generated_at=datetime.utcnow(), is_active=True,
        )
        db_session.add(plan)
        db_session.commit()
        result = get_diet_plan_detail(db_session, plan_id, uuid.uuid4())
        assert result is None


class TestGeneratePdfEdgeCases:

    def test_minimal_plan(self, test_user):
        from app.services import generate_diet_plan_pdf
        plan = DietPlan(
            id=uuid.uuid4(), user_id=test_user.id, plan_title="Min",
            plan_summary=None, foods_to_eat=[], foods_to_avoid=[],
            weekly_meal_plan={}, nutritional_guidelines={},
            allergy_notes=[], additional_recommendations=[],
            generated_at=datetime.utcnow(), is_active=True,
        )
        assert len(generate_diet_plan_pdf(plan)) > 0

    def test_empty_day_plan(self, test_user):
        from app.services import generate_diet_plan_pdf
        plan = DietPlan(
            id=uuid.uuid4(), user_id=test_user.id, plan_title="Empty Day",
            plan_summary="Test", foods_to_eat=[], foods_to_avoid=[],
            weekly_meal_plan={"monday": {}}, nutritional_guidelines={},
            allergy_notes=[], additional_recommendations=[],
            generated_at=datetime.utcnow(), is_active=True,
        )
        assert len(generate_diet_plan_pdf(plan)) > 0


class TestBuildFoodLists:

    def test_with_data(self, test_user):
        from app.services import _build_food_lists
        plan = DietPlan(
            id=uuid.uuid4(), user_id=test_user.id, plan_title="FL",
            foods_to_eat=[{"food_name": "Oats", "portion_size": "1c", "timing": "AM", "reason": "F"}],
            foods_to_avoid=[{"food_name": "Sugar", "reason": "D", "risk_level": "high"}],
            generated_at=datetime.utcnow(),
        )
        eat, avoid = _build_food_lists(plan)
        assert len(eat) == 1
        assert eat[0]["food_name"] == "Oats"
        assert len(avoid) == 1

    def test_none_fields(self, test_user):
        from app.services import _build_food_lists
        plan = DietPlan(
            id=uuid.uuid4(), user_id=test_user.id, plan_title="None",
            foods_to_eat=None, foods_to_avoid=None,
            generated_at=datetime.utcnow(),
        )
        eat, avoid = _build_food_lists(plan)
        assert eat == []
        assert avoid == []
