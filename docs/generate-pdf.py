#!/usr/bin/env python3
"""Generate AgentEHR System Overview PDF with inline diagrams.

Uses WeasyPrint to render styled HTML to PDF. Run from the repo root:
    python3 docs/generate-pdf.py
"""

import os
from pathlib import Path

from weasyprint import HTML

DOCS_DIR = Path(__file__).parent
DIAGRAMS_DIR = DOCS_DIR / "diagrams"
OUTPUT_PDF = DOCS_DIR / "AgentEHR-System-Overview.pdf"


def img_uri(filename: str) -> str:
    return (DIAGRAMS_DIR / filename).as_uri()


SECTIONS = [
    {
        "title": "The Problem",
        "image": "01-what-is-agentehr.png",
        "caption": "Figure 1 — AgentEHR: Your AI Clinical Assistant",
        "body": [
            "Electronic Health Records were supposed to make medicine better. Instead, they made it slower. Clinicians spend more time clicking through nested menus, copying lab values between screens, and wrestling with order entry forms than they spend talking to patients. The average physician logs over two hours of after-hours EHR work every day. The tools meant to help them have become the obstacle.",
            "AgentEHR starts from a different premise: what if clinicians could simply say what they need, and an AI assistant handled the rest?",
            'The concept is straightforward. A clinician speaks or types a natural-language instruction \u2014 <em>\u201cOrder metformin 500mg twice daily for John Smith\u201d</em> \u2014 and AgentEHR interprets the intent, validates the safety, drafts the order, and presents it for approval. The AI handles the EHR. The clinician stays focused on the patient.',
        ],
    },
    {
        "title": "A Day in the Clinic",
        "image": "02-clinician-workflow-journey.png",
        "caption": "Figure 2 — The AgentEHR Clinician Workflow",
        "body": [
            'Dr. Patel has a full afternoon schedule. Her next patient is John Smith, a 56-year-old man here for a diabetes follow-up. She opens AgentEHR, types \u201cJohn Smith\u201d into the search bar, and selects him from the results. In under four seconds, the system assembles everything she needs: conditions, medications, allergies, recent labs, vitals, immunizations, procedures, and clinical notes. An AI-generated narrative summarizes the patient\u2019s story in plain clinical language. Care gaps \u2014 a missed diabetic eye exam, an overdue flu vaccine \u2014 are flagged automatically before she even asks.',
            "This five-step workflow — search, review, chat, safety check, approve — is the backbone of every AgentEHR session. The clinician never leaves the interface. Every action flows through the same predictable loop, ending with an explicit human decision.",
        ],
    },
    {
        "title": "One Screen, Three Panels",
        "image": "03-ui-layout-overview.png",
        "caption": "Figure 3 — AgentEHR UI Layout Overview",
        "body": [
            "The interface is designed around a three-panel layout that puts the full clinical picture in a single view.",
            "On the left, a dark sidebar lists patient threads — ongoing conversations organized by patient, with unread counts and timestamps. Dr. Patel can switch between patients without losing context. The center panel is the clinical workspace: patient demographics at the top, the AI-generated narrative below, then status pills summarizing allergies, medications, active conditions, and care gaps at a glance. Beneath that, collapsible sections hold the full clinical record — labs with trends, vitals, immunizations, procedures, encounter history, and notes. At the bottom, a chat interface lets Dr. Patel converse with the AI in natural language.",
            "On the right panel, suggested actions appear with priority borders, pending approvals wait with approve and reject buttons, and care gap cards highlight what's missing. Everything a clinician needs, without switching tabs or screens.",
        ],
    },
    {
        "title": "Conversational Care — With Safety Rails",
        "image": "04-safety-approval-workflow.png",
        "caption": "Figure 4 — Medication Safety and Approval Workflow",
        "body": [
            'Dr. Patel reviews John Smith\u2019s A1C: 7.2%, up from 6.8% six months ago. She types: <em>\u201cOrder metformin 500mg twice daily.\u201d</em>',
            "The AI interprets her intent and begins working. It identifies the patient, pulls his current medication list, and runs the new order through two layers of validation. First, a drug-drug interaction check scans his active medications against 15+ built-in interaction rules — warfarin and NSAIDs, ACE inhibitors and potassium, metformin and contrast agents. Second, an allergy cross-reactivity check compares the new drug against his documented allergies, catching cross-reactions like penicillin-cephalosporin sensitivity.",
            "If either check raises a flag, warnings are attached to the order. But critically, the order is never auto-executed. It is created as a FHIR draft and placed in the approval queue. Dr. Patel sees it in the right panel with any warnings displayed. She reviews, then clicks Approve to activate the order — or Reject to delete it. <strong>No clinical action in AgentEHR executes without explicit clinician approval.</strong> This is a foundational design principle, not a feature toggle.",
        ],
    },
    {
        "title": "Under the Hood",
        "image": "05-system-architecture-layers.png",
        "caption": "Figure 5 — AgentEHR System Architecture (4-Layer Stack)",
        "body": [
            "Behind the conversational interface is a four-layer architecture.",
            "The <strong>frontend</strong> is a Next.js 15 application with React 19 and Tailwind CSS, serving the three-panel interface on port 3010. It proxies all API calls through Next.js rewrites to the backend. The <strong>API server</strong> is a FastAPI application on port 8000 that manages conversations, serves patient summaries, generates AI narratives via Gemini 3 Flash, and handles the approval queue endpoints.",
            "The <strong>AI orchestrator</strong> is the intelligent core — an OpenRouter client that runs an agentic loop: it sends the clinician's message to a large language model, receives tool call requests, executes them against 35+ FHIR tools, and loops until the model produces a final response. It is model-agnostic by design, supporting GLM-5, Claude, GPT-4o, and Gemini through a single interface. The <strong>FHIR data layer</strong> provides the clinical data foundation — a Medplum FHIR R4 server backed by PostgreSQL and Redis, running in Docker containers.",
        ],
    },
    {
        "title": "Data in Motion",
        "image": "06-data-flow-sequence.png",
        "caption": "Figure 6 — AgentEHR Data Flow Sequence Diagram",
        "body": [
            "When Dr. Patel selects John Smith, a precise choreography of data fetches begins.",
            "The browser sends a summary request through the Next.js proxy to FastAPI, which fires nine parallel FHIR queries simultaneously — conditions, medications, allergies, labs, vitals, immunizations, procedures, encounters, and clinical notes — using Python's <code>asyncio.gather</code>. The results are assembled into a single PatientSummary response and returned to the browser. In parallel, a separate non-blocking request triggers narrative generation: the patient's clinical data is sent to Gemini 3 Flash, which produces a natural-language summary that streams into the UI as it completes.",
            "When Dr. Patel sends a chat message, the flow is different. Her message is posted to FastAPI, which routes it to the orchestrator. The orchestrator enters its agentic loop: the LLM reasons about the request, emits tool calls (search patient, check medications, create order), the system executes each tool against the FHIR server, feeds the results back, and the LLM generates its final response — complete with any warnings and pending actions.",
        ],
    },
    {
        "title": "The Data Foundation",
        "image": "07-fhir-data-model.png",
        "caption": "Figure 7 — AgentEHR FHIR R4 Data Model",
        "body": [
            "All clinical data in AgentEHR is stored and exchanged using FHIR R4, the international standard for healthcare interoperability.",
            "The Patient resource sits at the center. Radiating outward are three groups: <strong>clinical data</strong> (Condition, Observation for labs and vitals, AllergyIntolerance, Immunization, Procedure), <strong>orders and plans</strong> (MedicationRequest, ServiceRequest, CarePlan, Appointment), and <strong>documentation</strong> (Encounter, DocumentReference, Communication). Every order-type resource passes through the approval queue. The lifecycle is always the same: a resource is created with status <code>draft</code>, queued for clinician review, and only transitions to <code>active</code> upon explicit approval. Rejected drafts are deleted entirely.",
        ],
    },
    {
        "title": "Infrastructure and What Comes Next",
        "image": "08-infrastructure-deployment.png",
        "caption": "Figure 8 — Infrastructure &amp; Deployment Topology",
        "body": [
            "AgentEHR runs across three zones. Host processes — the Next.js frontend, FastAPI server, and FHIR tool handlers — run natively on the developer's machine. The Medplum stack — the FHIR server, PostgreSQL, and Redis — runs in Docker Compose containers with health checks and dependency management. External API calls go to OpenRouter for LLM inference, authenticated via API key over HTTPS.",
            "This topology is designed for local development today and cloud deployment tomorrow. The Docker containers can move to Kubernetes. The host processes can become container images. The external API layer is already cloud-native.",
            "But across every layer, one principle holds: <strong>the clinician stays in control</strong>. AgentEHR is not an autonomous system. It is an assistant — fast, knowledgeable, and tireless — that proposes and the physician disposes. Every order is a draft until a human says otherwise. That is the contract at the heart of the system, and it runs from the UI buttons all the way down to the FHIR resource status codes.",
        ],
    },
]

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Playfair+Display:wght@700&display=swap');

@page {
    size: letter;
    margin: 1in 0.9in 1.1in 0.9in;

    @bottom-left {
        content: "AgentEHR";
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        font-size: 8pt;
        color: #8888a0;
        border-top: 1.5px solid #e4643d;
        padding-top: 8px;
    }
    @bottom-right {
        content: counter(page);
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        font-size: 8pt;
        color: #8888a0;
        border-top: 1.5px solid #e4643d;
        padding-top: 8px;
    }
}

@page :first {
    @bottom-left { content: none; border: none; }
    @bottom-right { content: none; border: none; }
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 10.5pt;
    line-height: 1.65;
    color: #444459;
}

/* ── Cover ── */
.cover {
    text-align: center;
    padding-top: 2.2in;
    page-break-after: always;
}
.cover .logo-text {
    font-family: 'Inter', sans-serif;
    font-size: 48pt;
    font-weight: 700;
    color: #1a1a2e;
    letter-spacing: -1px;
}
.cover .logo-text span {
    color: #e4643d;
}
.cover .subtitle {
    font-size: 16pt;
    font-weight: 400;
    color: #666680;
    margin-top: 12px;
}
.cover .rule {
    width: 120px;
    height: 3px;
    background: linear-gradient(90deg, #e4643d, #3dbde4);
    margin: 28px auto 0 auto;
    border: none;
    border-radius: 2px;
}
.cover .date {
    font-size: 10pt;
    color: #8888a0;
    margin-top: 40px;
}

/* ── Sections ── */
h2 {
    font-family: 'Inter', sans-serif;
    font-size: 18pt;
    font-weight: 600;
    color: #1a1a2e;
    border-left: 4px solid #e4643d;
    padding-left: 14px;
    margin-top: 32px;
    margin-bottom: 14px;
}

p {
    margin-bottom: 10px;
    text-align: justify;
    hyphens: auto;
}

strong {
    color: #1a1a2e;
    font-weight: 600;
}

em {
    color: #666680;
    font-style: italic;
}

code {
    font-family: 'SF Mono', 'Menlo', 'Consolas', monospace;
    font-size: 9pt;
    background: #f0fafc;
    color: #2fa8cc;
    padding: 1px 5px;
    border-radius: 3px;
    border: 1px solid #d8eef5;
}

/* ── Images ── */
.diagram-container {
    text-align: center;
    margin: 20px 0 24px 0;
}
.diagram-container img {
    max-width: 100%;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}
.diagram-container .caption {
    font-size: 8.5pt;
    color: #8888a0;
    font-style: italic;
    margin-top: 8px;
}

/* ── Dividers ── */
hr {
    border: none;
    height: 2px;
    background: linear-gradient(90deg, #e4643d 0%, #3dbde4 100%);
    margin: 28px 0;
    border-radius: 1px;
}
"""


def build_html() -> str:
    from datetime import date

    sections_html = ""
    for i, s in enumerate(SECTIONS):
        paragraphs = "\n".join(f"        <p>{p}</p>" for p in s["body"])

        # Place image before or after first paragraph depending on section
        sections_html += f"""
    <hr>
    <h2>{s["title"]}</h2>
{paragraphs}
    <div class="diagram-container">
        <img src="{img_uri(s["image"])}" alt="{s["caption"]}">
        <div class="caption">{s["caption"]}</div>
    </div>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <style>{CSS}</style>
</head>
<body>

<!-- Cover Page -->
<div class="cover">
    <div class="logo-text">Agent<span>EHR</span></div>
    <div class="subtitle">How It Works — A System Overview</div>
    <div class="rule"></div>
    <div class="date">{date.today().strftime("%B %Y")}</div>
</div>

<!-- Content -->
{sections_html}

</body>
</html>"""


def main():
    print("Building HTML...")
    html_content = build_html()

    print(f"Rendering PDF to {OUTPUT_PDF}...")
    HTML(string=html_content, base_url=str(DOCS_DIR)).write_pdf(str(OUTPUT_PDF))

    size_mb = OUTPUT_PDF.stat().st_size / (1024 * 1024)
    print(f"Done. {OUTPUT_PDF.name} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
