"""
Diet Service - Business Logic
GPT-4 diet plan generation with validation/retry, PDF generation,
and Azure Service Bus meal reminder publishing.
"""

import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from uuid import UUID

from openai import AzureOpenAI
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
try:
    from azure.servicebus.exceptions import ServiceBusError
except ImportError:
    class ServiceBusError(Exception):
        pass
from app.models import Document, DietPlan, FoodAllergy, User, PatientProfile

logger = logging.getLogger(__name__)
settings = get_settings()


# ============================================================
# OpenAI / GPT-4
# ============================================================

def get_openai_client() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=settings.AZURE_OPENAI_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION,
    )


def truncate_to_tokens(text: str, max_tokens: int = 4000) -> str:
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.8:
        truncated = truncated[:last_space]
    return truncated + "\n\n[Content truncated due to length]"


def _build_allergy_section(allergies: list) -> str:
    """Build the allergy block for the system prompt."""
    if not allergies:
        return "\n\nNo known food allergies reported for this patient."
    lines = "\n\n⚠️ CRITICAL PATIENT ALLERGIES - NEVER RECOMMEND THESE FOODS:\n"
    for allergy in allergies:
        lines += f"- {allergy['allergen_name']} (Severity: {allergy['severity'].upper()})"
        if allergy.get('notes'):
            lines += f" - Notes: {allergy['notes']}"
        lines += "\n"
    lines += (
        "\nYou MUST NEVER recommend any food containing the above allergens. "
        "This is a medical safety requirement. If any allergen is found in a food item, "
        "it MUST be listed in foods_to_avoid with appropriate risk level. "
        "Include specific allergy warnings in the allergy_notes field."
    )
    return lines


def _build_conditions_section(medical_conditions) -> str:
    """Build the medical conditions block for the system prompt."""
    if not medical_conditions:
        return ""
    if isinstance(medical_conditions, dict):
        conditions_list = list(medical_conditions.get("conditions", []))
        other_text = medical_conditions.get("other", "")
        if other_text:
            conditions_list.append(other_text)
    else:
        conditions_list = list(medical_conditions)
    conditions_list = [c for c in conditions_list if c and c != "None"]
    if not conditions_list:
        return ""
    return (
        f"\n\n🏥 PATIENT MEDICAL CONDITIONS:\n"
        f"The patient has the following medical conditions: {', '.join(conditions_list)}.\n"
        "You MUST tailor recommendations for the medical conditions (e.g., if diabetic, suggest low-glycemic foods;\n"
        "if hypertensive, recommend low-sodium options; if pregnant, ensure adequate folic acid and iron)."
    )


def _build_preferences_section(dietary_preferences: list) -> str:
    """Build the dietary preferences block for the system prompt."""
    if not dietary_preferences:
        return ""
    return (
        f"\n\n🍽️ PATIENT DIETARY PREFERENCES:\n"
        f"The patient follows these dietary preferences: {', '.join(dietary_preferences)}.\n"
        "You MUST respect ALL dietary preferences (e.g., if vegetarian, do not recommend meat, poultry, or fish;\n"
        "if vegan, exclude all animal products; if halal or kosher, ensure all foods comply with those requirements;\n"
        "if keto, focus on high-fat low-carb options). Violating dietary preferences is NOT acceptable."
    )


def build_system_prompt(
    allergies: list,
    medical_conditions: dict = None,
    dietary_preferences: list = None,
    enhanced: bool = False,
) -> str:
    allergy_section = _build_allergy_section(allergies)
    conditions_section = _build_conditions_section(medical_conditions)
    preferences_section = _build_preferences_section(dietary_preferences)

    enhanced_instruction = ""
    if enhanced:
        enhanced_instruction = (
            "\n\nIMPORTANT: You MUST include at least 5 foods to eat and at least 5 foods to avoid.\n"
            "Each food_to_eat item MUST have food_name, reason, portion_size, and timing fields.\n"
            "Each food_to_avoid item MUST have food_name, reason, and risk_level fields.\n"
            "Failure to include these fields will result in rejection of your response."
        )

    system_prompt = f"""You are a professional clinical nutritionist and dietitian AI assistant for the NutriAI Health Portal.
Your role is to analyze patient medical documents (lab reports, prescriptions, etc.), identify any current disease or medical findings from the reports, and generate personalized, safe, and medically-appropriate diet plans.

{allergy_section}
{conditions_section}
{preferences_section}
{enhanced_instruction}

You MUST respond with valid JSON in the following exact structure:
{{
    "plan_title": "A descriptive title for the diet plan",
    "plan_summary": "A 2-3 sentence summary of the overall diet plan and its goals",
    "foods_to_eat": [
        {{
            "food_name": "Name of the food",
            "reason": "Medical reason why this food is recommended",
            "portion_size": "Recommended portion size (e.g., '1 cup', '100g')",
            "timing": "When to eat (e.g., 'Morning', 'With lunch')",
            "frequency": "How often (e.g., 'Daily', '3 times per week')"
        }}
    ],
    "foods_to_avoid": [
        {{
            "food_name": "Name of the food to avoid",
            "reason": "Medical reason why this food should be avoided",
            "risk_level": "high/medium/low"
        }}
    ],
    "weekly_meal_plan": {{
        "monday": {{
            "breakfast": "Detailed breakfast description",
            "lunch": "Detailed lunch description",
            "dinner": "Detailed dinner description",
            "snacks": "Recommended snacks"
        }},
        "tuesday": {{ ... }},
        "wednesday": {{ ... }},
        "thursday": {{ ... }},
        "friday": {{ ... }},
        "saturday": {{ ... }},
        "sunday": {{ ... }}
    }},
    "nutritional_guidelines": {{
        "daily_calories": 2000,
        "protein_grams": 60,
        "carbs_grams": 250,
        "fats_grams": 65,
        "fiber_grams": 30,
        "water_liters": 2.5
    }},
    "allergy_notes": [
        "Specific allergy-related warnings and notes"
    ],
    "additional_recommendations": [
        "Additional lifestyle and dietary recommendations"
    ]
}}

Guidelines:
1. Base your recommendations on the medical data provided in the documents. Specifically, identify any current diseases, conditions, or clinical findings indicated in the reports.
2. Consider the patient's previous medical conditions/diseases when making recommendations.
3. Incorporate recommendations based on both the current identified disease from the reports and the previous diseases.
4. Respect all dietary preferences / food categories chosen by the patient — never include foods that violate them.
5. Always prioritize patient safety, especially regarding allergies. Never recommend any foods the patient is allergic to.
6. Provide a 2-3 sentence overall summary of the diet plan in the `plan_summary` field. In this summary, explicitly mention the current identified disease from the reports, how it interacts with the patient's previous diseases, and how the diet plan addresses both.
7. Be specific with food names, portions, and timing.
8. Ensure the weekly meal plan is varied and nutritionally balanced.
9. Include all 7 days (monday through sunday) in the weekly meal plan.
10. Each day must have breakfast, lunch, dinner, and snacks.
"""
    return system_prompt


def _validate_food_list(data: dict, key: str, required_sub_fields: list) -> bool:
    """Check that a food list field is a non-empty list with all required sub-fields present."""
    items = data.get(key)
    if not isinstance(items, list) or not items:
        logger.warning("%s is empty or not a list", key)
        return False
    for item in items:
        if not isinstance(item, dict):
            return False
        for req in required_sub_fields:
            if not item.get(req):
                logger.warning("%s item missing '%s'", key, req)
                return False
    return True


def validate_diet_plan_json(data: dict) -> bool:
    """Validate the GPT-4 response structure including food item fields."""
    required_fields = [
        "plan_title", "plan_summary", "foods_to_eat", "foods_to_avoid",
        "weekly_meal_plan", "nutritional_guidelines", "allergy_notes", "additional_recommendations",
    ]
    for field in required_fields:
        if field not in data:
            logger.warning("Missing required field: %s", field)
            return False
    if not _validate_food_list(data, "foods_to_eat", ["food_name", "reason", "portion_size", "timing"]):
        return False
    if not _validate_food_list(data, "foods_to_avoid", ["food_name", "reason", "risk_level"]):
        return False
    if not isinstance(data["nutritional_guidelines"], dict):
        return False
    return True





def generate_diet_plan_ai(
    ocr_content: str,
    allergies: list,
    medical_conditions: dict = None,
    dietary_preferences: list = None,
    additional_notes: Optional[str] = None,
) -> Optional[dict]:
    """
    Generate a diet plan with up to 3 attempts (retry with enhanced prompt).
    If OpenAI configuration is missing/placeholder or all attempts fail,
    falls back to a locally generated mock diet plan.
    """
    openai_key = settings.AZURE_OPENAI_KEY
    openai_endpoint = settings.AZURE_OPENAI_ENDPOINT
    is_mock = (
        not openai_key
        or openai_key == ""
        or "your-" in openai_key
        or openai_key.startswith("<")
        or not openai_endpoint
        or openai_endpoint == ""
        or "your-" in openai_endpoint
        or openai_endpoint.startswith("<")
    )

    if is_mock:
        logger.error("Azure OpenAI key or endpoint is empty or placeholder. AI service is not configured.")
        return None

    client = get_openai_client()
    truncated_content = truncate_to_tokens(ocr_content, max_tokens=4000)

    for attempt in range(3):
        try:
            enhanced = attempt > 0
            system_prompt = build_system_prompt(
                allergies,
                medical_conditions=medical_conditions,
                dietary_preferences=dietary_preferences,
                enhanced=enhanced,
            )

            user_message = f"""Please analyze the following medical document content and generate a personalized diet plan.

--- MEDICAL DOCUMENT CONTENT ---
{truncated_content}
--- END DOCUMENT CONTENT ---
"""
            if additional_notes:
                user_message += f"""
--- ADDITIONAL PATIENT NOTES ---
{additional_notes}
--- END NOTES ---
"""

            logger.info(f"GPT-4 attempt {attempt + 1}/3 (enhanced={enhanced})")

            response = client.chat.completions.create(
                model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_completion_tokens=4000,
            )

            response_text = response.choices[0].message.content
            diet_plan_data = json.loads(response_text)

            if validate_diet_plan_json(diet_plan_data):
                logger.info(f"Diet plan generated successfully on attempt {attempt + 1}")
                return diet_plan_data
            else:
                logger.warning(f"Validation failed on attempt {attempt + 1}")

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error on attempt {attempt + 1}: {e}")
        except (ValueError, OSError, RuntimeError) as e:
            logger.error(f"OpenAI error on attempt {attempt + 1}: {e}")

    logger.error("All 3 diet plan generation attempts failed. AI service is currently unavailable.")
    return None


# ============================================================
# Service Bus - Meal Reminder Publishing
# ============================================================

def _build_food_lists(diet_plan: DietPlan) -> tuple:
    """Return (foods_eat, foods_avoid) lists serialised for Service Bus messages."""
    foods_eat = [
        {
            "food_name": f.get("food_name", ""),
            "portion_size": f.get("portion_size", ""),
            "timing": f.get("timing", ""),
            "reason": f.get("reason", ""),
        }
        for f in (diet_plan.foods_to_eat or [])
    ]
    foods_avoid = [
        {
            "food_name": f.get("food_name", ""),
            "reason": f.get("reason", ""),
            "risk_level": f.get("risk_level", ""),
        }
        for f in (diet_plan.foods_to_avoid or [])
    ]
    return foods_eat, foods_avoid


def _send_scheduled_meal_messages(sender, diet_plan: DietPlan, now, today) -> int:
    """Send per-meal scheduled Service Bus messages. Returns the count sent."""
    from azure.servicebus import ServiceBusMessage  # imported inside to stay optional

    meal_times = {
        "breakfast": 8,
        "lunch": 13,
        "snack": 16,
        "dinner": 19,
    }
    foods_eat, foods_avoid = _build_food_lists(diet_plan)
    weekly_plan = diet_plan.weekly_meal_plan or {}
    messages_sent = 0

    for day_index in range(7):
        day_date = today + timedelta(days=day_index)
        day_name = day_date.strftime("%A").lower()
        day_plan = weekly_plan.get(day_name, {})

        for meal_type, hour in meal_times.items():
            scheduled_time = datetime(day_date.year, day_date.month, day_date.day, hour, 0, 0)
            if scheduled_time <= now:
                continue
            meal_key = "snacks" if meal_type == "snack" else meal_type
            meal_description = day_plan.get(meal_key, day_plan.get(meal_type, ""))
            message_body = json.dumps({
                "user_id": str(diet_plan.user_id),
                "user_email": "",
                "meal_type": meal_type,
                "foods_to_eat": foods_eat,
                "foods_to_avoid": foods_avoid,
                "day_name": day_name.capitalize(),
                "meal_description": meal_description,
            })
            msg = ServiceBusMessage(
                body=message_body,
                content_type="application/json",
                subject=f"meal-reminder-{day_name}-{meal_type}",
                scheduled_enqueue_time_utc=scheduled_time,
            )
            sender.send_messages(msg)
            messages_sent += 1

    return messages_sent


def publish_meal_reminders(diet_plan: DietPlan, user_email: str, is_first_plan: bool = False):
    """
    Publish 28 messages (7 days × 4 meals) to Service Bus topic
    with scheduled_enqueue_time at actual meal times.
    """
    if not settings.AZURE_SERVICE_BUS_CONNECTION_STRING:
        logger.warning("Service Bus connection string not configured, skipping meal reminders")
        return

    try:
        from azure.servicebus import ServiceBusClient, ServiceBusMessage

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        today = now.date()
        servicebus_client = ServiceBusClient.from_connection_string(
            settings.AZURE_SERVICE_BUS_CONNECTION_STRING
        )

        with servicebus_client:
            sender = servicebus_client.get_topic_sender(topic_name=settings.AZURE_SERVICE_BUS_TOPIC_NAME)
            with sender:
                messages_sent = _send_scheduled_meal_messages(sender, diet_plan, now, today)

                if user_email and is_first_plan:
                    foods_eat, foods_avoid = _build_food_lists(diet_plan)
                    welcome_body = json.dumps({
                        "user_id": str(diet_plan.user_id),
                        "user_email": user_email,
                        "meal_type": "Welcome",
                        "foods_to_eat": foods_eat[:3],
                        "foods_to_avoid": foods_avoid[:3],
                        "day_name": "Today",
                        "meal_description": (
                            "Welcome to NutriAI! Your personalized diet plan is ready. "
                            "This is an immediate test notification to confirm your email alerts are functioning correctly."
                        ),
                    })
                    welcome_msg = ServiceBusMessage(
                        body=welcome_body,
                        content_type="application/json",
                        subject="meal-reminder-welcome",
                    )
                    sender.send_messages(welcome_msg)
                    messages_sent += 1

                logger.info("Published %d meal reminder messages to Service Bus", messages_sent)

    except ImportError:
        logger.warning("azure-servicebus not installed, skipping meal reminders")
    except (ServiceBusError, OSError, RuntimeError, ValueError) as e:
        logger.error("Error publishing meal reminders to Service Bus: %s", e)


# ============================================================
# Diet Plan Orchestration
# ============================================================

def _fetch_documents(db: Session, user_id: UUID, document_ids: List[str]) -> tuple:
    """Return (documents list, combined_ocr string) for valid completed docs."""
    import uuid as _uuid
    documents = []
    combined_ocr = ""
    for doc_id_str in document_ids:
        try:
            doc_id = _uuid.UUID(doc_id_str) if isinstance(doc_id_str, str) else doc_id_str
        except ValueError:
            continue
        doc = db.query(Document).filter(
            Document.id == doc_id,
            Document.user_id == user_id,
            Document.ocr_status == "completed",
        ).first()
        if doc and doc.ocr_content:
            documents.append(doc)
            combined_ocr += f"\n--- Document: {doc.original_filename} (Type: {doc.document_type}) ---\n"
            combined_ocr += doc.ocr_content + "\n"
    return documents, combined_ocr


def _save_diet_plan(db: Session, user_id: UUID, documents: list, plan_data: dict) -> DietPlan:
    """Persist a new DietPlan record and return the refreshed instance."""
    diet_plan = DietPlan(
        user_id=user_id,
        document_ids=[str(d.id) for d in documents],
        plan_title=plan_data.get("plan_title", "Personalized Diet Plan"),
        plan_summary=plan_data.get("plan_summary", ""),
        foods_to_eat=plan_data.get("foods_to_eat", []),
        foods_to_avoid=plan_data.get("foods_to_avoid", []),
        weekly_meal_plan=plan_data.get("weekly_meal_plan", {}),
        nutritional_guidelines=plan_data.get("nutritional_guidelines", {}),
        allergy_notes=plan_data.get("allergy_notes", []),
        additional_recommendations=plan_data.get("additional_recommendations", []),
        is_active=True,
    )
    db.add(diet_plan)
    db.commit()
    db.refresh(diet_plan)
    return diet_plan


def create_diet_plan(
    db: Session,
    user_id,
    document_ids: List[str],
    additional_notes: Optional[str] = None,
) -> Optional[DietPlan]:
    try:
        import uuid as _uuid
        if isinstance(user_id, str):
            user_id = _uuid.UUID(user_id)

        documents, combined_ocr = _fetch_documents(db, user_id, document_ids)
        if not documents:
            logger.warning("No valid documents found for user: %s", user_id)
            return None

        # Gather allergies
        allergies = db.query(FoodAllergy).filter(FoodAllergy.user_id == user_id).all()
        allergy_list = [
            {"allergen_name": a.allergen_name, "severity": a.severity, "notes": a.notes or ""}
            for a in allergies
        ]

        # Fetch patient profile for medical conditions and dietary preferences
        patient_profile = db.query(PatientProfile).filter(PatientProfile.user_id == user_id).first()
        medical_conditions = patient_profile.medical_conditions if patient_profile else None
        dietary_preferences = patient_profile.dietary_preferences if patient_profile else None

        plan_data = generate_diet_plan_ai(
            ocr_content=combined_ocr,
            allergies=allergy_list,
            medical_conditions=medical_conditions,
            dietary_preferences=dietary_preferences,
            additional_notes=additional_notes,
        )
        if not plan_data:
            logger.error("All GPT-4 attempts failed")
            return None

        diet_plan = _save_diet_plan(db, user_id, documents, plan_data)

        is_first_plan = db.query(DietPlan).filter(DietPlan.user_id == user_id).count() == 1
        user = db.query(User).filter(User.id == user_id).first()
        user_email = user.email if user else ""
        publish_meal_reminders(diet_plan, user_email, is_first_plan=is_first_plan)

        logger.info("Diet plan created: %s", diet_plan.id)
        return diet_plan

    except (SQLAlchemyError, ValueError, OSError) as e:
        logger.error("Error creating diet plan: %s", e)
        db.rollback()
        return None


def get_diet_plans(db: Session, user_id) -> List[DietPlan]:
    import uuid as _uuid
    if isinstance(user_id, str):
        user_id = _uuid.UUID(user_id)
    return (
        db.query(DietPlan)
        .filter(DietPlan.user_id == user_id)
        .order_by(DietPlan.generated_at.desc())
        .all()
    )


def get_diet_plan_detail(db: Session, plan_id, user_id) -> Optional[DietPlan]:
    import uuid as _uuid
    if isinstance(user_id, str):
        user_id = _uuid.UUID(user_id)
    if isinstance(plan_id, str):
        plan_id = _uuid.UUID(plan_id)
    return (
        db.query(DietPlan)
        .filter(DietPlan.id == plan_id, DietPlan.user_id == user_id)
        .first()
    )


# ============================================================
# PDF Generation
# ============================================================

def generate_diet_plan_pdf(plan: DietPlan) -> bytes:
    buffer = io.BytesIO()
    # Margins set to 0.75 in (leaving 7.0 in printable width)
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch
    )

    styles = getSampleStyleSheet()
    
    # Redesigned typography hierarchy
    title_style = ParagraphStyle(
        "CustomTitle", parent=styles["Title"],
        fontSize=20, leading=24, textColor=colors.HexColor("#1E293B"),
        alignment=0, spaceAfter=8
    )
    
    heading_style = ParagraphStyle(
        "CustomHeading", parent=styles["Heading2"],
        fontSize=12, leading=16, textColor=colors.HexColor("#0F172A"),
        spaceAfter=6, spaceBefore=14, keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        "CustomBody", parent=styles["Normal"],
        fontSize=9, leading=13, textColor=colors.HexColor("#334155")
    )

    table_header_style = ParagraphStyle(
        "TableHeader", parent=styles["Normal"],
        fontSize=8.5, leading=11, textColor=colors.white, fontName="Helvetica-Bold"
    )
    
    table_cell_style = ParagraphStyle(
        "TableCell", parent=styles["Normal"],
        fontSize=8, leading=11, textColor=colors.HexColor("#334155")
    )

    elements = []

    # Beautiful top branding header band
    elements.append(Paragraph("<font color='#64748B' size='7'><b>NUTRIAI HEALTH PORTAL</b></font>", body_style))
    elements.append(Paragraph(plan.plan_title, title_style))
    elements.append(Paragraph(f"Generated on {plan.generated_at.strftime('%B %d, %Y')}", body_style))
    
    # Visual divider
    divider = Table([[""]], colWidths=[7.0 * inch], rowHeights=[2])
    divider.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0F766E")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(divider)
    elements.append(Spacer(1, 12))

    if plan.plan_summary:
        elements.append(Paragraph("Plan Summary", heading_style))
        elements.append(Paragraph(plan.plan_summary, body_style))
        elements.append(Spacer(1, 10))

    # 3. Weekly Meal Plan Table
    _BR = "<br/>"
    if plan.weekly_meal_plan:
        elements.append(Paragraph("📅 Weekly Meal Plan", heading_style))
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        table_data = []
        for day in days:
            day_plan = plan.weekly_meal_plan.get(day, {})
            if day_plan:
                meals_paragraphs = [
                    f"<b>{meal_type.capitalize()}:</b> {day_plan[meal_type]}"
                    for meal_type in ["breakfast", "lunch", "dinner", "snacks"]
                    if day_plan.get(meal_type)
                ]
                meals_html = _BR.join(meals_paragraphs)
                table_data.append([
                    Paragraph(f"<b>{day.capitalize()}</b>", table_cell_style),
                    Paragraph(meals_html, table_cell_style)
                ])
        if table_data:
            table = Table(table_data, colWidths=[1.2 * inch, 5.8 * inch])
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#F8FAFC"), colors.white]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 10))

    # 1. Foods to Eat Table
    if plan.foods_to_eat:
        elements.append(Paragraph("✅ Foods to Eat", heading_style))
        table_data = [[
            Paragraph("<b>Food</b>", table_header_style),
            Paragraph("<b>Reason</b>", table_header_style),
            Paragraph("<b>Portion</b>", table_header_style),
            Paragraph("<b>Timing</b>", table_header_style)
        ]]
        for food in plan.foods_to_eat:
            table_data.append([
                Paragraph(food.get("food_name", "") or "", table_cell_style),
                Paragraph(food.get("reason", "") or "", table_cell_style),
                Paragraph(food.get("portion_size", "") or "", table_cell_style),
                Paragraph(food.get("timing", "") or "", table_cell_style),
            ])
        table = Table(table_data, colWidths=[1.8 * inch, 2.6 * inch, 1.2 * inch, 1.4 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F766E")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8FAFC"), colors.white]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 10))

    # 2. Foods to Avoid Table
    if plan.foods_to_avoid:
        elements.append(Paragraph("❌ Foods to Avoid", heading_style))
        table_data = [[
            Paragraph("<b>Food</b>", table_header_style),
            Paragraph("<b>Reason</b>", table_header_style),
            Paragraph("<b>Risk Level</b>", table_header_style)
        ]]
        for food in plan.foods_to_avoid:
            table_data.append([
                Paragraph(food.get("food_name", "") or "", table_cell_style),
                Paragraph(food.get("reason", "") or "", table_cell_style),
                Paragraph(food.get("risk_level", "") or "", table_cell_style),
            ])
        table = Table(table_data, colWidths=[2.2 * inch, 3.4 * inch, 1.4 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#991B1B")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#FFF5F5"), colors.white]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 10))

    # 4. Nutritional Guidelines Dashboard
    if plan.nutritional_guidelines:
        elements.append(Paragraph("📊 Nutritional Guidelines", heading_style))
        ng = plan.nutritional_guidelines
        
        metrics_headers = [
            Paragraph("<b>Calories</b>", table_header_style),
            Paragraph("<b>Protein</b>", table_header_style),
            Paragraph("<b>Carbs</b>", table_header_style),
            Paragraph("<b>Fats</b>", table_header_style),
            Paragraph("<b>Fiber</b>", table_header_style),
            Paragraph("<b>Water</b>", table_header_style)
        ]
        metrics_values = [
            Paragraph(f"{ng.get('daily_calories', 'N/A')} kcal", table_cell_style),
            Paragraph(f"{ng.get('protein_grams', 'N/A')}g", table_cell_style),
            Paragraph(f"{ng.get('carbs_grams', 'N/A')}g", table_cell_style),
            Paragraph(f"{ng.get('fats_grams', 'N/A')}g", table_cell_style),
            Paragraph(f"{ng.get('fiber_grams', 'N/A')}g", table_cell_style),
            Paragraph(f"{ng.get('water_liters', 'N/A')}L", table_cell_style)
        ]
        
        table_data = [metrics_headers, metrics_values]
        col_w = (7.0 / 6.0) * inch
        table = Table(table_data, colWidths=[col_w] * 6)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 10))

    # 5. Allergy Notes Callout Box
    if plan.allergy_notes:
        elements.append(Paragraph("⚠️ Allergy Notes", heading_style))
        notes_text = _BR.join([f"• {note}" for note in plan.allergy_notes])
        alert_style = ParagraphStyle(
            "AllergyAlert", parent=styles["Normal"],
            fontSize=8.5, leading=12, textColor=colors.HexColor("#78350F")
        )
        table_data = [[Paragraph(notes_text, alert_style)]]
        table = Table(table_data, colWidths=[7.0 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEF3C7")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#FBBF24")),
            ("LINELEFT", (0, 0), (-0, -1), 3.0, colors.HexColor("#D97706")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 10))

    # 6. Additional Recommendations Callout Box
    if plan.additional_recommendations:
        elements.append(Paragraph("💡 Additional Recommendations", heading_style))
        recs_text = _BR.join([f"• {rec}" for rec in plan.additional_recommendations])
        info_style = ParagraphStyle(
            "InfoAlert", parent=styles["Normal"],
            fontSize=8.5, leading=12, textColor=colors.HexColor("#1E3A8A")
        )
        table_data = [[Paragraph(recs_text, info_style)]]
        table = Table(table_data, colWidths=[7.0 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
            ("LINELEFT", (0, 0), (-0, -1), 3.0, colors.HexColor("#3B82F6")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 12))

    # Custom canvas footer maker for page numbers and branding
    def add_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(0.75 * inch, 0.4 * inch, "NutriAI Health Portal | Personalized Guidance")
        canvas.drawRightString(8.5 * inch - 0.75 * inch, 0.4 * inch, f"Page {doc.page}")
        canvas.setStrokeColor(colors.HexColor("#E2E8F0"))
        canvas.setLineWidth(0.5)
        canvas.line(0.75 * inch, 0.5 * inch, 8.5 * inch - 0.75 * inch, 0.5 * inch)
        canvas.restoreState()

    doc.build(elements, onFirstPage=add_footer, onLaterPages=add_footer)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

