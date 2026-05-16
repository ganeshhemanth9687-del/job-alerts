import os
import base64
from googleapiclient.discovery import build
from google.oauth2 import service_account
import google.generativeai as genai

# 1. Setup Connections
# Use GitHub Secrets to load these
GEMINI_KEY = os.environ['GEMINI_API_KEY']
genai.configure(api_key=GEMINI_KEY)

# 2. Logic to fetch Unread Emails with label 'JobAlerts'
def get_unread_emails(service):
    # Search for unread messages in your specific label
    results = service.users().messages().list(userId='me', q='label:JobAlerts is:unread').execute()
    return results.get('messages', [])

# 3. Logic to Parse with Gemini
def parse_job_data(email_body):
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"Extract Job Title, Company, Location, Experience, and Link from this email. Return as a single comma-separated line. Content: {email_body}"
    response = model.generate_content(prompt)
    return response.text.strip().split(',')

# 4. Logic to Append to Google Sheets
# Use the Sheets API to append the list to the next empty row
