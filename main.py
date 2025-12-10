import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import os
import json
import re
import time
from urllib.parse import urljoin

# --- הגדרות חיפוש ---
KEYWORDS_INCLUDE = [
    "Success", "Support", "Care", "Fraud", "Risk", "Operation", 
    "Community", "Game", "Junior", "Entry", "Specialist", "QA",
    "Quality", "Trust", "Product"
]

KEYWORDS_EXCLUDE = [
    "Senior", "Head", "Director", "Lead", "VP", "Manager", 
    "Engineer", "Developer", "DevOps", "Backend", "Frontend",
    "Full Stack", "Fullstack", "Principal", "Staff", "Architect"
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
        print("Error: Missing Telegram credentials")
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return True
        else:
            print(f"Telegram Error: {response.text}")
            return False
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
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
                jobs.append({
                    "title": job.get("title", ""),
                    "url": job.get("absolute_url", ""),
                    "location": job.get("location", {}).get("name", "")
                })
            return jobs
    except Exception as e:
        print(f"Error fetching Greenhouse jobs for {identifier}: {e}")
    return []

def fetch_comeet_jobs(identifier):
    url = f"https://www.comeet.com/jobs/{identifier}/all"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            jobs = []
            job_elements = soup.find_all("a", class_=re.compile("job|position|career", re.I))
            if not job_elements:
                job_elements = soup.find_all("div", class_=re.compile("job|position|career", re.I))
            for elem in job_elements:
                title = elem.get_text(strip=True)
                href = elem.get("href", "")
                if href and not href.startswith("http"):
                    href = f"https://www.comeet.com{href}"
                if title:
                    jobs.append({
                        "title": title,
                        "url": href,
                        "location": ""
                    })
            return jobs
    except Exception as e:
        print(f"Error fetching Comeet jobs for {identifier}: {e}")
    return []

def fetch_careers_page_jobs(url, company_name):
    try:
