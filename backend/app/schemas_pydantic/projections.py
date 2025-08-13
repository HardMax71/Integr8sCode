"""Projection schemas for event projections"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ProjectionStatus(BaseModel):
    """Status information for a projection"""
    name: str
    description: Optional[str]
    status: str
    last_updated: datetime
    last_processed: Optional[datetime]
    source_events: List[str]
    output_collection: str
    error: Optional[str]

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ProjectionQueryRequest(BaseModel):
    """Request schema for querying projection data"""
    projection_name: str
    filters: Optional[Dict[str, Any]] = {}
    limit: int = 100
    skip: int = 0
    sort: Optional[Dict[str, int]] = None


class ProjectionActionRequest(BaseModel):
    """Request schema for projection management actions"""
    action: str
    projection_names: List[str]


class ProjectionQueryResponse(BaseModel):
    """Response schema for projection queries"""
    projection: str
    data: List[Dict[str, Any]]
    total: int
    limit: int
    skip: int


class ExecutionSummaryResponse(BaseModel):
    """Response schema for execution summary"""
    user_id: str
    period: Dict[str, Optional[str]]
    totals: Dict[str, Any]
    performance: Dict[str, Any]
    daily_summaries: List[Dict[str, Any]]


class ErrorAnalysisResponse(BaseModel):
    """Response schema for error analysis"""
    period: Dict[str, Optional[str]]
    filter: Dict[str, Optional[str]]
    error_types: Dict[str, Any]
    top_errors: List[Dict[str, Any]]


class LanguageUsageResponse(BaseModel):
    """Response schema for language usage stats"""
    month: Optional[str]
    languages: Dict[str, Any]
    total_languages: int
