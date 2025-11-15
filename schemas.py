"""
Database Schemas for Library Management

Each Pydantic model represents a MongoDB collection.
Collection name is the lowercase of the class name:
- Book -> "book"
- Member -> "member"
- Loan -> "loan"
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date

class Book(BaseModel):
    title: str = Field(..., description="Book title")
    author: str = Field(..., description="Author name")
    isbn: Optional[str] = Field(None, description="ISBN identifier")
    category: Optional[str] = Field(None, description="Genre or category")
    total_copies: int = Field(1, ge=0, description="Total number of copies owned")
    available_copies: int = Field(1, ge=0, description="Currently available copies")
    tags: Optional[List[str]] = Field(default=None, description="Searchable tags")

class Member(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    phone: Optional[str] = Field(None, description="Phone number")
    is_active: bool = Field(True, description="Active membership status")

class Loan(BaseModel):
    member_id: str = Field(..., description="Member ObjectId as string")
    book_id: str = Field(..., description="Book ObjectId as string")
    due_date: Optional[date] = Field(None, description="Date when the book is due")
    returned: bool = Field(False, description="Whether the book has been returned")
