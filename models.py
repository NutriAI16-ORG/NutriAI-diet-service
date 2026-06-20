"""
Diet Service - Database Models
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey, JSON, Enum, Float, Integer
from sqlalchemy.dialects.postgresql import UUID

from database import Base


class DietPlan(Base):
    __tablename__ = "diet_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    document_ids = Column(JSON, default=list)
    plan_title = Column(String(500), nullable=False)
    plan_summary = Column(Text, nullable=True)
    foods_to_eat = Column(JSON, default=list)
    foods_to_avoid = Column(JSON, default=list)
    weekly_meal_plan = Column(JSON, default=dict)
    nutritional_guidelines = Column(JSON, default=dict)
    allergy_notes = Column(JSON, default=list)
    additional_recommendations = Column(JSON, default=list)
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class Document(Base):
    """Read-only reference for fetching OCR content."""
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    document_type = Column(String(50))
    original_filename = Column(String(500), nullable=False)
    blob_name = Column(String(500))
    blob_url = Column(String(1000))
    ocr_content = Column(Text, nullable=True)
    ocr_status = Column(String(20))
    uploaded_at = Column(DateTime)


class FoodAllergy(Base):
    """Read-only reference for allergy data."""
    __tablename__ = "food_allergies"

    id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    allergen_name = Column(String(255), nullable=False)
    severity = Column(String(20))
    notes = Column(Text, nullable=True)


class PatientProfile(Base):
    """Read-only reference for medical conditions and dietary preferences."""
    __tablename__ = "patient_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    medical_conditions = Column(JSON, default=dict)
    dietary_preferences = Column(JSON, default=list)
    blood_type = Column(String(10))
    emergency_contact = Column(String(255))


class User(Base):
    """Read-only reference for user email (for meal reminders)."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True)
    email = Column(String(255), nullable=False)
    full_name = Column(String(255))
    username = Column(String(100))
    hashed_password = Column(String(255))
    age = Column(Integer)
    gender = Column(String(20))
    weight = Column(Float)
    height = Column(Float)
    auth_type = Column(String(20))
    entra_oid = Column(String(255))
    role = Column(String(20))
    is_active = Column(Boolean)
    created_at = Column(DateTime)
