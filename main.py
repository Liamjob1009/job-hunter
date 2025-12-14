import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import os
import json
import re
import time
from urllib.parse import urljoin

# --- הגדרות ---
HISTORY_FILE = "history.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

MY_RESUME = """
Name: Liam Edelman
Location: Tel Aviv, Israel
Looking for: Junior Project Management, Operations, Customer Success, Support.
"""

KEYWORDS_INCLUDE = [
    "Success", "Support", "Care", "Operation", "Project", "Coordinator",
    "Community", "Game", "Junior", "Entry", "Specialist", "QA",
    "Trust", "Product", "Tier", "Analyst", "Manager", "Admin", "Client", "Help"
]

KEYWORDS_EXCLUDE = [
    "Senior", "Head", "Director", "VP", "Chief", "Engineer", "Developer", 
    "DevOps", "Backend", "Frontend", "Full Stack", "Architect", "Legal", "Sales"
]

# --- פונקציות עזר ---

def send_telegram_message(token, chat_id, message):
    if not token or not chat_id: return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = { "chat_id": chat_id, "text": message, "parse_mode": "HTML" }
    try:
        requests.post(url, json=payload, timeout=10)
        return True
    except:
        return False

def     load_companies():
    try:
        with open("companies.json", "r") as f: return json.load(f)
    except: return []

def load_history():
    return [] # דיבוג - מתעלמים מהיסטוריה

def save_history(history):
    with open(HISTORY_FILE, "w") as f: json.dump(history, f, indent=2)

# --- פונקציות חיפוש ---

def fetch_greenhouse_jobs(identifier):
    url = f"https://boards-api.greenhouse.io/v1/boards/{identifier}/jobs"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            jobs = []
            for job in data.get("jobs", []):
                jobs.append({
                    "title": job.get("title", "No Title"),
                    "url": job.get("absolute_url", ""),
                    "location": job.get("location", {}).get("name", "Unknown")
                })
            return jobs
    except: pass
    return []

def fetch_comeet_jobs(identifier):
    url = f"https://www.comeet.com/jobs/{identifier}/all"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        jobs = []
        for elem in soup.find_all("a", class_=re.compile("job|position|career", re.I)):
            title = elem.get_text(strip=True)
            href = elem.get("href", "")
            if href and not href.startswith("http"): href = f"https://www.comeet.com{href}"
            if title:
                jobs.append({"title": title, "url": href, "location": "Unknown"})
        return jobs
    except: pass
    return []

def fetch_careers_page_jobs(url, company_name):
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        jobs = []
        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True)
            if any(kw.lower() in text.lower() for kw in KEYWORDS_INCLUDE):
                job_url = link["href"]
                if not job_url.startswith("http"): job_url = urljoin(url, job_url)
                jobs.append({"title": text, "url": job_url, "location": "Unknown"})
        return jobs
    except: pass
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
    return True

# --- פונקציה חכמה לבחירת מודל ---
def get_best_available_model():
    try:
        print("Listing available models...")
        models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                models.append(m.name)
        
        print(f"Available models: {models}")
        
        # עדיפות ראשונה: פלאש 1.5 (מהיר וטוב)
        if 'models/gemini-1.5-flash' in models:
            return 'models/gemini-1.5-flash'
        # עדיפות שניה: פרו 1.5
        elif 'models/gemini-1.5-pro' in models:
            return 'models/gemini-1.5-pro'
        # עדיפות שלישית: פרו 1.0 (הישן והטוב)
        elif 'models/gemini-1.0-pro' in models:
            return 'models/gemini-1.0-pro'
        # אם אין ברירה - קח את הראשון שיש
        elif models:
            return models[0]
        else:
            return None
    except Exception as e:
        print(f"Error listing models: {e}")
        return 'gemini-pro' # ברירת מחדל נואשת

def rate_job_with_ai(title, company_name, location, url, model):
    prompt = f"""
    Rate this job for Liam (Junior PM / Support / Ops).
    Job: {title} at {company_name}
    Location: {location}
    
    Give a score from 0 to 100.
    - If it's Support/Success/Project/Ops -> Give 80+.
    - If it's Engineer/Dev -> Give 0.
    
    Return JSON ONLY: {{"score": int, "reason": "short text"}}
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.strip().replace("```json", "").replace("```", "")
        if "{" in text:
            text = text[text.find("{"):text.rfind("}")+1]
        
        result = json.loads(text)
        return result.get("score", 0), result.get("reason", "No reason provided")
    except Exception as e:
        return 0, f"AI Error: {str(e)}"

# --- Main ---

def main():
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    telegram_token = os.environ.get("TELEGRAM_TOKEN")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not gemini_api_key or not telegram_token: return

    # --- חיבור לגוגל ---
    genai.configure(api_key=gemini_api_key)
    
    # --- זיהוי אוטומטי של המודל ---
    model_name = get_best_available_model()
    
    if not model_name:
        send_telegram_message(telegram_token, telegram_chat_id, "❌ Error: No AI models found for your API key.")
        return

    send_telegram_message(telegram_token, telegram_chat_id, f"🧠 <b>AI Connected</b>\nUsing model: {model_name}\nStarting scan...")
    
    model = genai.GenerativeModel(model_name)
    
    companies = load_companies()
    debug_count = 0
    
    for company in companies:
        company_name = company.get("name", "Unknown")
        print(f"Scanning {company_name}...")
        
        try:
            jobs = fetch_jobs(company)
            
            for job in jobs:
                title = job.get("title", "")
                url = job.get("url", "")
                location = job.get("location", "Unknown")
                
                if not matches_filter(title, location): continue
                
                score, reason = rate_job_with_ai(title, company_name, location, url, model)
                
                # מצב דיבוג: שולח את ה-5 הראשונים לא משנה מה
                if debug_count < 5:
                    debug_msg = f"""🐞 <b>DEBUG #{debug_count+1}</b>
🏢 {company_name}
💼 {title}
🤖 Score: {score}
💭 Reason: {reason}
🔗 {url}"""
                    send_telegram_message(telegram_token, telegram_chat_id, debug_msg)
                    debug_count += 1
                    time.sleep(1)
                
                # אם הציון גבוה, שלח רגיל
                elif score >= 50:
                    msg = f"🎯 <b>Match Found!</b> ({score})\n{company_name}\n{title}\n{url}"
                    send_telegram_message(telegram_token, telegram_chat_id, msg)
                
                time.sleep(1)
                
        except Exception as e:
            print(f"Error: {e}")
            continue

    send_telegram_message(telegram_token, telegram_chat_id, "🏁 Debug Scan Complete.")

if __name__ == "__main__":
    main()
