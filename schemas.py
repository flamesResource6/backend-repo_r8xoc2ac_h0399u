"""
Database Schemas for Claire Beltramo Psychomotrician Platform

Each Pydantic model represents a MongoDB collection (collection name is the lowercase of the class name).
"""
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import date


class Account(BaseModel):
    """User accounts (patients or admin)"""
    username: str = Field(..., description="Unique username")
    password_hash: str = Field(..., description="SHA256 password hash")
    role: str = Field("patient", description="Role: 'patient' or 'admin'")
    patient_id: Optional[str] = Field(None, description="Linked patient id for patient accounts")
    name: Optional[str] = Field(None, description="Display name")
    email: Optional[str] = Field(None, description="Email address")


class Patient(BaseModel):
    """Patients managed by the psychomotrician"""
    first_name: str
    last_name: str
    date_of_birth: date
    email: Optional[str] = None
    phone: Optional[str] = None
    parent_contact: Optional[str] = Field(None, description="Parent/guardian contact")
    address: Optional[str] = None
    notes: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class Session(BaseModel):
    """Therapy sessions for a patient"""
    patient_id: str
    date: date
    duration_min: int = Field(..., ge=10, le=180)
    focus: Optional[str] = Field(None, description="Main focus of the session")
    notes: Optional[str] = None
    payment_status: Optional[str] = Field("pending", description="pending | paid | waived")
    amount: Optional[float] = Field(None, ge=0)
