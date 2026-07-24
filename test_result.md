#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================
user_problem_statement: |
  Deployed existing Agentic AI Recruitment Pipeline from GitHub repo. Then added:
  1. "New Position" button on Pipeline (dialog with ticket_number, title, project, priority, skills, JD paste OR PDF/DOCX upload+parse)
  2. "Edit JD" on Job Description tab (paste OR PDF/DOCX upload+parse) with skills edit
  3. Bulk CV upload on Candidates tab (multi PDF/DOCX/TXT drop; backend parses; LLM extracts name+email per file)
  4. Candidates CSV importer on Import page (ticket_number, name, email, cv_text; upsert by ticket+email/name)

backend:
  - task: "POST /api/parse/file — parse PDF/DOCX/TXT to text"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "New endpoint uses pypdf + python-docx. TXT falls back to utf-8 decode. 10MB limit."
        - working: true
          agent: "testing"
          comment: "✅ PASSED. Tested TXT (37 chars), PDF (28 chars), DOCX (49 chars), and unsupported .zip (38 chars with utf-8 fallback). All file types parsed correctly. Returns {filename, chars, text} as expected."
  - task: "PATCH /api/positions/{pid}/jd — update JD text + skills"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Updates jd_text and optionally meta.skills. Emits JD_UPDATED event. Scoped to caller's project."
        - working: true
          agent: "testing"
          comment: "✅ PASSED. Tested as Diana (DM) - successfully updated JD text and skills for POS-101. JD_UPDATED event emitted correctly. Scope enforcement verified: Priya (Phoenix PM) correctly blocked (404) from patching Atlas position POS-103."
  - task: "POST /api/positions/{pid}/candidates/bulk — multi-file CV upload with LLM name/email extraction"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Multipart upload with 'files' field. Parses each file, then gathers LLM extractions concurrently via asyncio.gather. Skips duplicates by email/name on same position. Falls back to filename+regex email if LLM fails."
        - working: true
          agent: "testing"
          comment: "✅ PASSED. Uploaded 3 CV files (john_smith.txt, sarah_johnson.txt, michael_chen.txt) to POS-105. All 3 candidates created with correct name/email extraction via LLM. Source field correctly starts with 'upload:'. Duplicate detection working: re-uploading same candidate returned 0 created + 'already exists' error. Scope enforcement verified: Priya blocked (404) from uploading to Atlas position."
  - task: "POST /api/import/candidates — CSV candidates importer"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "CSV columns: ticket_number, name, email, cv_text. Upsert by (position + email) or (position + name). Scope-checks each row."
        - working: true
          agent: "testing"
          comment: "✅ PASSED. First import: 3 candidates created successfully. Second import (upsert): 3 candidates updated (0 created). Error handling verified: missing ticket_number, unknown ticket (INVALID-999), and out-of-scope ticket all correctly rejected with appropriate error messages. Valid rows imported despite errors in other rows."

frontend:
  - task: "New Position dialog on Pipeline page (with JD paste + upload)"
    implemented: true
    working: "NA"
    file: "frontend/src/components/NewPositionDialog.jsx + Dashboard.jsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Not tested by main agent (frontend tests only on user request)."
  - task: "Edit JD dialog on Position Detail (paste + upload + skills)"
    implemented: true
    working: "NA"
    file: "frontend/src/pages/PositionDetail.jsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Not tested by main agent."
  - task: "Bulk CV upload on Candidates tab"
    implemented: true
    working: "NA"
    file: "frontend/src/pages/PositionDetail.jsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Uses multipart 'files' array. Shows per-file result inline."
  - task: "Candidates CSV import card on Import page"
    implemented: true
    working: "NA"
    file: "frontend/src/pages/ImportPage.jsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false

metadata:
  created_by: "main_agent"
  version: "1.1"
  test_sequence: 2
  run_ui: false

test_plan:
  current_focus: []
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      New intake endpoints added — please test backend only:
      1. POST /api/parse/file — upload a PDF, DOCX and TXT (multipart 'file'); expect { filename, chars, text }.
      2. PATCH /api/positions/{pid}/jd — { jd_text, skills? }; check scope enforcement (Priya can't patch Atlas).
      3. POST /api/positions/{pid}/candidates/bulk — multipart 'files' (multiple). Use small text files (rename to .txt) with a name and email inside so LLM extraction works. Confirm 'count', 'created[]', 'errors[]', and that duplicates on retry are rejected.
      4. POST /api/import/candidates — CSV upload; test upsert on re-import; test errors for missing ticket / out-of-scope ticket / missing cv_text.
      Existing endpoints must still work. Persona header X-User-Id is used for scope. Personas seeded: diana (dm), priya (pm-Phoenix), pablo (pm-Atlas), sam (staffing). Fetch /api/users to get IDs.
  - agent: "testing"
    message: |
      ✅ ALL 4 NEW BACKEND ENDPOINTS TESTED AND WORKING CORRECTLY.
      
      Test Results Summary:
      1. POST /api/parse/file - ✅ PASSED (TXT, PDF, DOCX, unsupported extensions all working)
      2. PATCH /api/positions/{pid}/jd - ✅ PASSED (JD update, skills update, JD_UPDATED event, scope enforcement all working)
      3. POST /api/positions/{pid}/candidates/bulk - ✅ PASSED (LLM extraction, duplicate detection, scope enforcement all working)
      4. POST /api/import/candidates - ✅ PASSED (CSV import, upsert, error handling all working)
      
      Smoke tests on old flows: ✅ PASSED
      - GET /api/agents: 6 agents returned
      - GET /api/reports/summary: working correctly
      - GET /api/positions: scoping working (Diana sees 6, Priya sees 3)
      
      No regressions detected. All endpoints functioning as expected.
