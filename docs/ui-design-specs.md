# AgentEHR UI Design Specifications

## Design System

### Color Palette

```css
:root {
  /* Primary Colors */
  --primary-orange: #e4643d;
  --primary-orange-hover: #d55a35;
  --primary-orange-light: #fef3f0;

  /* Secondary Colors */
  --secondary-cyan: #3dbde4;
  --secondary-cyan-hover: #2fa8cc;
  --secondary-cyan-light: #f0fafc;

  /* Neutrals */
  --neutral-900: #1a1a2e;
  --neutral-800: #2d2d44;
  --neutral-700: #444459;
  --neutral-600: #666680;
  --neutral-500: #8888a0;
  --neutral-400: #aaaabb;
  --neutral-300: #ccccdd;
  --neutral-200: #e8e8f0;
  --neutral-100: #f5f5f7;
  --neutral-50: #fafafa;
  --white: #ffffff;

  /* Semantic Colors */
  --success: #3de477;
  --success-light: #e8fef0;
  --warning: #e4a43d;
  --warning-light: #fef8e8;
  --error: #e43d3d;
  --error-light: #fef0f0;

  /* Shadows */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.07);
  --shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.1);
}
```

### Typography

```css
/* Font Family */
font-family: 'Schibsted Grotesk', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;

/* Type Scale */
--text-xs: 0.75rem;    /* 12px - Caption */
--text-sm: 0.875rem;   /* 14px - Small body */
--text-base: 1rem;     /* 16px - Body */
--text-lg: 1.125rem;   /* 18px - Large body */
--text-xl: 1.25rem;    /* 20px - H6 */
--text-2xl: 1.5rem;    /* 24px - H5 */
--text-3xl: 1.875rem;  /* 30px - H4 */
--text-4xl: 2.25rem;   /* 36px - H3 */
--text-5xl: 3rem;      /* 48px - H2 */
--text-6xl: 3.75rem;   /* 60px - H1 */

/* Font Weights */
--font-normal: 400;
--font-medium: 500;
--font-semibold: 600;
--font-bold: 700;
```

### Spacing

```css
--space-1: 0.25rem;   /* 4px */
--space-2: 0.5rem;    /* 8px */
--space-3: 0.75rem;   /* 12px */
--space-4: 1rem;      /* 16px */
--space-5: 1.25rem;   /* 20px */
--space-6: 1.5rem;    /* 24px */
--space-8: 2rem;      /* 32px */
--space-10: 2.5rem;   /* 40px */
--space-12: 3rem;     /* 48px */
```

### Border Radius

```css
--radius-sm: 4px;
--radius-md: 8px;
--radius-lg: 12px;
--radius-xl: 16px;
--radius-full: 9999px;
```

---

## Screen 1: Main Chat Interface

### Layout Structure

```
+------------------+------------------------+------------------+
|                  |                        |                  |
|    LEFT SIDEBAR  |      MAIN CHAT AREA    |   RIGHT PANEL    |
|      (260px)     |       (flexible)       |     (320px)      |
|                  |                        |                  |
|    Dark grey     |     White background   |   Light grey     |
|    #1a1a2e       |        #ffffff         |    #f5f5f7       |
|                  |                        |                  |
+------------------+------------------------+------------------+
```

### Left Sidebar Components

**Search Bar**
- Height: 40px
- Background: rgba(255,255,255,0.1)
- Border radius: 8px
- Placeholder: "Search patients..."
- Icon: Search icon (left)

**Patient List Item**
```
+------------------------------------------+
| [Avatar] Patient Name                    |
|          MRN: 123456789                  |
|          Last: 2 hours ago               |
+------------------------------------------+
```
- Height: 72px
- Padding: 12px 16px
- Active state: Orange left border (3px)
- Hover: Background lighten 5%

### Main Chat Area

**Header Bar**
- Height: 64px
- Background: White
- Border bottom: 1px solid #e8e8f0
- Content:
  - Left: AgentEHR logo (orange)
  - Right: Dark mode toggle, User avatar dropdown

**Message Bubble - AI**
```
+------------------------------------------+
| [Cyan Avatar]  AI Message text here      |
|               with possible citations    |
|               [PubMed] [UpToDate]        |
+------------------------------------------+
```
- Max width: 70%
- Background: #f5f5f7
- Border radius: 12px 12px 12px 0
- Padding: 12px 16px

**Message Bubble - User**
```
+------------------------------------------+
|     User message text aligned right      |
|                          [Grey Avatar]   |
+------------------------------------------+
```
- Max width: 70%
- Background: #e8e8f0
- Border radius: 12px 12px 0 12px
- Padding: 12px 16px
- Align: right

**Citation Chip**
- Height: 24px
- Background: var(--secondary-cyan-light)
- Border: 1px solid var(--secondary-cyan)
- Border radius: 12px
- Font size: 12px
- Padding: 4px 10px

**Chat Input Area**
- Height: 56px (minimum, expandable)
- Background: White
- Border top: 1px solid #e8e8f0
- Input field: Border radius 8px, grey border
- Send button: Orange (#e4643d), 40px square, rounded

### Right Panel Components

**Patient Context Card**
```
+------------------------------------------+
| Patient Name                       Edit  |
| DOB: Jan 15, 1965 | Age: 61 | Male      |
| MRN: 123456789                          |
+------------------------------------------+
```
- Background: White
- Border radius: 12px
- Shadow: var(--shadow-sm)
- Padding: 16px

**Section Headers**
- Font size: 14px
- Font weight: 600
- Color: #666680
- Margin bottom: 8px
- Text transform: uppercase

**Condition Pill**
- Background: var(--secondary-cyan-light)
- Border radius: 16px
- Padding: 4px 12px
- Font size: 13px

**Medication Item**
- Height: 48px
- Border bottom: 1px solid #e8e8f0
- Shows: Drug name, dosage, frequency

**Allergy Badge (Severe)**
- Background: var(--error-light)
- Border-left: 3px solid var(--error)
- Icon: Warning triangle

---

## Screen 2: Approval Queue

### Layout Structure

```
+------------------------------------------------+
|              HEADER BAR (64px)                 |
+------------------------------------------------+
|    TABS: Pending | Approved | Rejected         |
+------------------------------------------------+
|    FILTER BAR: [Patient v] [Type v] [Search]   |
+------------------------------------------------+
|                                                |
|    +------ ACTION CARD 1 ------+              |
|    |                           |              |
|    +---------------------------+              |
|                                                |
|    +------ ACTION CARD 2 ------+              |
|    |                           |              |
|    +---------------------------+              |
|                                                |
|    +------ ACTION CARD 3 ------+              |
|    |                           |              |
|    +---------------------------+              |
|                                                |
+------------------------------------------------+
```

### Tab Navigation

```
[ Pending (12) ]  [ Approved ]  [ Rejected ]
      ^
   Active tab: Orange underline, bold text
```
- Height: 48px
- Active: Orange bottom border (3px), font-weight: 600
- Inactive: No border, font-weight: 400
- Hover: Light orange background

### Filter Bar
- Height: 56px
- Background: White
- Padding: 12px 24px
- Dropdowns: 180px width each
- Search: Flexible width, right aligned

### Action Card

```
+----------------------------------------------------------------+
|  [Icon]  |  Action Summary (Bold)                    | Approve |
|  Circle  |  Patient: John Smith (MRN: 123456)       | Reject  |
|          |  AI Reasoning: Based on lab results...   |         |
|          |  [Drug Interaction - Severe]             | 2h ago  |
+----------------------------------------------------------------+
```

**Card Specifications**
- Background: White
- Border radius: 12px
- Shadow: var(--shadow-md)
- Padding: 20px 24px
- Margin bottom: 16px
- Border left: 4px solid (color based on action type)

**Action Type Icons**
- Size: 48px circle
- Medication: Pill icon, orange background
- Lab Order: Flask icon, cyan background
- Appointment: Calendar icon, purple (#a855f7) background

**Warning Badges**
```css
/* Severe Warning */
.badge-severe {
  background: #fef0f0;
  color: #e43d3d;
  border: 1px solid #e43d3d;
}

/* Caution Warning */
.badge-caution {
  background: #fef8e8;
  color: #b8860b;
  border: 1px solid #e4a43d;
}

/* Compliant Badge */
.badge-compliant {
  background: #e8fef0;
  color: #22c55e;
  border: 1px solid #3de477;
}
```

**Buttons**
- Approve: Orange filled, white text, 100px width
- Reject: Grey outlined, grey text, 100px width
- Height: 36px
- Border radius: 8px

---

## Screen 3: Patient Summary View

### Layout Structure

```
+------------------------------------------------+
|              HEADER BAR (64px)                 |
+------------------------------------------------+
|         PATIENT HEADER SECTION (120px)         |
| [Avatar]  Name, DOB, Age, Gender, MRN          |
|                                    [Buttons]   |
+------------------------------------------------+
| Overview | Medications | Labs | Notes | Orders |
+------------------------------------------------+
|                                                |
|  +-- Card 1 --+    +-- Card 2 --+             |
|  |            |    |            |             |
|  +------------+    +------------+             |
|                                                |
|  +-- Card 3 --+    +-- Card 4 --+             |
|  |            |    |            |             |
|  +------------+    +------------+             |
|                                                |
+------------------------------------------------+
```

### Patient Header

**Avatar**
- Size: 80px
- Border radius: 50%
- Background: var(--secondary-cyan-light)
- Initials: 32px font, cyan color

**Patient Info**
```
John Michael Smith
DOB: January 15, 1965  |  Age: 61  |  Male
MRN: 123-456-789

[Active] <-- Green status badge
```

**Action Buttons**
- "Start Chat": Orange filled, icon + text
- "View History": Grey outlined

### Tab Navigation
- Same style as Approval Queue
- Active tab: Orange underline

### Content Cards

**Active Conditions Card**
```
+------------------------------------------+
| ACTIVE CONDITIONS                   View |
+------------------------------------------+
| [Primary] Type 2 Diabetes Mellitus      |
|           ICD-10: E11.9                 |
+------------------------------------------+
| Hypertension                            |
| ICD-10: I10                             |
+------------------------------------------+
| Chronic Kidney Disease - Stage 3        |
| ICD-10: N18.3                           |
+------------------------------------------+
```
- Card padding: 20px
- Item separator: 1px solid #e8e8f0
- Primary badge: Orange background, white text

**Recent Vitals Card**
```
+------------------------------------------+
| RECENT VITALS                    Updated |
+------------------------------------------+
|  BP          HR          Temp           |
| 142/88      72 bpm      98.6°F          |
|   ^           -           -             |
+------------------------------------------+
|  SpO2       Weight                      |
|  97%        187 lbs                     |
|   -           ^                         |
+------------------------------------------+
```
- Grid layout: 3 columns, 2 rows
- Trend arrows: Red (up bad), Green (down good), Grey (stable)
- Abnormal values: Red text

**Allergies Card**
```
+------------------------------------------+
| ALLERGIES                                |
+------------------------------------------+
| [!] Penicillin - Anaphylaxis    SEVERE  |
|     Red background strip                |
+------------------------------------------+
| [!] Sulfa Drugs - Rash         MODERATE |
|     Yellow background strip             |
+------------------------------------------+
| [i] Latex - Skin irritation      MILD   |
|     Grey background strip               |
+------------------------------------------+
```

**Care Team Card**
```
+------------------------------------------+
| CARE TEAM                                |
+------------------------------------------+
| Primary Care                             |
| Dr. Sarah Johnson, MD                    |
| Internal Medicine                        |
+------------------------------------------+
| Specialists                              |
| Dr. Michael Chen - Endocrinology        |
| Dr. Lisa Park - Nephrology              |
+------------------------------------------+
```

---

## Component Library

### Buttons

```css
/* Primary Button */
.btn-primary {
  background: #e4643d;
  color: white;
  border: none;
  padding: 10px 20px;
  border-radius: 8px;
  font-weight: 600;
  transition: background 0.2s;
}
.btn-primary:hover {
  background: #d55a35;
}

/* Secondary Button */
.btn-secondary {
  background: transparent;
  color: #666680;
  border: 1px solid #ccccdd;
  padding: 10px 20px;
  border-radius: 8px;
  font-weight: 500;
  transition: all 0.2s;
}
.btn-secondary:hover {
  background: #f5f5f7;
  border-color: #aaaabb;
}

/* Icon Button */
.btn-icon {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}
```

### Input Fields

```css
.input-field {
  height: 44px;
  padding: 0 14px;
  border: 1px solid #ccccdd;
  border-radius: 8px;
  font-size: 15px;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.input-field:focus {
  border-color: #e4643d;
  box-shadow: 0 0 0 3px rgba(228, 100, 61, 0.1);
  outline: none;
}
```

### Status Badges

```css
.badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}

.badge-active { background: #e8fef0; color: #22c55e; }
.badge-pending { background: #fef8e8; color: #b8860b; }
.badge-inactive { background: #f5f5f7; color: #666680; }
```

### Loading States

```css
/* Typing indicator for AI */
.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
}
.typing-indicator span {
  width: 8px;
  height: 8px;
  background: #3dbde4;
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out;
}
.typing-indicator span:nth-child(1) { animation-delay: 0s; }
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}
```

---

## Dark Mode Tokens

```css
[data-theme="dark"] {
  --bg-primary: #0f0f1a;
  --bg-secondary: #1a1a2e;
  --bg-tertiary: #252540;
  --text-primary: #ffffff;
  --text-secondary: #aaaabb;
  --border-color: #333355;
  --card-bg: #1a1a2e;

  /* Adjusted accents for dark mode */
  --primary-orange: #f07050;
  --secondary-cyan: #50d0f0;
}
```

---

## Responsive Breakpoints

```css
/* Desktop: Full three-column layout */
@media (min-width: 1280px) {
  .sidebar { width: 260px; }
  .main-content { flex: 1; }
  .right-panel { width: 320px; }
}

/* Tablet: Collapsible sidebar, hidden right panel */
@media (max-width: 1279px) and (min-width: 768px) {
  .sidebar { width: 72px; } /* Icons only */
  .right-panel { display: none; }
}

/* Mobile: Stack layout */
@media (max-width: 767px) {
  .sidebar { display: none; }
  .right-panel { display: none; }
  /* Use bottom navigation */
}
```

---

## Stitch Prompts

Use these prompts directly in Stitch to generate screens:

### Screen 1 Prompt
```
Create a clinical AI chat interface with three columns: dark sidebar (260px) with patient list, white main chat area with message bubbles, and light grey right panel (320px) with patient context. Use orange (#e4643d) as primary accent and cyan (#3dbde4) for AI elements. Include AgentEHR logo in header.
```

### Screen 2 Prompt
```
Create an approval queue dashboard with tabs (Pending/Approved/Rejected) and a card list of clinical actions to review. Each card shows action type icon, summary, patient info, warning badges (red/yellow/green), and approve/reject buttons. Use orange (#e4643d) for approve, grey for reject.
```

### Screen 3 Prompt
```
Create a patient summary view with large patient header (avatar, name, DOB, MRN) and tabbed content (Overview/Medications/Labs/Notes/Orders). Overview shows cards for conditions, vitals, allergies, and care team. Use orange (#e4643d) accents, card-based layout on light grey background.
```
