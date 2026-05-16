import os
import json
import base64
from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google import genai

# 1. Load System Configuration from GitHub Secrets
CLIENT_ID = os.environ['GMAIL_CLIENT_ID']
CLIENT_SECRET = os.environ['GMAIL_CLIENT_SECRET']
REFRESH_TOKEN = os.environ['GMAIL_REFRESH_TOKEN']
SPREADSHEET_ID = os.environ['SPREADSHEET_ID']
GEMINI_KEY = os.environ['GEMINI_API_KEY']

# 2. Authorize Google Workspace Connections via OAuth2 Refresh Token
creds = Credentials(
    None,
    refresh_token=REFRESH_TOKEN,
    token_uri="https://oauth2.googleapis.com/token",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET
)

gmail_service = build('gmail', 'v1', credentials=creds)
sheets_service = build('sheets', 'v4', credentials=creds)

# Initialize the modern Gemini AI Client
ai_client = genai.Client(api_key=GEMINI_KEY)


def get_unread_emails():
    """Fetches unread emails from the inbox."""
    query = 'is:unread'
    results = gmail_service.users().messages().list(userId='me', q=query).execute()
    return results.get('messages', [])


def get_email_body(msg_id):
    """Safely handles extraction of email contents from multi-part or plain MIME types."""
    msg = gmail_service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    payload = msg.get('payload', {})
    
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
    """Sends unstructured job content to Gemini and extracts programmatic JSON structure."""
    prompt = (
        "Analyze this job alert email snippet. Extract the following information: "
        "Job Title, Company, Location, Experience Required, and Application Link. "
        "Format the output strictly as a valid JSON list of lists where each inner list represents a job row: "
        '[["Job Title", "Company", "Location", "Experience", "Link"]]. If multiple jobs are listed in one email, '
        "include all rows. Do not use markdown code blocks, just return raw plain text JSON string structures."
    )
    
    response = ai_client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[prompt, email_content]
    )
    
    try:
        # Safe string cleaning using safe targets to avoid copy-paste line breaks
        cleaned_text = response.text.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]
        elif cleaned_text.startswith("
```"):
            cleaned_text = cleaned_text[3:]
            
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]
            
        cleaned_text = cleaned_text.strip()
        return json.loads(cleaned_text)
    except Exception as e:
        print(f"Failed parsing structured JSON from Gemini pipeline: {e}")
        return []


def log_to_sheet(rows):
    """Appends job listings seamlessly to your target tracking Google Sheet."""
    current_date = datetime.now().strftime("%Y-%m-%d")
    final_rows = []
    
    for row in rows:
        final_rows.append([current_date] + row)
        
    body = {'values': final_rows}
    sheets_service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range="Sheet1!A:F",
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()


def mark_as_read(msg_id):
    """Cleans up the inbox tracking state by removing the UNREAD flag from parsed messages."""
    gmail_service.users().messages().batchModify(
        userId='me',
        body={'ids': [msg_id], 'removeLabelIds': ['UNREAD']}
    ).execute()


def main():
    messages = get_unread_emails()
    if not messages:
        print("No new unread job alert emails discovered.")
        return

    print(f"Discovered {len(messages)} new message(s). Initiating pipeline transformation...")
    
    for msg in messages:
        content = get_email_body(msg['id'])
        extracted_jobs = parse_with_gemini(content)
        
        if extracted_jobs and isinstance(extracted_jobs, list):
            log_to_sheet(extracted_jobs)
            print(f"Successfully processed and appended {len(extracted_jobs)} job data rows.")
            
        mark_as_read(msg['id'])


if __name__ == "__main__":
    main()
