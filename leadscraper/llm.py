"""LLM calls. Every call is temperature 0 with strict structured output."""

import json
from typing import Any, TypeVar

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from .schemas import BusinessAssessment, CompanyResearch, ContactInfo, DocAnalysis, LeadReport
from .settings import Settings

T = TypeVar("T", bound=BaseModel)


class ConfigError(RuntimeError):
    pass


ASSESS_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You qualify sales leads for a technical documentation consultancy. Decide whether the "
     "website belongs to a product that has, or clearly needs, documentation (developer docs, "
     "API reference, SDK guides, user manuals, help center), and whether its owners are worth "
     "contacting about documentation quality. Base your answer only on the evidence given."),
    ("human",
     "Product: {name}\nWebsite: {url}\nListing description: {description}\n\n"
     "Page title: {title}\nMeta description: {meta}\n\n"
     "Header/navigation links (text -> url):\n{nav_links}\n\n"
     "Header links that match documentation keywords:\n{doc_links}\n\n"
     "Homepage text (truncated):\n{text}"),
])

PURIFY_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a helpful assistant. Please rewrite the following list of emails and phone numbers, "
     "removing any duplicates or invalid entries. Remove anything that you think is invalid or not "
     "a proper email or phone number. Please provide the output in a structured JSON format with two "
     "keys: 'emails' and 'phone_numbers'.\n\n"
     "Additional rules:\n"
     "- Keep only contacts that plausibly reach the owners or team of {domain}. Drop placeholder "
     "addresses, addresses of unrelated third parties (vendors, example customers, libraries), and "
     "numbers that are clearly not phone numbers (ids, prices, versions, dates).\n"
     "- Never invent a contact that is not in the input. You may reformat a phone number "
     "(e.g. to international format) but must not change its digits other than adding a country code.\n"
     "- Order the output most useful first (named people and sales/contact/hello addresses before "
     "support/noreply-like ones)."),
    ("human", "Website: {url}\n\nCollected contacts with the pages they were found on:\n{contacts}"),
])

RESEARCH_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You research a company for a documentation consultancy, using only the pages given.\n"
     "People: list every person the pages name together with a job title (leadership, founders, "
     "developer relations, product, engineering, documentation). Copy names and titles exactly. Do not "
     "include customers, investors, testimonial authors or blog authors without a stated role at the "
     "company. Never add anyone who is not on the pages.\n"
     "Signals: from the changelog page, pick up to 3 entries from the last 6 months (today is {today}) "
     "that create documentation work: API or SDK changes, breaking changes, deprecations, new "
     "endpoints, new products or integrations. Newest first. Copy each entry's URL from the link "
     "list; use an empty string if it has none. If there is no changelog page, return no signals."),
    ("human",
     "Company: {name}\nWebsite: {url}\n\n"
     "Team / about pages:\n{people_pages}\n\n"
     "Changelog page: {changelog_url}\n{changelog_text}\n\n"
     "Links on the changelog page (text -> url):\n{changelog_links}"),
])

ANALYZE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a senior technical writer auditing a product's documentation. Score quality, "
     "completeness and usability from 0 to 10 using only the sampled pages and metrics. Be "
     "specific and critical: cite concrete observations (page names, missing topics, unclear "
     "steps, absent examples). Do not reward volume; reward clarity and coverage. If the sample "
     "is too small to judge something, say so in the justification instead of guessing."),
    ("human",
     "Product: {name}\nWebsite: {url}\nDocumentation URL: {doc_url}\n"
     "Business type: {business_type}\n\n"
     "Deterministic metrics:\n{metrics}\n\n"
     "Sampled documentation pages:\n{pages}"),
])

REPORT_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You write concise lead reports for a documentation consultancy. Summarise the documentation "
     "audit, list the improvements that would matter most to this product's users, and write "
     "a short cold-email opener to the product team. The opener must "
     "reference one or two specific, verifiable observations about their docs, be friendly and "
     "non-salesy, avoid flattery, and contain no placeholders like [Name] or [Your Company]. "
     "End the body with the last sentence: no sign-off, closing line or signature.\n"
     "If a recipient is given, start the body with the greeting shown and write to that person's role. "
     "If recent signals are given, open with the most relevant one (name the change and when it shipped) "
     "and connect it to what the docs need; do not invent details beyond the signal text."),
    ("human",
     "Product: {name}\nWebsite: {url}\nDocumentation: {doc_url}\nBusiness type: {business_type}\n"
     "Contacts available: {contact_summary}\n"
     "Recipient: {recipient}\n\n"
     "Recent signals (JSON):\n{signals}\n\n"
     "Documentation audit (JSON):\n{analysis}\n\nMetrics (JSON):\n{metrics}"),
])


class LLM:
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise ConfigError("OPENAI_API_KEY is not set (add it to .env)")
        self.chat = ChatOpenAI(
            model=settings.openai_model,
            temperature=0,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=90,
            max_retries=3,
        )

    def _run(self, prompt: ChatPromptTemplate, schema: type[T], **variables: Any) -> T:
        chain = prompt | self.chat.with_structured_output(schema, method="json_schema", strict=True)
        return chain.invoke(variables)

    def assess_business(self, **v: Any) -> BusinessAssessment:
        return self._run(ASSESS_PROMPT, BusinessAssessment, **v)

    def purify_contacts(self, url: str, domain: str, emails: dict, phones: dict) -> ContactInfo:
        contacts = json.dumps({"emails": emails, "phone_numbers": phones}, indent=1)
        return self._run(PURIFY_PROMPT, ContactInfo, url=url, domain=domain, contacts=contacts)

    def research(self, **v: Any) -> CompanyResearch:
        return self._run(RESEARCH_PROMPT, CompanyResearch, **v)

    def analyze_docs(self, **v: Any) -> DocAnalysis:
        return self._run(ANALYZE_PROMPT, DocAnalysis, **v)

    def write_report(self, **v: Any) -> LeadReport:
        return self._run(REPORT_PROMPT, LeadReport, **v)
