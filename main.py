import os
import hashlib
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Patient as PatientSchema, Session as SessionSchema, Account as AccountSchema

app = FastAPI(title="Claire Beltramo - Psychomotrician Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Helpers ----------
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)


def to_dict(doc):
    if not doc:
        return doc
    doc["id"] = str(doc.pop("_id"))
    # Convert datetime/date fields to isoformat if needed
    for k, v in list(doc.items()):
        if hasattr(v, "isoformat"):
            doc[k] = v.isoformat()
    return doc


def collection(name: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    return db[name]


def generate_username(first_name: str, last_name: str) -> str:
    return f"{first_name[:1].lower()}.{last_name.lower()}"


def format_default_password(last_name: str, dob_str: str) -> str:
    # dob_str expected format DDMMYYYY
    return f"{last_name.lower()}{dob_str}"


def sha256_hash(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


# ---------- Request/Response Models ----------
class PatientCreate(BaseModel):
    first_name: str
    last_name: str
    date_of_birth: str  # DD/MM/YYYY or YYYY-MM-DD supported
    email: Optional[str] = None
    phone: Optional[str] = None
    parent_contact: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class PatientUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    parent_contact: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class SessionCreate(BaseModel):
    patient_id: str
    date: str  # YYYY-MM-DD
    duration_min: int
    focus: Optional[str] = None
    notes: Optional[str] = None
    payment_status: Optional[str] = "pending"
    amount: Optional[float] = None


class AccountPublic(BaseModel):
    id: str
    username: str
    role: str
    patient_id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None


# ---------- Basic routes ----------
@app.get("/")
def read_root():
    return {"message": "Backend OK", "service": "Psychomotrician Platform"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set",
        "database_name": "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    return response


# ---------- Patients ----------
@app.get("/api/patients")
def list_patients(q: Optional[str] = Query(None, description="Search by name")):
    filt = {}
    if q:
        # simple case-insensitive search
        filt = {"$or": [
            {"first_name": {"$regex": q, "$options": "i"}},
            {"last_name": {"$regex": q, "$options": "i"}},
        ]}
    docs = list(collection("patient").find(filt).sort("last_name"))
    return [to_dict(d) for d in docs]


@app.get("/api/patients/{patient_id}")
def get_patient(patient_id: str):
    doc = collection("patient").find_one({"_id": PyObjectId.validate(patient_id)})
    if not doc:
        raise HTTPException(404, "Patient not found")
    return to_dict(doc)


@app.post("/api/patients")
def create_patient(payload: PatientCreate):
    # Normalize date
    dob_input = payload.date_of_birth.strip()
    if "/" in dob_input:
        # DD/MM/YYYY -> YYYY-MM-DD
        dd, mm, yyyy = dob_input.split("/")
        dob_iso = f"{yyyy}-{mm}-{dd}"
        dob_compact = f"{dd}{mm}{yyyy}"
    elif "-" in dob_input:
        yyyy, mm, dd = dob_input.split("-")
        dob_iso = dob_input
        dob_compact = f"{dd}{mm}{yyyy}"
    else:
        raise HTTPException(400, "date_of_birth must be DD/MM/YYYY or YYYY-MM-DD")

    p = PatientSchema(
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        date_of_birth=datetime.strptime(dob_iso, "%Y-%m-%d").date(),
        email=payload.email,
        phone=payload.phone,
        parent_contact=payload.parent_contact,
        address=payload.address,
        notes=payload.notes,
        tags=payload.tags or [],
    )

    # Insert patient
    pid = create_document("patient", p)

    # Auto account creation if missing
    username = generate_username(p.first_name, p.last_name)
    acc_col = collection("account")
    existing = acc_col.find_one({"username": username})
    if not existing:
        default_pass = format_default_password(p.last_name, dob_compact)
        acc = AccountSchema(
            username=username,
            password_hash=sha256_hash(default_pass),
            role="patient",
            patient_id=pid,
            name=f"{p.first_name} {p.last_name}",
            email=p.email,
        )
        create_document("account", acc)

    return {"id": pid, "username": username}


@app.put("/api/patients/{patient_id}")
def update_patient(patient_id: str, payload: PatientUpdate):
    update = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if "date_of_birth" in update:
        dob_input = update["date_of_birth"].strip()
        if "/" in dob_input:
            dd, mm, yyyy = dob_input.split("/")
            dob_iso = f"{yyyy}-{mm}-{dd}"
        elif "-" in dob_input:
            dob_iso = dob_input
        else:
            raise HTTPException(400, "date_of_birth must be DD/MM/YYYY or YYYY-MM-DD")
        update["date_of_birth"] = datetime.strptime(dob_iso, "%Y-%m-%d").date()

    res = collection("patient").update_one({"_id": PyObjectId.validate(patient_id)}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(404, "Patient not found")
    doc = collection("patient").find_one({"_id": PyObjectId.validate(patient_id)})
    return to_dict(doc)


@app.delete("/api/patients/{patient_id}")
def delete_patient(patient_id: str):
    res = collection("patient").delete_one({"_id": PyObjectId.validate(patient_id)})
    if res.deleted_count == 0:
        raise HTTPException(404, "Patient not found")
    # Optionally also delete sessions
    collection("session").delete_many({"patient_id": patient_id})
    return {"status": "deleted"}


@app.post("/api/patients/search")
def search_patient(last_name: str, date_of_birth: str):
    # date_of_birth: DD/MM/YYYY or YYYY-MM-DD
    dob_input = date_of_birth.strip()
    if "/" in dob_input:
        dd, mm, yyyy = dob_input.split("/")
        dob_iso = f"{yyyy}-{mm}-{dd}"
    elif "-" in dob_input:
        dob_iso = dob_input
    else:
        raise HTTPException(400, "date_of_birth must be DD/MM/YYYY or YYYY-MM-DD")

    dob = datetime.strptime(dob_iso, "%Y-%m-%d").date()
    doc = collection("patient").find_one({"last_name": {"$regex": f"^{last_name}$", "$options": "i"}, "date_of_birth": dob})
    if not doc:
        raise HTTPException(404, "Patient not found")
    return to_dict(doc)


# ---------- Sessions ----------
@app.get("/api/patients/{patient_id}/sessions")
def list_sessions(patient_id: str):
    docs = list(collection("session").find({"patient_id": patient_id}).sort("date", -1))
    return [to_dict(d) for d in docs]


@app.post("/api/sessions")
def create_session(payload: SessionCreate):
    # Parse date
    try:
        _ = datetime.strptime(payload.date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")

    s = SessionSchema(
        patient_id=payload.patient_id,
        date=_,
        duration_min=payload.duration_min,
        focus=payload.focus,
        notes=payload.notes,
        payment_status=payload.payment_status or "pending",
        amount=payload.amount,
    )
    sid = create_document("session", s)
    return {"id": sid}


# ---------- Accounts ----------
@app.get("/api/accounts/by-patient/{patient_id}")
def get_account_by_patient(patient_id: str):
    acc = collection("account").find_one({"patient_id": patient_id})
    if not acc:
        raise HTTPException(404, "Account not found")
    acc_d = to_dict(acc)
    # Remove sensitive
    acc_d.pop("password_hash", None)
    return acc_d


class ResetPasswordRequest(BaseModel):
    last_name: str
    date_of_birth: str  # DD/MM/YYYY or YYYY-MM-DD


@app.post("/api/accounts/reset-default/{patient_id}")
def reset_default_password(patient_id: str, payload: ResetPasswordRequest):
    # Compute default
    dob_input = payload.date_of_birth.strip()
    if "/" in dob_input:
        dd, mm, yyyy = dob_input.split("/")
        compact = f"{dd}{mm}{yyyy}"
    elif "-" in dob_input:
        yyyy, mm, dd = dob_input.split("-")
        compact = f"{dd}{mm}{yyyy}"
    else:
        raise HTTPException(400, "date_of_birth must be DD/MM/YYYY or YYYY-MM-DD")

    default_pass = format_default_password(payload.last_name, compact)
    res = collection("account").update_one({"patient_id": patient_id}, {"$set": {"password_hash": sha256_hash(default_pass)}})
    if res.matched_count == 0:
        raise HTTPException(404, "Account not found")
    return {"status": "ok"}
