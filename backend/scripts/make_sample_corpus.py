"""Generate a small mixed-format sample corpus (DOCX, PDF, MD) for a fictional company.

Run from the backend folder:  python -m scripts.make_sample_corpus
Replace or extend these with your own domain documents if you prefer.
"""
import json

from docx import Document
from fpdf import FPDF

from app import config

HEADER = "Northwind Corp - Internal Use Only"

DOCS = {
    "hr_leave_policy.docx": {
        "meta": {"author": "HR Team", "date": "2026-01-15", "access_tags": ["all_employees"]},
        "title": "Leave Policy",
        "sections": [
            ("Annual leave", "Full-time employees receive 18 days of paid annual leave per calendar year. "
             "Leave accrues monthly at 1.5 days per month. New hires start accruing leave from their first day."),
            ("Carry forward", "A maximum of 5 unused leave days can be carried forward to the next year. "
             "Any balance above 5 days lapses on 31 December."),
            ("Contractors", "Contractors are not eligible for paid annual leave. Contractors may take up to "
             "6 days of unpaid leave per year with approval from their engagement manager."),
            ("How to apply", "Leave must be requested in Workday at least 7 days in advance. "
             "Sick leave of up to 2 days does not require a medical certificate."),
            ("Parental leave", "Primary caregivers receive 26 weeks of paid parental leave; "
             "secondary caregivers receive 4 weeks."),
        ],
    },
    "remote_work_policy.docx": {
        "meta": {"author": "HR Team", "date": "2026-02-01", "access_tags": ["all_employees"]},
        "title": "Remote Work Policy",
        "sections": [
            ("Eligibility", "Employees may work remotely up to 3 days per week after completing their probation period of 90 days."),
            ("Core hours", "All employees must be available during core hours of 11:00 to 16:00 local time, regardless of location."),
            ("Stipend", "Remote workers receive an internet stipend of $50 per month, paid with the monthly salary."),
            ("Equipment", "Employees may claim a one-time home office allowance of $300 for a chair, desk or monitor."),
        ],
    },
    "travel_policy.docx": {
        "meta": {"author": "Finance Team", "date": "2026-03-10", "access_tags": ["all_employees"]},
        "title": "Business Travel Policy",
        "sections": [
            ("Flights", "Economy class is required for flights under 6 hours. Business class is allowed for flights "
             "longer than 6 hours with VP approval."),
            ("Booking", "All travel must be booked through Concur at least 14 days before departure."),
            ("Hotels", "Hotel stays are capped at $200 per night in tier-1 cities and $150 per night elsewhere."),
        ],
    },
    "salary_bands_2026.docx": {
        "meta": {"author": "HR Compensation", "date": "2026-04-01", "access_tags": ["hr_only"]},
        "title": "Salary Bands 2026 (Confidential)",
        "sections": [
            ("Engineering", "Engineer I: $75,000 - $95,000. Engineer II: $95,000 - $120,000. "
             "Senior Engineer: $120,000 - $155,000."),
            ("Review cycle", "Salary reviews happen once a year in April. Merit increases range from 0% to 8%."),
        ],
    },
    "expense_policy.pdf": {
        "meta": {"author": "Finance Team", "date": "2026-01-20", "access_tags": ["all_employees"]},
        "title": "Expense Reimbursement Policy",
        "sections": [
            ("Meals", "Meal expenses are capped at $40 per day for domestic travel and $75 per day for international travel."),
            ("Receipts", "Receipts are required for every expense above $25."),
            ("Deadlines", "Expense claims must be submitted in Concur within 30 days of the expense date. "
             "Late claims require director approval."),
            ("Approvals", "Claims under $500 are approved by the line manager. Claims of $500 or more need director approval."),
        ],
    },
    "incident_postmortem_q3.pdf": {
        "meta": {"author": "SRE Team", "date": "2026-08-20", "access_tags": ["engineering"]},
        "title": "Postmortem: Payment Gateway Outage (14 Aug 2026)",
        "sections": [
            ("Summary", "On 14 August 2026 the payment gateway was unavailable for 47 minutes."),
            ("Root cause", "The root cause was an expired TLS certificate on the payment gateway load balancer. "
             "Automatic renewal had been disabled during a migration and was never re-enabled."),
            ("Actions", "Certificate auto-renewal was re-enabled, and an alert now fires 21 days before any certificate expires."),
        ],
    },
}

MARKDOWN = {
    "it_security_runbook.md": ({"author": "IT Security", "date": "2026-02-15", "access_tags": ["all_employees"]}, """# IT Security Runbook

## Passwords
Passwords must be at least 14 characters long and are rotated every 180 days.
Multi-factor authentication (MFA) is mandatory for email, VPN and all SaaS tools.

## Phishing
If you receive a suspicious email, do not click any links. Report it using the "Report Phish" button
or forward it to security@northwind.example within 1 hour.

## Lost or stolen laptop
Call the IT helpdesk immediately on extension 4357. IT will remotely lock and wipe the device.
"""),
    "vpn_setup_guide.md": ({"author": "IT Support", "date": "2026-03-01", "access_tags": ["all_employees"]}, """# VPN Setup Guide

## Installing
Northwind uses the GlobalProtect VPN client. Install it from the Company Portal app.
Connect to the portal address vpn.northwind.example and sign in with your SSO credentials.

## Troubleshooting
- Error 403 means your device certificate has expired. Re-enrol the device from the Company Portal.
- If the VPN disconnects every few minutes, switch from Wi-Fi 2.4 GHz to 5 GHz or use a wired connection.
- Still stuck? Raise a ticket in ServiceNow under the "Network" category.
"""),
    "onboarding_faq.md": ({"author": "People Ops", "date": "2026-01-05", "access_tags": ["all_employees"]}, """# New Joiner FAQ

**Where do I collect my laptop?** Laptops are collected on your first day from the IT desk on floor 3, desk 3B.

**Will I have a buddy?** Yes, every new joiner is assigned an onboarding buddy for the first 30 days.

**What training is mandatory?** Security Awareness and Code of Conduct training must be completed within 14 days of joining.

**When is my probation review?** Probation lasts 90 days and ends with a review with your manager.
"""),
}


def write_docx(path, title, sections):
    doc = Document()
    doc.sections[0].header.paragraphs[0].text = HEADER
    doc.add_heading(title, 0)
    for heading, body in sections:
        doc.add_heading(heading, level=1)
        doc.add_paragraph(body)
    doc.save(str(path))


def write_pdf(path, title, sections):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    def header():
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(0, 8, HEADER, new_x="LMARGIN", new_y="NEXT")

    pdf.header = header
    pdf.footer = lambda: (pdf.set_y(-15), pdf.set_font("Helvetica", "I", 8),
                          pdf.cell(0, 10, f"Page {pdf.page_no()} of {{nb}}", align="C"))
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
    for heading, body in sections:
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 8, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6, body, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    pdf.output(str(path))


if __name__ == "__main__":
    config.CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    metadata = {}
    for name, d in DOCS.items():
        path = config.CORPUS_DIR / name
        (write_docx if name.endswith(".docx") else write_pdf)(path, d["title"], d["sections"])
        metadata[name] = d["meta"]
    for name, (meta, text) in MARKDOWN.items():
        (config.CORPUS_DIR / name).write_text(text, encoding="utf-8")
        metadata[name] = meta
    config.METADATA_FILE.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Wrote {len(metadata)} documents + metadata.json to {config.CORPUS_DIR}")
