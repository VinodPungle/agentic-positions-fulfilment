"""
Test NEW backend endpoints for Agentic Recruitment Pipeline:
1. POST /api/parse/file
2. PATCH /api/positions/{pid}/jd
3. POST /api/positions/{pid}/candidates/bulk
4. POST /api/import/candidates

Plus smoke tests for old flows.
"""
import io
import os
import csv
import requests
from docx import Document

# Backend URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://agentic-positions.preview.emergentagent.com').rstrip('/')
API = f"{BASE_URL}/api"

print(f"Testing against: {API}")

# ========== Helper Functions ==========

def get_users():
    """Fetch all users and return a dict by role/name."""
    r = requests.get(f"{API}/users", timeout=15)
    assert r.status_code == 200, f"Failed to get users: {r.text}"
    users = r.json()
    result = {}
    for u in users:
        if u['role'] == 'dm':
            result['diana'] = u
        elif u['role'] == 'staffing':
            result['sam'] = u
        elif u['role'] == 'pm':
            if 'Phoenix' in u.get('projects', []):
                result['priya'] = u
            elif 'Atlas' in u.get('projects', []):
                result['pablo'] = u
    return result

def client_for(user_id):
    """Create a requests session with X-User-Id header."""
    s = requests.Session()
    s.headers.update({'X-User-Id': user_id})
    return s

def get_position_by_ticket(client, ticket):
    """Find position by ticket number."""
    r = client.get(f"{API}/positions", timeout=15)
    assert r.status_code == 200, r.text
    for p in r.json():
        if p['ticket_number'] == ticket:
            return p
    return None

def create_txt_file(content):
    """Create in-memory text file."""
    return io.BytesIO(content.encode('utf-8'))

def create_pdf_file(text):
    """Create a minimal PDF with text using pypdf."""
    # Create a minimal PDF structure manually
    # This is a very basic PDF that pypdf can read
    pdf_content = f"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj
2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj
3 0 obj
<<
/Type /Page
/Parent 2 0 R
/Resources <<
/Font <<
/F1 <<
/Type /Font
/Subtype /Type1
/BaseFont /Helvetica
>>
>>
>>
/MediaBox [0 0 612 792]
/Contents 4 0 R
>>
endobj
4 0 obj
<<
/Length 44
>>
stream
BT
/F1 12 Tf
100 700 Td
({text}) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000317 00000 n 
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
410
%%EOF"""
    return io.BytesIO(pdf_content.encode('latin-1'))

def create_docx_file(text):
    """Create a DOCX file with text using python-docx."""
    doc = Document()
    doc.add_paragraph(text)
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# ========== Tests ==========

def test_parse_file_txt():
    """Test POST /api/parse/file with TXT file."""
    print("\n=== Test 1: POST /api/parse/file (TXT) ===")
    
    content = "This is a test text file for parsing."
    file = create_txt_file(content)
    
    r = requests.post(f"{API}/parse/file", 
                     files={'file': ('test.txt', file, 'text/plain')},
                     timeout=15)
    
    assert r.status_code == 200, f"Failed: {r.status_code} {r.text}"
    data = r.json()
    
    assert 'filename' in data, "Missing filename"
    assert 'chars' in data, "Missing chars"
    assert 'text' in data, "Missing text"
    assert data['chars'] > 0, "No characters extracted"
    assert content in data['text'], f"Text mismatch: {data['text']}"
    
    print(f"✅ TXT parsing: {data['chars']} chars extracted")

def test_parse_file_pdf():
    """Test POST /api/parse/file with PDF file."""
    print("\n=== Test 2: POST /api/parse/file (PDF) ===")
    
    text = "This is a test PDF document."
    file = create_pdf_file(text)
    
    r = requests.post(f"{API}/parse/file",
                     files={'file': ('test.pdf', file, 'application/pdf')},
                     timeout=15)
    
    assert r.status_code == 200, f"Failed: {r.status_code} {r.text}"
    data = r.json()
    
    assert data['chars'] > 0, "No characters extracted from PDF"
    assert 'test' in data['text'].lower(), f"Expected text not found: {data['text']}"
    
    print(f"✅ PDF parsing: {data['chars']} chars extracted")

def test_parse_file_docx():
    """Test POST /api/parse/file with DOCX file."""
    print("\n=== Test 3: POST /api/parse/file (DOCX) ===")
    
    text = "This is a test DOCX document with sample content."
    file = create_docx_file(text)
    
    r = requests.post(f"{API}/parse/file",
                     files={'file': ('test.docx', file, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},
                     timeout=15)
    
    assert r.status_code == 200, f"Failed: {r.status_code} {r.text}"
    data = r.json()
    
    assert data['chars'] > 0, "No characters extracted from DOCX"
    assert text in data['text'], f"Text mismatch: {data['text']}"
    
    print(f"✅ DOCX parsing: {data['chars']} chars extracted")

def test_parse_file_unsupported():
    """Test POST /api/parse/file with unsupported extension (should fallback to utf-8)."""
    print("\n=== Test 4: POST /api/parse/file (unsupported .zip) ===")
    
    # Create a simple text content but name it .zip
    content = "This is actually text but named as zip"
    file = create_txt_file(content)
    
    r = requests.post(f"{API}/parse/file",
                     files={'file': ('test.zip', file, 'application/zip')},
                     timeout=15)
    
    # Should succeed with utf-8 fallback
    assert r.status_code == 200, f"Failed: {r.status_code} {r.text}"
    data = r.json()
    assert data['chars'] > 0, "No characters extracted"
    
    print(f"✅ Unsupported extension fallback: {data['chars']} chars extracted")

def test_patch_jd_as_diana():
    """Test PATCH /api/positions/{pid}/jd as Diana (DM)."""
    print("\n=== Test 5: PATCH /api/positions/{pid}/jd (Diana) ===")
    
    users = get_users()
    diana = client_for(users['diana']['id'])
    
    # Get any position
    pos = get_position_by_ticket(diana, 'POS-101')
    assert pos is not None, "POS-101 not found"
    
    new_jd = "Updated JD: We need a senior Python developer with FastAPI experience."
    new_skills = ["Python", "FastAPI", "MongoDB"]
    
    r = diana.patch(f"{API}/positions/{pos['id']}/jd",
                   json={'jd_text': new_jd, 'skills': new_skills},
                   timeout=15)
    
    assert r.status_code == 200, f"Failed: {r.status_code} {r.text}"
    data = r.json()
    
    assert data['jd_text'] == new_jd, "JD text not updated"
    assert data['meta']['skills'] == new_skills, "Skills not updated"
    
    # Verify by fetching position detail
    detail = diana.get(f"{API}/positions/{pos['id']}", timeout=15).json()
    assert detail['jd_text'] == new_jd, "JD not persisted"
    assert detail['meta']['skills'] == new_skills, "Skills not persisted"
    
    # Check for JD_UPDATED event
    events = detail.get('events', [])
    assert any(e['event_type'] == 'JD_UPDATED' for e in events), "JD_UPDATED event not found"
    
    print(f"✅ JD updated successfully for {pos['ticket_number']}")

def test_patch_jd_scope_enforcement():
    """Test PATCH /api/positions/{pid}/jd scope enforcement (Priya can't patch Atlas)."""
    print("\n=== Test 6: PATCH /api/positions/{pid}/jd (scope enforcement) ===")
    
    users = get_users()
    diana = client_for(users['diana']['id'])
    priya = client_for(users['priya']['id'])
    
    # Get an Atlas position (POS-103)
    atlas_pos = get_position_by_ticket(diana, 'POS-103')
    assert atlas_pos is not None, "POS-103 (Atlas) not found"
    
    # Priya (Phoenix PM) tries to patch Atlas position
    r = priya.patch(f"{API}/positions/{atlas_pos['id']}/jd",
                   json={'jd_text': 'Unauthorized update'},
                   timeout=15)
    
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"
    assert 'not found in your scope' in r.text or 'outside your project scope' in r.text, "Wrong error message"
    
    print(f"✅ Scope enforcement working: Priya blocked from Atlas position")

def test_bulk_upload_cvs():
    """Test POST /api/positions/{pid}/candidates/bulk with multiple files."""
    print("\n=== Test 7: POST /api/positions/{pid}/candidates/bulk ===")
    
    users = get_users()
    diana = client_for(users['diana']['id'])
    
    # Get a position
    pos = get_position_by_ticket(diana, 'POS-105')
    assert pos is not None, "POS-105 not found"
    
    # Create 3 candidate CV files with realistic data
    cv1 = create_txt_file("""
John Smith
john.smith@example.com
Phone: +1-555-0101

PROFESSIONAL SUMMARY
Senior Python Developer with 8 years of experience in backend development.

SKILLS
- Python, FastAPI, Django
- MongoDB, PostgreSQL
- AWS, Docker, Kubernetes

EXPERIENCE
Senior Developer at Tech Corp (2018-2024)
- Built scalable APIs using FastAPI
- Managed MongoDB databases
    """)
    
    cv2 = create_txt_file("""
Sarah Johnson
sarah.j@techmail.com

PROFILE
Full-stack developer specializing in Python and React.

TECHNICAL SKILLS
Python, JavaScript, React, Node.js, FastAPI, MongoDB

WORK HISTORY
Lead Developer - StartupXYZ (2020-2024)
- Developed microservices architecture
- 5 years Python experience
    """)
    
    cv3 = create_txt_file("""
Michael Chen
m.chen@devmail.io

SUMMARY
Backend engineer with expertise in Python and cloud technologies.

CORE COMPETENCIES
- Python (FastAPI, Flask)
- Database design (MongoDB, Redis)
- CI/CD pipelines

PROFESSIONAL EXPERIENCE
Software Engineer at CloudTech (2019-2024)
    """)
    
    files = [
        ('files', ('john_smith.txt', cv1, 'text/plain')),
        ('files', ('sarah_johnson.txt', cv2, 'text/plain')),
        ('files', ('michael_chen.txt', cv3, 'text/plain'))
    ]
    
    r = requests.post(f"{API}/positions/{pos['id']}/candidates/bulk",
                     files=files,
                     headers={'X-User-Id': users['diana']['id']},
                     timeout=60)  # LLM extraction may take time
    
    assert r.status_code == 200, f"Failed: {r.status_code} {r.text}"
    data = r.json()
    
    assert 'created' in data, "Missing 'created' field"
    assert 'errors' in data, "Missing 'errors' field"
    assert 'count' in data, "Missing 'count' field"
    assert data['count'] == 3, f"Expected 3 candidates created, got {data['count']}"
    assert len(data['created']) == 3, f"Expected 3 in created list, got {len(data['created'])}"
    
    # Verify each candidate has name and email
    for c in data['created']:
        assert 'name' in c and c['name'], f"Missing name: {c}"
        assert 'email' in c, f"Missing email: {c}"
        assert 'filename' in c, f"Missing filename: {c}"
        # Source should start with 'upload:'
        
    # Verify candidates were added to position
    detail = diana.get(f"{API}/positions/{pos['id']}", timeout=15).json()
    candidates = detail.get('candidates', [])
    
    # Check that sources start with 'upload:'
    upload_candidates = [c for c in candidates if c.get('source', '').startswith('upload:')]
    assert len(upload_candidates) >= 3, f"Expected at least 3 upload candidates, got {len(upload_candidates)}"
    
    print(f"✅ Bulk upload: {data['count']} candidates created")
    
    # Test duplicate upload (should return 0 created + errors)
    print("\n=== Test 7b: Bulk upload duplicates ===")
    
    cv1_dup = create_txt_file("""
John Smith
john.smith@example.com
Duplicate candidate
    """)
    
    files_dup = [('files', ('john_smith_dup.txt', cv1_dup, 'text/plain'))]
    
    r2 = requests.post(f"{API}/positions/{pos['id']}/candidates/bulk",
                      files=files_dup,
                      headers={'X-User-Id': users['diana']['id']},
                      timeout=60)
    
    assert r2.status_code == 200, f"Failed: {r2.status_code} {r2.text}"
    data2 = r2.json()
    
    assert data2['count'] == 0, f"Expected 0 created (duplicate), got {data2['count']}"
    assert len(data2['errors']) > 0, f"Expected errors for duplicates, got {data2['errors']}"
    assert 'already exists' in str(data2['errors']).lower(), f"Expected 'already exists' error: {data2['errors']}"
    
    print(f"✅ Duplicate detection working: {len(data2['errors'])} duplicates rejected")

def test_bulk_upload_scope_enforcement():
    """Test bulk upload scope enforcement (Priya can't upload to Atlas)."""
    print("\n=== Test 8: Bulk upload scope enforcement ===")
    
    users = get_users()
    diana = client_for(users['diana']['id'])
    priya = client_for(users['priya']['id'])
    
    # Get Atlas position
    atlas_pos = get_position_by_ticket(diana, 'POS-104')
    assert atlas_pos is not None, "POS-104 (Atlas) not found"
    
    cv = create_txt_file("Test Candidate\ntest@example.com\nPython developer")
    files = [('files', ('test.txt', cv, 'text/plain'))]
    
    r = requests.post(f"{API}/positions/{atlas_pos['id']}/candidates/bulk",
                     files=files,
                     headers={'X-User-Id': users['priya']['id']},
                     timeout=30)
    
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"
    
    print(f"✅ Bulk upload scope enforcement working")

def test_import_candidates_csv():
    """Test POST /api/import/candidates with CSV."""
    print("\n=== Test 9: POST /api/import/candidates (CSV) ===")
    
    users = get_users()
    diana = client_for(users['diana']['id'])
    
    # Get valid ticket numbers
    positions = diana.get(f"{API}/positions", timeout=15).json()
    tickets = [p['ticket_number'] for p in positions[:3]]
    
    # Create CSV with 3 rows
    csv_content = f"""ticket_number,name,email,cv_text
{tickets[0]},Alice Williams,alice.w@example.com,"Senior Python developer with 7 years experience. Expert in FastAPI and MongoDB."
{tickets[1]},Bob Martinez,bob.m@example.com,"Full-stack engineer. Python, React, Node.js. 5 years experience."
{tickets[2]},Carol Davis,carol.d@example.com,"Backend specialist. Python, Django, FastAPI. Database expert."
"""
    
    csv_file = io.BytesIO(csv_content.encode('utf-8'))
    
    r = requests.post(f"{API}/import/candidates",
                     files={'file': ('candidates.csv', csv_file, 'text/csv')},
                     headers={'X-User-Id': users['diana']['id']},
                     timeout=30)
    
    assert r.status_code == 200, f"Failed: {r.status_code} {r.text}"
    data = r.json()
    
    assert 'created' in data, "Missing 'created' field"
    assert 'updated' in data, "Missing 'updated' field"
    assert 'errors' in data, "Missing 'errors' field"
    assert data['created'] == 3, f"Expected 3 created, got {data['created']}"
    
    print(f"✅ CSV import: {data['created']} candidates created")
    
    # Test upsert (re-import same CSV)
    print("\n=== Test 9b: CSV import upsert ===")
    
    csv_content_updated = f"""ticket_number,name,email,cv_text
{tickets[0]},Alice Williams,alice.w@example.com,"UPDATED: Senior Python developer with 8 years experience now."
{tickets[1]},Bob Martinez,bob.m@example.com,"UPDATED: Full-stack engineer with more experience."
{tickets[2]},Carol Davis,carol.d@example.com,"UPDATED: Backend specialist with cloud expertise."
"""
    
    csv_file2 = io.BytesIO(csv_content_updated.encode('utf-8'))
    
    r2 = requests.post(f"{API}/import/candidates",
                      files={'file': ('candidates.csv', csv_file2, 'text/csv')},
                      headers={'X-User-Id': users['diana']['id']},
                      timeout=30)
    
    assert r2.status_code == 200, f"Failed: {r2.status_code} {r2.text}"
    data2 = r2.json()
    
    assert data2['created'] == 0, f"Expected 0 created (upsert), got {data2['created']}"
    assert data2['updated'] == 3, f"Expected 3 updated, got {data2['updated']}"
    
    print(f"✅ CSV upsert: {data2['updated']} candidates updated")

def test_import_candidates_errors():
    """Test CSV import error handling."""
    print("\n=== Test 10: CSV import error handling ===")
    
    users = get_users()
    diana = client_for(users['diana']['id'])
    priya = client_for(users['priya']['id'])
    
    # Get valid tickets
    diana_positions = diana.get(f"{API}/positions", timeout=15).json()
    priya_positions = priya.get(f"{API}/positions", timeout=15).json()
    
    valid_ticket = diana_positions[0]['ticket_number']
    
    # Find an Atlas ticket (out of scope for Priya)
    atlas_ticket = None
    for p in diana_positions:
        if p['ticket_number'] not in [pp['ticket_number'] for pp in priya_positions]:
            atlas_ticket = p['ticket_number']
            break
    
    # CSV with errors: missing ticket, unknown ticket, out-of-scope ticket
    csv_content = f"""ticket_number,name,email,cv_text
,Missing Ticket,missing@example.com,"CV text here"
INVALID-999,Unknown Ticket,unknown@example.com,"CV text here"
{atlas_ticket},Out of Scope,outofscope@example.com,"CV text here"
{valid_ticket},Valid Candidate,valid@example.com,"Valid CV text"
"""
    
    csv_file = io.BytesIO(csv_content.encode('utf-8'))
    
    r = requests.post(f"{API}/import/candidates",
                     files={'file': ('candidates_errors.csv', csv_file, 'text/csv')},
                     headers={'X-User-Id': users['priya']['id']},
                     timeout=30)
    
    assert r.status_code == 200, f"Failed: {r.status_code} {r.text}"
    data = r.json()
    
    assert len(data['errors']) >= 3, f"Expected at least 3 errors, got {len(data['errors'])}: {data['errors']}"
    
    # Check error messages
    errors_str = str(data['errors']).lower()
    assert 'missing ticket' in errors_str, f"Missing 'missing ticket' error: {data['errors']}"
    assert 'no position' in errors_str or 'invalid' in errors_str, f"Missing 'unknown ticket' error: {data['errors']}"
    assert 'outside your scope' in errors_str or 'scope' in errors_str, f"Missing 'out of scope' error: {data['errors']}"
    
    # Valid row should be created
    assert data['created'] >= 1, f"Expected at least 1 created, got {data['created']}"
    
    print(f"✅ CSV error handling: {len(data['errors'])} errors caught, {data['created']} valid rows imported")

def test_smoke_old_flows():
    """Smoke test old flows to ensure no regression."""
    print("\n=== Test 11: Smoke test old flows ===")
    
    users = get_users()
    diana = client_for(users['diana']['id'])
    priya = client_for(users['priya']['id'])
    
    # Test GET /api/agents
    r = requests.get(f"{API}/agents", timeout=15)
    assert r.status_code == 200, f"GET /api/agents failed: {r.text}"
    agents = r.json()
    assert len(agents) > 0, "No agents returned"
    print(f"  ✓ GET /api/agents: {len(agents)} agents")
    
    # Test GET /api/reports/summary
    r = diana.get(f"{API}/reports/summary", timeout=15)
    assert r.status_code == 200, f"GET /api/reports/summary failed: {r.text}"
    summary = r.json()
    assert 'total_positions' in summary, "Missing total_positions"
    print(f"  ✓ GET /api/reports/summary: {summary['total_positions']} positions")
    
    # Test GET /api/positions with different personas
    r_diana = diana.get(f"{API}/positions", timeout=15)
    assert r_diana.status_code == 200, f"Diana GET /api/positions failed: {r_diana.text}"
    diana_positions = r_diana.json()
    
    r_priya = priya.get(f"{API}/positions", timeout=15)
    assert r_priya.status_code == 200, f"Priya GET /api/positions failed: {r_priya.text}"
    priya_positions = r_priya.json()
    
    # Diana should see more positions than Priya
    assert len(diana_positions) > len(priya_positions), \
        f"Scoping issue: Diana sees {len(diana_positions)}, Priya sees {len(priya_positions)}"
    
    print(f"  ✓ GET /api/positions scoping: Diana={len(diana_positions)}, Priya={len(priya_positions)}")
    print(f"✅ Smoke tests passed")

# ========== Main Execution ==========

if __name__ == "__main__":
    print("=" * 70)
    print("BACKEND API TESTS - NEW ENDPOINTS")
    print("=" * 70)
    
    try:
        # Test 1-4: File parsing
        test_parse_file_txt()
        test_parse_file_pdf()
        test_parse_file_docx()
        test_parse_file_unsupported()
        
        # Test 5-6: JD patching
        test_patch_jd_as_diana()
        test_patch_jd_scope_enforcement()
        
        # Test 7-8: Bulk CV upload
        test_bulk_upload_cvs()
        test_bulk_upload_scope_enforcement()
        
        # Test 9-10: CSV import
        test_import_candidates_csv()
        test_import_candidates_errors()
        
        # Test 11: Smoke tests
        test_smoke_old_flows()
        
        print("\n" + "=" * 70)
        print("ALL TESTS PASSED ✅")
        print("=" * 70)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        raise
