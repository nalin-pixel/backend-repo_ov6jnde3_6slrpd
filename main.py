import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta, date

from database import db, create_document, get_documents
from schemas import Book as BookSchema, Member as MemberSchema, Loan as LoanSchema

try:
    from bson import ObjectId
except Exception:
    # Fallback minimal ObjectId validator (should not happen in this environment)
    ObjectId = str  # type: ignore

app = FastAPI(title="Library Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------
# Utility helpers
# ----------------------

def to_object_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID format")

def serialize(doc: dict) -> dict:
    if not doc:
        return doc
    d = {**doc}
    if d.get("_id") is not None:
        d["id"] = str(d.pop("_id"))
    # Convert datetime/date to isoformat for JSON
    for k, v in list(d.items()):
        if isinstance(v, (datetime, date)):
            d[k] = v.isoformat()
    return d

# ----------------------
# Health & Schema
# ----------------------

@app.get("/")
def read_root():
    return {"message": "Library Management Backend is running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_name"] = getattr(db, "name", "✅ Connected")
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    import os as _os
    response["database_url"] = "✅ Set" if _os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if _os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response

@app.get("/schema")
def get_schema():
    # Return JSON schema-like description for viewer tools
    return {
        "book": BookSchema.model_json_schema(),
        "member": MemberSchema.model_json_schema(),
        "loan": LoanSchema.model_json_schema(),
    }

# ----------------------
# Pydantic request models
# ----------------------

class CreateBook(BaseModel):
    title: str
    author: str
    isbn: Optional[str] = None
    category: Optional[str] = None
    total_copies: int = 1
    available_copies: int = 1
    tags: Optional[List[str]] = None

class UpdateBook(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    isbn: Optional[str] = None
    category: Optional[str] = None
    total_copies: Optional[int] = None
    available_copies: Optional[int] = None
    tags: Optional[List[str]] = None

class CreateMember(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None

class BorrowRequest(BaseModel):
    member_id: str
    book_id: str
    days: int = 14

class ReturnRequest(BaseModel):
    loan_id: str

# ----------------------
# Books Endpoints
# ----------------------

@app.post("/books")
def create_book(book: CreateBook):
    doc = BookSchema(**book.model_dump())
    new_id = create_document("book", doc)
    created = db["book"].find_one({"_id": to_object_id(new_id)})
    return serialize(created)

@app.get("/books")
def list_books(q: Optional[str] = Query(None, description="Search query")):
    filter_dict = {}
    if q:
        # Basic case-insensitive search on title/author/category/tags
        filter_dict = {
            "$or": [
                {"title": {"$regex": q, "$options": "i"}},
                {"author": {"$regex": q, "$options": "i"}},
                {"category": {"$regex": q, "$options": "i"}},
                {"tags": {"$elemMatch": {"$regex": q, "$options": "i"}}},
            ]
        }
    docs = db["book"].find(filter_dict).sort("title", 1)
    return [serialize(d) for d in docs]

@app.get("/books/{book_id}")
def get_book(book_id: str):
    doc = db["book"].find_one({"_id": to_object_id(book_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Book not found")
    return serialize(doc)

@app.put("/books/{book_id}")
def update_book(book_id: str, payload: UpdateBook):
    update = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not update:
        return get_book(book_id)
    update["updated_at"] = datetime.utcnow()
    result = db["book"].update_one({"_id": to_object_id(book_id)}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Book not found")
    return get_book(book_id)

@app.delete("/books/{book_id}")
def delete_book(book_id: str):
    loan_exists = db["loan"].find_one({"book_id": book_id, "returned": False})
    if loan_exists:
        raise HTTPException(status_code=400, detail="Cannot delete book with active loans")
    result = db["book"].delete_one({"_id": to_object_id(book_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Book not found")
    return {"status": "deleted", "id": book_id}

# ----------------------
# Members Endpoints
# ----------------------

@app.post("/members")
def create_member(member: CreateMember):
    existing = db["member"].find_one({"email": member.email})
    if existing:
        return serialize(existing)
    doc = MemberSchema(name=member.name, email=member.email, phone=member.phone)
    new_id = create_document("member", doc)
    created = db["member"].find_one({"_id": to_object_id(new_id)})
    return serialize(created)

@app.get("/members")
def list_members():
    docs = db["member"].find().sort("name", 1)
    return [serialize(d) for d in docs]

@app.get("/members/by-email")
def get_member_by_email(email: str):
    m = db["member"].find_one({"email": email})
    if not m:
        raise HTTPException(status_code=404, detail="Member not found")
    return serialize(m)

# ----------------------
# Loans Endpoints
# ----------------------

@app.get("/loans")
def list_loans(member_id: Optional[str] = None, active: Optional[bool] = None):
    filt = {}
    if member_id:
        filt["member_id"] = member_id
    if active is not None:
        filt["returned"] = not not (not not active)  # ensure boolean
        if active:
            filt["returned"] = False
        else:
            filt["returned"] = True
    docs = db["loan"].find(filt).sort("created_at", -1)
    return [serialize(d) for d in docs]

@app.get("/loans/by-email")
def loans_by_email(email: str):
    member = db["member"].find_one({"email": email})
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    member_id = str(member["_id"])
    loans = list(db["loan"].find({"member_id": member_id}).sort("created_at", -1))
    # Enrich with book info
    for l in loans:
        book = db["book"].find_one({"_id": to_object_id(l["book_id"])})
        l["book"] = {"title": book.get("title"), "author": book.get("author")} if book else None
    return [serialize(l) for l in loans]

@app.get("/loans/active")
def active_loans():
    loans = list(db["loan"].find({"returned": False}).sort("created_at", -1))
    enriched = []
    for l in loans:
        book = db["book"].find_one({"_id": to_object_id(l["book_id"])})
        member = db["member"].find_one({"_id": to_object_id(l["member_id"])})
        l["book"] = {"title": book.get("title"), "author": book.get("author")} if book else None
        l["member"] = {"name": member.get("name"), "email": member.get("email")} if member else None
        enriched.append(serialize(l))
    return enriched

@app.post("/loans/borrow")
def borrow_book(payload: BorrowRequest):
    # Validate book
    book = db["book"].find_one({"_id": to_object_id(payload.book_id)})
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if int(book.get("available_copies", 0)) <= 0:
        raise HTTPException(status_code=400, detail="No copies available")

    # Validate member
    member = db["member"].find_one({"_id": to_object_id(payload.member_id)})
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    due = datetime.utcnow() + timedelta(days=max(1, payload.days))
    loan_doc = LoanSchema(member_id=payload.member_id, book_id=payload.book_id, due_date=due.date(), returned=False)
    loan_id = create_document("loan", loan_doc)

    # Decrement available copies
    db["book"].update_one({"_id": to_object_id(payload.book_id)}, {"$inc": {"available_copies": -1}, "$set": {"updated_at": datetime.utcnow()}})

    created = db["loan"].find_one({"_id": to_object_id(loan_id)})
    return serialize(created)

@app.post("/loans/return")
def return_book(payload: ReturnRequest):
    loan = db["loan"].find_one({"_id": to_object_id(payload.loan_id)})
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    if loan.get("returned"):
        return serialize(loan)

    # Mark returned
    db["loan"].update_one({"_id": to_object_id(payload.loan_id)}, {"$set": {"returned": True, "updated_at": datetime.utcnow()}})

    # Increment available copies
    book_id = loan.get("book_id")
    if book_id:
        db["book"].update_one({"_id": to_object_id(book_id)}, {"$inc": {"available_copies": 1}, "$set": {"updated_at": datetime.utcnow()}})

    updated = db["loan"].find_one({"_id": to_object_id(payload.loan_id)})
    return serialize(updated)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
