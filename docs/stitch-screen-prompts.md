# Stitch Screen Generation Prompts for AgentEHR

Use these detailed prompts with Stitch's `generate_screen_from_text` tool when the MCP connection is available.

---

## Screen 1: Main Chat Interface

**Project ID:** 4858348639960008525
**Device Type:** DESKTOP

### Prompt:
```
Create a Main Chat Interface screen for AgentEHR - a clinical AI assistant.

LAYOUT (Three-column design):
- Left sidebar (260px width): Dark grey background (#1a1a2e), contains:
  - Search bar at top with search icon
  - "Recent Patients" section header
  - Patient list items showing name, MRN, and last interaction time
  - Active patient highlighted with orange (#e4643d) left border

- Main chat area (center, flexible width): Clean white background
  - Header bar: "AgentEHR" logo in orange (#e4643d), user avatar with dropdown, dark mode toggle icon
  - Message history area showing conversation:
    - AI messages: Left-aligned, light grey bubbles with cyan (#3dbde4) avatar icon
    - User messages: Right-aligned, subtle grey bubbles
    - Include citation chips (small rounded pills linking to evidence sources)
  - Chat input area at bottom: Large text input field, orange "Send" button on right

- Right panel (320px width): Light grey background (#f5f5f7)
  - "Patient Context" header
  - Current patient card: Name, DOB, MRN, gender
  - "Active Conditions" section with condition pills
  - "Current Medications" section with medication list
  - "Allergies" section with red warning badges for severe allergies

COLOR SCHEME:
- Primary accent: Orange (#e4643d) for CTAs and branding
- Secondary accent: Cyan (#3dbde4) for AI elements
- Background: White (#ffffff) main, dark grey (#1a1a2e) sidebar
- Text: Dark grey (#333333) primary, light grey (#666666) secondary

TYPOGRAPHY:
- Sans-serif font (Schibsted Grotesk style)
- Clear hierarchy with bold headers

INTERACTIONS:
- Sticky header
- Smooth hover states on patient list items
- Loading indicator dots for AI typing
```

---

## Screen 2: Approval Queue

**Project ID:** 4858348639960008525
**Device Type:** DESKTOP

### Prompt:
```
Create an Approval Queue screen for AgentEHR - a clinical AI assistant for reviewing AI-suggested clinical actions.

LAYOUT:
- Header bar: "AgentEHR" logo in orange (#e4643d), breadcrumb showing "Approval Queue", user avatar, dark mode toggle
- Tab navigation below header: "Pending" (active, with count badge), "Approved", "Rejected"
- Filter bar: Dropdown to filter by patient, dropdown to filter by action type (Medication, Lab Order, Appointment), search field

MAIN CONTENT - Card list of pending actions:
Each card contains:
- Left side: Action type icon in a colored circle
  - Medication: pill icon, orange background
  - Lab Order: flask icon, cyan (#3dbde4) background
  - Appointment: calendar icon, purple background
- Center content:
  - Action summary in bold (e.g., "Prescribe Metformin 500mg twice daily")
  - Patient name and MRN below in grey
  - AI reasoning excerpt in smaller text
  - Warning badges if present:
    - Red badge: "Drug Interaction - Severe"
    - Yellow badge: "Dosage Alert"
    - Green badge: "Guideline Compliant"
- Right side:
  - Two buttons: "Approve" (orange filled), "Reject" (grey outlined)
  - Timestamp showing when suggested
  - "View Details" link

COLOR SCHEME:
- Primary: Orange (#e4643d) for approve buttons and primary actions
- Secondary: Cyan (#3dbde4) for lab-related items
- Warning colors: Red (#e43d3d) severe, Yellow (#e4a43d) caution, Green (#3de477) compliant
- Background: Light grey (#f8f9fa)
- Cards: White with subtle shadow

Show 4-5 sample action cards with different types and warning states. Include at least one medication with a drug interaction warning.
```

---

## Screen 3: Patient Summary View

**Project ID:** 4858348639960008525
**Device Type:** DESKTOP

### Prompt:
```
Create a Patient Summary View screen for AgentEHR - a clinical AI assistant.

LAYOUT:
- Header bar: "AgentEHR" logo in orange (#e4643d), back arrow, user avatar, dark mode toggle

PATIENT HEADER SECTION:
- Left: Circular avatar placeholder with patient initials
- Patient info: Full name (large, bold), DOB, Age, Gender, MRN
- Status badge: "Active" in green
- Right side: "Start Chat" button (orange), "View History" button (grey outlined)

TAB NAVIGATION:
- Tabs: "Overview" (active), "Medications", "Labs", "Notes", "Orders"
- Orange underline on active tab

OVERVIEW TAB CONTENT (Card-based layout in 2-column grid):

Left Column:
1. "Active Conditions" card:
   - List of conditions with ICD-10 codes
   - Primary diagnosis badge
   - Example: Type 2 Diabetes (E11.9), Hypertension (I10), Chronic Kidney Disease Stage 3 (N18.3)

2. "Recent Vitals" card:
   - Grid showing: Blood Pressure, Heart Rate, Temperature, SpO2, Weight
   - Each with value, unit, timestamp, and trend arrow (up/down/stable)
   - Abnormal values highlighted in red

Right Column:
1. "Allergies" card:
   - List with severity indicators
   - Severe allergies: Red background strip with warning icon (e.g., "Penicillin - Anaphylaxis")
   - Moderate: Yellow strip
   - Mild: Grey

2. "Care Team" card:
   - Primary Care Provider name and specialty
   - Specialists list
   - Contact icons

3. "Upcoming Appointments" card:
   - Next appointment date and type
   - Provider name
   - Location

COLOR SCHEME:
- Primary: Orange (#e4643d) for actions and accents
- Secondary: Cyan (#3dbde4) for informational elements
- Severity: Red (#e43d3d), Yellow (#e4a43d), Green (#3de477)
- Cards: White with subtle border-radius and shadow
- Background: Light grey (#f5f6f7)

TYPOGRAPHY:
- Sans-serif, clean hierarchy
- Bold headers, regular body text
- Monospace for MRN and codes
```

---

## Additional Screens (Future)

### Screen 4: Medication Review Panel

```
Create a medication management screen showing:
- Current medications in a table with columns: Drug Name, Dosage, Frequency, Prescriber, Last Filled
- Drug interaction matrix visualization
- "Add Medication" button with search
- Interaction warnings highlighted in red/yellow
- Integration with AI suggestions panel on right
Use orange (#e4643d) primary, cyan (#3dbde4) secondary colors
```

### Screen 5: Lab Results Timeline

```
Create a lab results screen showing:
- Timeline view of lab results with date filters
- Trend charts for key markers (A1c, Creatinine, etc.)
- Abnormal values highlighted
- AI interpretation panel on right side
- Export functionality
Use orange (#e4643d) primary, cyan (#3dbde4) for charts
```

### Screen 6: Clinical Notes with AI

```
Create a clinical notes screen with:
- Split view: Left shows note editor, Right shows AI suggestions
- Rich text editor with medical term autocomplete
- Template selection dropdown
- Voice-to-text button
- Citation suggestions from AI
- "Submit for Review" orange button
```

---

## Mobile Variants

### Mobile Chat Interface

```
Create a mobile version of the AgentEHR chat interface:
- Bottom navigation: Chat, Patients, Queue, Settings
- Full-width chat area
- Patient context in collapsible header drawer
- Floating action button for new chat
- Same color scheme: Orange (#e4643d), Cyan (#3dbde4)
```

### Mobile Approval Queue

```
Create a mobile approval queue for AgentEHR:
- Swipeable cards (swipe right to approve, left to reject)
- Compact card design with essential info
- Bottom sheet for full details
- Tab bar at top for Pending/Approved/Rejected
- Orange (#e4643d) for approve actions
```

---

## Quick Reference

| Element | Color Code | Usage |
|---------|------------|-------|
| Primary CTA | #e4643d | Buttons, Logo, Active states |
| Secondary | #3dbde4 | AI elements, Info badges |
| Severe Warning | #e43d3d | Drug interactions, Critical |
| Moderate Warning | #e4a43d | Caution, Dosage alerts |
| Success/Compliant | #3de477 | Approved, Guidelines met |
| Dark Background | #1a1a2e | Sidebar |
| Light Background | #f5f5f7 | Panels |
| Card Background | #ffffff | Content cards |
