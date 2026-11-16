"""Data models.

`Lead` is produced by sources. Everything below the "LLM structured output"
marker is passed to `with_structured_output` in strict JSON-schema mode, so
those models must not use defaults, dicts, or numeric constraints: the OpenAI
strict schema requires every field to be present. Ranges are enforced in code.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class Lead(BaseModel):
    name: str
    website: str
    source: str
    source_url: str | None = None
    description: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


# --- LLM structured output ---------------------------------------------------


class BusinessAssessment(BaseModel):
    business_type: str = Field(
        description="Short label, e.g. 'developer API', 'B2B SaaS', 'open-source library', "
        "'consumer mobile app', 'agency', 'marketplace'."
    )
    likely_has_documentation: bool = Field(
        description="True if the site shows evidence of, or the product clearly needs, technical or user docs."
    )
    worth_pursuing: bool = Field(
        description="True if this is a product whose owners would plausibly care about documentation "
        "quality (APIs, SDKs, dev tools, technical SaaS, platforms). False for consumer apps, "
        "content sites, agencies, dead or parked sites."
    )
    confidence: float = Field(description="0.0 to 1.0")
    reasoning: str = Field(description="One or two sentences.")


class ContactInfo(BaseModel):
    emails: list[str]
    phone_numbers: list[str]


class Person(BaseModel):
    name: str = Field(description="Full name exactly as written on the page.")
    role: str = Field(description="Job title as written on the page, e.g. 'CTO', 'VP of Product'.")
    source_url: str = Field(description="URL of the page that names this person (one of the given pages).")


class IntentSignal(BaseModel):
    title: str = Field(description="Entry headline as written on the changelog page.")
    date: str = Field(description="Publication date as YYYY-MM-DD, or empty string if the page shows none.")
    url: str = Field(description="Link to the entry, copied from the given link list; empty string if none.")
    summary: str = Field(description="One sentence: what changed.")
    why_it_matters: str = Field(description="One sentence: why this creates documentation work or risk.")


class CompanyResearch(BaseModel):
    people: list[Person] = Field(description="Named team members shown with a role. Never invent anyone.")
    signals: list[IntentSignal] = Field(
        description="Up to 3 recent changelog entries most relevant to documentation, newest first."
    )


class ScoredDimension(BaseModel):
    score: int = Field(description="0 (terrible) to 10 (excellent)")
    justification: str = Field(description="One or two sentences citing what was observed.")


class DocAnalysis(BaseModel):
    doc_type: str = Field(description="e.g. 'API reference', 'SDK guide', 'user manual', 'mixed'")
    quality: ScoredDimension = Field(description="Accuracy, clarity, writing, code example quality.")
    completeness: ScoredDimension = Field(
        description="Coverage: quickstart, auth, reference, errors, examples, changelog, etc."
    )
    usability: ScoredDimension = Field(description="Navigation, search, structure, discoverability.")
    overall_score: int = Field(description="0 to 10")
    strengths: list[str]
    weaknesses: list[str]
    missing_sections: list[str] = Field(description="Sections a reader would expect but were not found.")


class Improvement(BaseModel):
    area: str
    issue: str
    recommendation: str
    priority: Literal["high", "medium", "low"]


class OutreachOpener(BaseModel):
    subject: str
    body: str = Field(description="3 to 5 sentences, plain text, no placeholders like [Name].")


class LeadReport(BaseModel):
    # lead_score / lead_score_reason are added in code (graph.score_lead), not by the LLM.
    executive_summary: str
    improvements: list[Improvement] = Field(description="Ordered most important first.")
    outreach: OutreachOpener
