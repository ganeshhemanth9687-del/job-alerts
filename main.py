import os
import json
import base64
from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import google.generativeai as genai

# Load Configuration from Environment / GitHub Secrets
CLIENT_ID = os.environ['GMAIL_CLIENT_ID']
CLIENT_SECRET = os.environ['GMAIL_CLIENT_SECRET']
REFRESH_TOKEN = os.environ['GMAIL_REFRESH_TOKEN']
SPREADSHEET_ID = os.environ['SPREADSHEET_ID']
GEMINI_KEY = os.environ['GEMINI_API_KEY']

# Authorize Google APIs via OAuth2 Refresh Token
creds = Credentials(
    None,
    refresh_token=REFRESH_TOKEN,
    token_uri="https://oauth2.googleapis.com/token",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET
)

gmail_service = build('gmail', 'v1', credentials=creds)
sheets_service = build('sheets', 'v4', credentials=creds)
genai.configure(api_key=GEMINI_KEY)

def get_unread_emails():
    # Looks for unread emails. Customize the search query if you set up labels
    query = 'is:unread from:naukri.com'
    results = gmail_service.users().messages().list(userId='me', q=query).execute()
    return results.get('messages', [])

def get_email_body(msg_id):
    msg = gmail_service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    payload = msg.get('payload', {})
    
    # Extract plain text or snippet safely
    snippet = msg.get('snippet', '')
    body = ""
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain' and part.get('body', {}).get('data'):
                body += base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
    elif payload.get('body', {}).get('data'):
        body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
        
    return body if body else snippet

def parse_with_gemini(email_content):
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = (
        "Analyze this job alert email snippet. Extract the following information: "
        "Job Title, Company, Location, Experience Required, and Application Link. "
        "Format the output strictly as a valid JSON list of lists where each inner list represents a job row: "
        '[["Job Title", "Company", "Location", "Experience", "Link"]]. If multiple jobs are in one mail, '
        "include all rows. Do not use markdown code blocks (like ```json), just return raw plain text JSON."
    )
    
    response = model.generate_content([prompt, email_content])
    try:
        # This keeps the string replacements safely on single lines
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned_text)
    except Exception as e:
        print(f"Failed parsing JSON from Gemini: {e}")
        return []

def log_to_sheet(rows):
    current_date = datetime.now().strftime("%Y-%m-%d")
    final_rows = []
    for row in rows:
        # Prepend execution date to column A
        final_rows.append([current_date] + row)
        
    body = {'values': final_rows}
    sheets_service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range="Sheet1!A:F",
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()

def mark_as_read(msg_id):
    gmail_service.users().messages().batchModify(
        userId='me',
        body={'ids': [msg_id], 'removeLabelIds': ['UNREAD']}
    ).execute()

def main():
    messages = get_unread_emails()
    if not messages:
        print("No new job alert emails found.")
        return

    print(f"Processing {len(messages)} new email(s)...")
    for msg in messages:
        content = get_email_body(msg['id'])
        extracted_jobs = parse_with_gemini(content)
        
        if extracted_jobs and isinstance(extracted_jobs, list):
            log_to_sheet(extracted_jobs)
            print(f"Logged {len(extracted_jobs)} rows to Google Sheet.")
            
        mark_as_read(msg['id'])

if __name__ == "__main__":
    main()
