import os
import sqlite3
import requests
import asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel
from twilio.rest import Client

TWILIO_SID = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN", "")
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER", "")
TARGET_PHONE = os.getenv("TARGET_PHONE", "")

KEYWORDS = ["asbestos", "r&d survey", "acm removal", "abatement", "demolition survey", "licensed asbestos"]

def init_db():
    conn = sqlite3.connect("asbestos_leads.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            title TEXT,
            category TEXT,
            location TEXT,
            distance_miles REAL,
            description TEXT,
            publish_date TEXT,
            portal_url TEXT,
            contact_phone TEXT,
            contact_email TEXT,
            status TEXT
        )
    """)
    conn.commit()
    conn.close()

async def run_scraper_loop():
    while True:
        try:
            url = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search?q=asbestos"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                conn = sqlite3.connect("asbestos_leads.db")
                c = conn.cursor()
                
                for release in data.get("releases", []):
                    notice_id = release.get("id")
                    tender = release.get("tender", {})
                    title = tender.get("title", "Asbestos Contract")
                    description = tender.get("description", "No detailed description provided.")
                    
                    if any(kw in title.lower() or kw in description.lower() for kw in KEYWORDS):
                        c.execute("SELECT id FROM leads WHERE id = ?", (notice_id,))
                        if not c.fetchone():
                            category = "Survey & R&D" if "survey" in title.lower() else "Removal & Abatement"
                            c.execute("""
                                INSERT INTO leads VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?)
                            """, (
                                notice_id, title, category, "UK Wide", 12.5, description,
                                "https://www.contractsfinder.service.gov.uk", "+447700900077", "tender@example.com", "New"
                            ))
                            conn.commit()
                            
                            if TWILIO_SID and TWILIO_TOKEN:
                                client = Client(TWILIO_SID, TWILIO_TOKEN)
                                msg_body = f"🚨 NEW ASBESTOS WORK\n\nTitle: {title[:100]}\nCategory: {category}"
                                client.messages.create(body=msg_body, from_=TWILIO_NUMBER, to=TARGET_PHONE)
                conn.close()
        except Exception as e:
            print(f"Scraper error: {e}")
            
        await asyncio.sleep(900)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    asyncio.create_task(run_scraper_loop())
    yield

app = FastAPI(title="Asbestos Lead Portal", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class StatusUpdate(BaseModel):
    status: str

@app.get("/api/leads")
def get_leads():
    conn = sqlite3.connect("asbestos_leads.db")
    c = conn.cursor()
    c.execute("SELECT id, title, category, location, distance_miles, description, publish_date, portal_url, contact_phone, contact_email, status FROM leads ORDER BY publish_date DESC")
    rows = c.fetchall()
    conn.close()
    
    return [
        {
            "id": r[0], "title": r[1], "category": r[2], "location": r[3],
            "distanceMiles": r[4], "description": r[5], "publishDate": r[6],
            "portalUrl": r[7], "contactPhone": r[8], "contactEmail": r[9], "status": r[10]
        }
        for r in rows
    ]

@app.post("/api/leads/{lead_id}/status")
def update_status(lead_id: str, payload: StatusUpdate):
    conn = sqlite3.connect("asbestos_leads.db")
    c = conn.cursor()
    c.execute("UPDATE leads SET status = ? WHERE id = ?", (payload.status, lead_id))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Asbestos Lead Portal</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-50 text-gray-900 font-sans antialiased">
        <div class="max-w-md mx-auto min-h-screen bg-white shadow-xl flex flex-col">
            <header class="bg-orange-600 text-white p-4 sticky top-0 z-10 shadow">
                <h1 class="text-xl font-bold">Asbestos Work Feeds</h1>
                <p class="text-xs text-orange-100">Automated Tender & Survey Radar</p>
            </header>
            <main id="lead-list" class="flex-1 p-4 space-y-4 overflow-y-auto">
                <div class="text-center py-10 text-gray-400">Loading live leads...</div>
            </main>
        </div>
        <script>
            async function fetchLeads() {
                try {
                    const res = await fetch('/api/leads');
                    const leads = await res.json();
                    const container = document.getElementById('lead-list');
                    if (leads.length === 0) {
                        container.innerHTML = '<div class="text-center py-10 text-gray-400">No leads found yet. Scraper runs every 15 mins.</div>';
                        return;
                    }
                    container.innerHTML = leads.map(lead => `
                        <div class="border border-gray-200 rounded-xl p-4 shadow-sm bg-white space-y-2">
                            <div class="flex justify-between items-center">
                                <span class="text-xs font-bold uppercase px-2 py-0.5 bg-orange-100 text-orange-700 rounded">${lead.category}</span>
                                <span class="text-xs text-gray-500 font-medium">${lead.status}</span>
                            </div>
                            <h2 class="font-bold text-gray-900 text-base">${lead.title}</h2>
                            <p class="text-sm text-gray-600 line-clamp-2">${lead.description}</p>
                            <div class="flex items-center text-xs text-gray-500 space-x-2 pt-1">
                                <span>📍 ${lead.location}</span>
                                <span>•</span>
                                <span>${lead.distanceMiles} miles away</span>
                            </div>
                            <div class="pt-3 flex space-x-2 border-t border-gray-100">
                                <a href="tel:${lead.contactPhone}" class="flex-1 bg-green-600 hover:bg-green-700 text-white text-center py-2 rounded-lg text-sm font-semibold">Call</a>
                                <a href="mailto:${lead.contactEmail}?subject=Quote for ${encodeURIComponent(lead.title)}" class="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-center py-2 rounded-lg text-sm font-semibold">Email Quote</a>
                                <a href="${lead.portalUrl}" target="_blank" class="bg-gray-100 hover:bg-gray-200 text-gray-800 px-3 py-2 rounded-lg text-sm font-semibold">Portal</a>
                            </div>
                        </div>
                    `).join('');
                } catch (err) { console.error(err); }
            }
            fetchLeads();
            setInterval(fetchLeads, 30000);
        </script>
    </body>
    </html>
    """