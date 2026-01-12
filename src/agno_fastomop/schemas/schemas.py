from pydantic import BaseModel
from typing import List, Optional, Dict, Literal

class ConceptMapping(BaseModel):
    term: str
    concept_code: Optional[str] = None  # Allow None when concept not found
    concept_name: Optional[str] = None
    vocabulary_id: Optional[str] = None
    domain_id: Optional[Literal["Condition", "Drug", "Device", "Observation",
                         "Procedure", "Measurement", "Gender",
                         "Race", "Ethnicity", "Visit"]] = None
    concept_id: Optional[int] = None
    entity_order: Optional[int] = None  # NEW: Order of entity in query (1, 2, 3)

    # Intelligent concept selection fields
    selection_reasoning: Optional[str] = None  # Explanation of why this concept was chosen
    alternative_concepts_considered: Optional[List[int]] = None  # Other concept IDs evaluated
    estimated_patient_count: Optional[int] = None  # Patient count from database usage check

class TemporalConstraint(BaseModel):
    """Temporal constraint following new semantic agent output format.

    Types:
    - within: Symmetric time window (e.g., "within 30 days")
    - after: Directional "followed by" with no specific days
    - days_after: Directional with specific day count (e.g., "more than 30 days after")
    - before: Directional before
    - in_year: Year filter (e.g., "in year 2145")
    """

    type: Literal["within", "after", "days_after", "before", "in_year"]
    value: Optional[int] = None  # Number of days or year value
    unit: Optional[Literal["days", "year"]] = None
    direction: Optional[Literal["symmetric", "first_to_second", "second_to_first"]] = None

    class Config:
        extra = "allow"  # Accept novel fields from LLM


class AdditionalFilters(BaseModel):
    """Additional filters for query context (demographics, grouping, etc.)"""

    # Demographics filters
    age: Optional[int] = None  # Exact age constraint (e.g., "at age 18")
    gender: Optional[str] = None
    race: Optional[str] = None
    ethnicity: Optional[str] = None
    state: Optional[str] = None
    year: Optional[int] = None

    # Grouping
    group_by: Optional[List[str]] = None  # List of fields to group by

    # Follow-up query support (legacy)
    is_followup: Optional[bool] = False
    age_min: Optional[int] = None
    age_max: Optional[int] = None

    class Config:
        extra = "allow"  # Accept novel fields from LLM


class SemanticContext(BaseModel):
    user_query: str
    query_intent: str  # Brief description of query purpose
    query_category: str  # CRITICAL: Category name (e.g., "DRUG_AND", "CONDITION_FOLLOWED_BY", etc.)

    entities: Optional[List[ConceptMapping]] = []  # Empty for demographics queries
    temporal_constraint: Optional[TemporalConstraint] = None
    additional_filters: Optional[AdditionalFilters] = None

    # Legacy field for backwards compatibility
    query_type: Optional[Literal["single", "intersection", "multi_intersection", "union", "demographics"]] = None

class QueryResult(BaseModel):
    sql: str
    result_count: Optional[int] = None
    execution_time: Optional[str] = None
    schema_prefix: str
    rows: Optional[List[Dict]] = None
    message: Optional[str] = None  # For error messages or explanations

class ErrorResponse(BaseModel):
    error_type: str
    message: str
    suggested_fix: Optional[str] = None


