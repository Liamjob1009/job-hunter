import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import os
import json
import re
import time
from urllib.parse import urljoin

# --- הגדרות אישיות (עודכן לפי קורות החיים שלך) ---

MY_RESUME = """
Name: Liam Edelman
Location: Tel Aviv, Israel
Looking for: Junior Customer Success / Customer Support / Operations positions in High-Tech.
Experience:
- Project & Site Manager at Edelman Renovations: Managed end-to-end projects, client facing, problem solving under pressure.
- Service experience (Giraffe): Fast-paced environment, high service orientation.
- IDF (Meitav): Recruiter, data-driven decision making, working under pressure.
Skills: SQL, Microsoft Excel, CRM Familiarity, Analytical capabilities, English (Proficient), Hebrew (Native).
"""

# מילות מפתח לסינון ראשוני
KEYWORDS_INCLUDE = [
    "Success", "Support", "Care", "Fraud", "Risk", "Operation", 
    "Community", "Game", "Junior", "Entry", "Specialist", "QA",
    "Quality", "Trust", "Product", "Tier", "Analyst"
]

KEYWORDS_EXCLUDE = [
    "Senior", "Head", "Director", "Lead", "VP", "Manager", 
    "Engineer", "Developer", "DevOps", "Backend", "Frontend",
    "Full Stack", "Fullstack", "Principal", "Staff", "Architect",
    "Accounting", "Finance", "Legal", "Sales"
]

HISTORY_FILE = "history.json"

# --- פונקציות עזר ---

def load_companies():
    try:
        with open("companies.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("Error: companies.json file not found!")
        return []

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
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

# --- פונקציות חיפוש משרות ---

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
    except Exception as e:
        print(f"Error fetching Greenhouse: {e}")
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
    except Exception as e:
        print(f"Error fetching Comeet: {e}")
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
    except Exception as e:
        print(f"Error fetching careers page: {e}")
    return []

def fetch_jobs(company):
    ctype = company.get("type", "")
    if ctype == "greenhouse": return fetch_greenhouse_jobs(company.get("identifier", ""))
    elif ctype == "comeet": return fetch_comeet_jobs(company.get("identifier", ""))
    elif ctype == "careers_page": return fetch_careers_page_jobs(company.get("url", ""), company.get("name", ""))
    return []

def matches_filter(title, location):
    title_lower = title.lower()
    if any(kw.lower() in title_lower for kw in KEYWORDS_EXCLUDE): return False
    if not any(kw.lower() in title_lower for kw in KEYWORDS_INCLUDE): return False
    
    # סינון מיקום (ישראל/תל אביב)
    if location and len(location) > 2:
        loc_lower = location.lower()
        if "israel" not in loc_lower and "tel aviv" not in loc_lower and "remote" not in loc_lower:
            return False
            
    return True

def rate_job_with_ai(title, company_name, location, url, model):
    # הוראות ל-AI בהתאם לקורות החיים שלך
    prompt = f"""
    Act as a Career Consultant for Liam Edelman.
    Candidate Profile: "{MY_RESUME}"

    Evaluate this Job:
    - Title: {title}
    - Company: {company_name}
    - Location Info: {location}
    - Link: {url}

    CRITICAL RULES:
    1. LOCATION: If job is clearly NOT in Israel, Score = 0.
    2. EXPERIENCE: If it requires "Senior", "Manager", or 3+ years experience, Score = 0.
    3. FIT: Look for Junior/Entry CS, Support, Operations roles. Use the SQL/Excel skills as a bonus.
    4. RELEVANCE: Rate 0-100.

    Return JSON ONLY: {{"score": int, "reason": "short explanation"}}
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        result = json.loads(text)
        return result.get("score", 0), result.get("reason", "")
    except:
        return 0, "Error in AI rating"

# --- Main Execution ---

def main():
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    telegram_token = os.environ.get("TELEGRAM_TOKEN")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not gemini_api_key or not telegram_token:
        print("Error: Missing secrets in GitHub Settings.")
        return

    print("🚀 Starting Smart Job Hunt (Liam's Profile)...")
    
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    companies = load_companies()
    history = load_history()
    
    for company in companies:
        company_name = company.get("name", "Unknown")
        print(f"Scanning {company_name}...")
        jobs = fetch_jobs(company)
        
        for job in jobs:
            title = job.get("title", "")
            url = job.get("url", "")
            location = job.get("location", "")
            job_id = f"{company_name}:{title}"
            
            if job_id in history: continue
            
            if not matches_filter(title, location):
                continue

            print(f"  AI Checking: {title} ({location})")
            
            score, reason = rate_job_with_ai(title, company_name, location, url, model)
            
            history.append(job_id)
            
            if score >= 70:
                print(f"  ✅ MATCH! Score: {score}")
                msg = f"🎯 <b>Mishra For Liam!</b> ({score}/100)\n\n<b>{company_name}</b>\n{title}\n\n📍 {location}\n💡 {reason}\n\n<a href='{url}'>Apply Here</a>"
                send_telegram_message(telegram_token, telegram_chat_id, msg)
            else:
                print(f"  ❌ Low Score: {score} ({reason})")
            
            time.sleep(1)

    save_history(history)
    print("Scan complete!")

if __name__ == "__main__":
    main()
