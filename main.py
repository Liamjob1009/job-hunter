import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import os
import json
import re
import time
from urllib.parse import urljoin

# --- הגדרות אישיות משופרות ---
MY_RESUME = """
Name: Liam Edelman
Location: Tel Aviv, Israel
Looking for: 
1. Junior Project Management / Operations / Coordinator roles (Based on my experience as Site Manager).
2. Customer Success / Customer Support roles (Open to all levels, not just Junior).

Experience:
- Project & Site Manager: Managed end-to-end projects, timelines, suppliers, and clients.
- Customer Service (Giraffe): High-pressure environment, service-oriented.
- IDF Recruiter: Data-driven, sorting and matching candidates.

Skills: SQL, Excel, Tech-savvy, English (Proficient), Hebrew (Native).
"""

# --- מילות מפתח מעודכנות ---
# הוספתי לכאן Project, Coordinator, Success
KEYWORDS_INCLUDE = [
    "Success", "Support", "Care", "Operation", "Project", "Coordinator",
    "Community", "Game", "Junior", "Entry", "Specialist", "QA",
    "Trust", "Product", "Tier", "Analyst", "Manager", "Admin"
]

# הורדתי את "Manager" מהחסימה כדי שלא תפספס ניהול פרויקטים
KEYWORDS_EXCLUDE = [
    "Senior", "Head", "Director", "VP", "Chief",
    "Engineer", "Developer", "DevOps", "Backend", "Frontend",
    "Full Stack", "Fullstack", "Principal", "Staff", "Architect",
    "Accounting", "Finance", "Legal", "Sales", "R&D"
]

HISTORY_FILE = "history.json"

# --- פונקציות עזר ---

def load_companies():
    try:
        with open("companies.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def load_history():
    # מחזיר רשימה ריקה כדי לוודא שאתה רואה תוצאות עכשיו (בטל את ההערה בהמשך כדי לזכור)
    return [] 

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def send_telegram_message(token, chat_id, message):
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = { "chat_id": chat_id, "text": message, "parse_mode": "HTML" }
    try:
        requests.post(url, json=payload, timeout=10)
        return True
    except:
        return False

# --- פונקציות חיפוש ---

def fetch_greenhouse_jobs(identifier):
    url = f"https://boards-api.greenhouse.io/v1/boards/{identifier}/jobs"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            jobs = []
            for job in data.get("jobs", []):
                loc_name = job.get("location", {}).get("name", "")
                jobs.append({
                    "title": job.get("title", ""),
                    "url": job.get("absolute_url", ""),
                    "location": loc_name
                })
            return jobs
    except:
        return []
    return []

def fetch_comeet_jobs(identifier):
    url = f"https://www.comeet.com/jobs/{identifier}/all"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            jobs = []
            for elem in soup.find_all("a", class_=re.compile("job|position|career", re.I)):
                title = elem.get_text(strip=True)
                href = elem.get("href", "")
                if href and not href.startswith("http"): href = f"https://www.comeet.com{href}"
                if title:
                    jobs.append({"title": title, "url": href, "location": ""})
            return jobs
    except:
        return []
    return []

def fetch_careers_page_jobs(url, company_name):
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            jobs = []
            for link in soup.find_all("a", href=True):
                text = link.get_text(strip=True)
                if any(kw.lower() in text.lower() for kw in KEYWORDS_INCLUDE):
                    job_url = link["href"]
                    if not job_url.startswith("http"): job_url = urljoin(url, job_url)
                    jobs.append({"title": text, "url": job_url, "location": ""})
            return jobs
    except:
        return []
    return []

def fetch_jobs(company):
    ctype = company.get("type", "")
    if ctype == "greenhouse": return fetch_greenhouse_jobs(company.get("identifier", ""))
    elif ctype == "comeet": return fetch_comeet_jobs(company.get("identifier", ""))
    elif ctype == "careers_page": return fetch_careers_page_jobs(company.get("url", ""), company.get("name", ""))
    return []

def matches_filter(title, location):
    title_lower = title.lower()
    
    # בדיקת מילות חסימה (כמו Senior, Engineer)
    if any(kw.lower() in title_lower for kw in KEYWORDS_EXCLUDE): 
        return False
    
    # בדיקת מילות חיוב
    if not any(kw.lower() in title_lower for kw in KEYWORDS_INCLUDE): 
        return False
    
    # --- סינון ישראל קשוח ---
    if location and len(location) > 2:
        loc_lower = location.lower()
        # חייב להיות ישראל או תל אביב או חיפה וכו'
        is_israel = "israel" in loc_lower or "tel aviv" in loc_lower or "jerusalem" in loc_lower or "herzliya" in loc_lower or "haifa" in loc_lower or "remote" in loc_lower
        
        # אם כתוב רק "Remote" בלי מדינה, ה-AI יחליט. אם כתוב מדינה אחרת - לפסול.
        if not is_israel:
             # אם המיקום הוא מפורשות מדינה אחרת
             if "united states" in loc_lower or "london" in loc_lower or "uk" in loc_lower or "germany" in loc_lower:
                 return False
            
    return True

def rate_job_with_ai(title, company_name, location, url, model):
    prompt = f"""
    Role: Career Consultant for Liam.
    Profile: "{MY_RESUME}"
    Job: {title} at {company_name} ({location})
    Link: {url}

    LOGIC:
    1. **LOCATION**: MUST be Israel. If text says "US", "UK", "Europe" -> Score 0.
    
    2. **ROLE TYPE MATCHING**:
       - IF "Customer Support" or "Customer Success": High Score (75-100). Experience level is flexible (don't reject if not Junior).
       - IF "Project Manager" / "Operations" / "Coordinator": High Score ONLY if "Junior" or "Entry Level" or matches 1-2 years experience.
       - IF "Engineering" / "Developer": Score 0.

    3. **OUTPUT**:
       Return JSON ONLY: {{"score": int, "reason": "concise explanation"}}
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        result = json.loads(text)
        return result.get("score", 0), result.get("reason", "")
    except:
        return 0, "AI Error"

# --- Main Execution ---

def main():
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    telegram_token = os.environ.get("TELEGRAM_TOKEN")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
