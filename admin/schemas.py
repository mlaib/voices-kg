"""Pydantic request / response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from .models import Role


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    role: Role
    created_at: datetime
    last_login: Optional[datetime] = None
    active: bool


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=6)
    role: Role = Role.reviewer


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=6)


class MeResponse(BaseModel):
    email: str
    role: Role
    authenticated: bool = True


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    fuseki: Optional[str] = None
    meilisearch: Optional[str] = None
    redis: Optional[str] = None


class InterviewSummary(BaseModel):
    id: str
    survivor_label: Optional[str] = None


class InterviewDetail(BaseModel):
    id: str
    survivor_label: Optional[str] = None
    metadata: dict = {}
    counts: dict = {}


class EventSummary(BaseModel):
    id: str
    label: Optional[str] = None
    interview: Optional[str] = None
    activity: Optional[str] = None
    emotion: Optional[str] = None
    place: Optional[str] = None


class EventDetail(BaseModel):
    id: str
    label: Optional[str] = None
    interview: Optional[str] = None
    properties: dict = {}
    annotations: list = []


class PlaceSummary(BaseModel):
    id: str
    label: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class SearchHit(BaseModel):
    id: str
    text: str
    score: Optional[float] = None
    interview: Optional[str] = None


class SimilarHit(BaseModel):
    id: str
    score: float
