from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


Severity = Literal["critical", "major", "minor"]
Grade = Literal["PASS", "BORDERLINE", "FAIL"]
Modality = Literal["voice", "text"]


class EvidenceSpan(BaseModel):
    prompt_id: Optional[str] = None
    response_id: Optional[str] = None
    quote: Optional[str] = None
    start_char: Optional[int] = None
    end_char: Optional[int] = None

    supports: Optional[Literal["credit", "penalty", "safety_flag", "uncertainty"]] = None
    span_confidence: Optional[float] = None
    span_type: Optional[Literal["verbatim", "paraphrase"]] = None

    @model_validator(mode="after")
    def _must_link_somewhere(self) -> "EvidenceSpan":
        if not self.prompt_id and not self.response_id:
            raise ValueError("evidence_spans[] must include prompt_id or response_id")
        # Require some verifiable content: either quote or valid offsets.
        if (self.quote is None or str(self.quote).strip() == "") and (self.start_char is None or self.end_char is None):
            raise ValueError("evidence_spans[] must include quote or (start_char,end_char)")
        if self.start_char is not None or self.end_char is not None:
            if self.start_char is None or self.end_char is None:
                raise ValueError("evidence_spans[] offsets must include both start_char and end_char")
            if self.start_char < 0 or self.end_char < 0:
                raise ValueError("evidence_spans[] offsets must be non-negative")
            if self.end_char <= self.start_char:
                raise ValueError("evidence_spans[] end_char must be > start_char")
            if (self.end_char - self.start_char) > 400:
                raise ValueError("evidence_spans[] span too long (max 400 chars)")
        return self


class MarksheetMeta(BaseModel):
    attempt_id: str
    station_run_id: str
    case_id: str
    rubric_set_id: str
    generated_by: str
    generated_at: datetime


class MarksheetHeader(BaseModel):
    candidate_name: Optional[str] = None
    candidate_id: Optional[str] = None
    exam_name: Optional[str] = None
    station_name: str
    date: date
    modality: Modality


class OverallResult(BaseModel):
    total_score: float
    total_max: float
    percentage: float
    grade: Grade
    pass_rule: str
    examiner_summary: str


class DomainScore(BaseModel):
    rubric_domain_key: str
    score_value: float
    max_value: float
    weight_applied: float = 1.0
    rationale: str
    evidence_spans: List[EvidenceSpan] = Field(default_factory=list)


class GlobalRatingMark(BaseModel):
    global_key: str
    score_value: float
    max_value: float
    rationale: Optional[str] = None
    evidence_spans: List[EvidenceSpan] = Field(default_factory=list)


class ChecklistMark(BaseModel):
    checklist_key: str
    mark_value: float
    evidence_spans: List[EvidenceSpan] = Field(default_factory=list)


class CriticalFlag(BaseModel):
    flag_key: str
    severity: Severity
    description: str
    detection_confidence: Optional[float] = None
    evidence_spans: List[EvidenceSpan] = Field(default_factory=list)


class Marksheet(BaseModel):
    meta: MarksheetMeta
    marksheet_header: MarksheetHeader
    overall_result: OverallResult
    domain_scores: List[DomainScore]
    global_ratings: List[GlobalRatingMark] = Field(default_factory=list)
    checklist_marks: List[ChecklistMark] = Field(default_factory=list)
    critical_flags: List[CriticalFlag] = Field(default_factory=list)

    extra: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _basic_sanity(self) -> "Marksheet":
        if not self.domain_scores:
            raise ValueError("domain_scores must not be empty")
        return self

