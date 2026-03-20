# /setup - Profile Onboarding Interview

You are running the onboarding setup for the AI Job Search framework. Your goal is to collect the user's professional information and populate all profile files so the `/apply` workflow works out of the box.

---

## Step 0: Welcome & Choose Path

Welcome the user and explain what this setup does. Then offer two paths:

> **Welcome to the AI Job Search setup!**
>
> I'll help you set up your professional profile so Claude can evaluate job postings, tailor CVs, write cover letters, and prepare you for interviews.
>
> **Two ways to get started:**
>
> **Path A: Import from CV (recommended)** - Share your existing CV or resume (mention the file with @ or paste the text). I'll extract your information automatically and ask follow-up questions for anything missing.
>
> **Path B: Interview mode** - I'll walk you through structured questions section by section. Great if you're starting from scratch.
>
> Which do you prefer?

If the user specifies `$ARGUMENTS` containing `--section <name>`, skip to that section only for updating.

---

## Path A: Document Import

If the user provides a CV/resume:

1. Read the document thoroughly
2. Extract all structured information: name, contact, education, experience, skills, publications, awards
3. Present a summary of what was extracted
4. Ask follow-up questions for gaps (behavioral profile, career goals, deal-breakers, salary expectations, references)
5. Proceed to file generation (Step 3)

---

## Path B: Interview Mode

Walk through each section conversationally. Ask questions naturally, not as a form. Let the user answer in their own words and you'll structure the data.

### Section 1: Identity & Contact
Ask about:
- Full name
- Location (city, country)
- Phone, email, LinkedIn, GitHub
- Languages spoken (with proficiency levels)
- Current employment status
- Family/commute constraints (if any)

### Section 2: Education
For each degree:
- Level (PhD, MSc, BSc, etc.), field, institution, years
- Thesis topic (if applicable)
- Key coursework or topics

Also ask about certifications (online courses, professional certs).

### Section 3: Professional Experience
For each role (most recent first):
- Job title, company, dates, location
- Key responsibilities (3-5 bullets)
- Key achievements or projects
- Technologies/tools used

Also ask about independent projects, freelance work, or side projects.

### Section 4: Technical Skills
- Programming languages + proficiency level
- ML/AI frameworks and tools
- Domain expertise
- Software tools and platforms
- Any other technical skills

### Section 5: Publications & Awards (optional)
- Peer-reviewed papers, conference presentations
- Hackathons, competitions, awards
- Skip if not applicable

### Section 6: Behavioral Profile (optional)
If they have a formal assessment (PI, DISC, Myers-Briggs, StrengthsFinder):
- Ask them to describe or share the results

If not, ask behavioral questions:
- "What work environments do you thrive in?"
- "What drains your energy at work?"
- "How do you prefer to work in teams?"
- "How do you make decisions - quickly or deliberately?"
- "What's your communication style?"
- Synthesize answers into a behavioral profile

### Section 7: Career Goals & Preferences
- Target roles and industries
- What excites you in work
- Deal-breakers and must-haves
- Salary expectations/baseline (optional)
- What environments to avoid
- Commute/location constraints

### Section 8: References (optional)
For each reference:
- Name, title, company, email, phone
- Relationship to the user

### Section 9: Job Search Configuration
This section generates the search queries that power `/scrape`. Use the information from Sections 1, 4, and 7 to build targeted queries.

Ask about:
- **Role titles to search for:** "What job titles should I search for? For example: Data Scientist, ML Engineer, Geophysicist." Collect 3-8 specific titles.
- **Key skills as search terms:** "Which of your skills are most likely to appear in job postings?" Pick 3-5 that are distinctive and searchable.
- **Target companies (optional):** "Are there specific companies you'd like to monitor for openings?"
- **Geographic scope:** "Which cities or regions should I search in? How far are you willing to commute?" Use this to define the location filter tiers (ideal, acceptable, borderline, too far).
- **Job portals:** "The framework includes tools for Danish job portals (Jobindex, Jobbank, Jobdanmark, Jobnet). Are these the right ones for you, or do you use other sites?" Note: if the user is outside Denmark, acknowledge that the built-in CLI tools are Denmark-specific and suggest they can add their own portal integrations or rely on LinkedIn/Google site-searches.

**Important:** Also suggest role types the user may not have considered, based on their skill profile. For example:
- If they have strong Python + domain expertise: "Have you considered roles like 'Technical Consultant' or 'Solutions Engineer' in your domain?"
- If they have ML + a specific industry: "Companies in adjacent industries also hire for these skills. Should I include searches for [adjacent sector]?"
- If they have project management experience alongside technical skills: "Would you also want to search for 'Technical Project Manager' or 'Team Lead' roles?"

This proactive suggestion step helps users discover career paths they might not have considered.

---

## Step 3: Generate Profile Files

Once all information is collected (via either path), generate the following files:

### 1. Update `CLAUDE.md`
Replace all `[PLACEHOLDER]` tokens with the user's actual information. Keep the structure, workflow, and verification checklist intact.

### 2. Populate `01-candidate-profile.md`
Write the full candidate profile with structured sections: Identity, Education, Professional Experience, Independent Projects, Technical Skills, Publications, Awards, References.

### 3. Populate `02-behavioral-profile.md`
Write the behavioral profile based on assessment results or synthesized answers.

### 4. Update `04-job-evaluation.md`
Replace skill match areas with the user's actual skills:
- Strong match areas: [their primary skills]
- Moderate match areas: [their secondary skills]
- Weak match areas: [skills they lack]

Update career goals and motivation filters with their actual preferences.

### 5. Update `05-cv-templates.md`
Add role-specific profile statement templates based on their background.

### 6. Update `07-interview-prep.md`
Create STAR examples from their actual experience (at least 3-4 examples).

### 7. Update `cv/main_example.tex`
Replace placeholder personal data with their actual name, contact info, and add their education and most recent experience entries.

### 8. Generate `.claude/skills/job-scraper/search-queries.md`
Replace all placeholder tokens in the search queries file with the user's actual information from Section 9:
- Replace `[YOUR_PRIMARY_ROLE_TYPE]`, `[YOUR_PRIMARY_JOB_TITLE]`, etc. with actual role titles
- Replace `[YOUR_KEY_SKILL]`, `[YOUR_DOMAIN_KEYWORD_1]`, etc. with actual skills and domain terms
- Replace `[YOUR_CITY]`, `[YOUR_COUNTRY]`, `[YOUR_REGION]` with actual location
- Fill in the location filter tiers (ideal, acceptable, borderline, too far) based on commute constraints
- Organize queries into priority categories matching the user's career direction:
  - Priority 1: Their strongest/most desired role direction
  - Priority 2: Their domain expertise
  - Priority 3: Adjacent roles they could pivot into
  - Priority 4: Broader roles (wider net)

---

## Step 4: Confirm & Next Steps

Present a summary:

> **Setup complete!** Here's what was generated:
>
> - `CLAUDE.md` - Your full candidate profile
> - `.claude/skills/job-application-assistant/01-candidate-profile.md` - Structured profile
> - `.claude/skills/job-application-assistant/02-behavioral-profile.md` - Behavioral assessment
> - `.claude/skills/job-application-assistant/04-job-evaluation.md` - Personalized evaluation framework
> - `.claude/skills/job-application-assistant/05-cv-templates.md` - CV templates with your profile statements
> - `.claude/skills/job-application-assistant/07-interview-prep.md` - STAR examples from your experience
> - `cv/main_example.tex` - Your LaTeX CV template
> - `.claude/skills/job-scraper/search-queries.md` - Job search queries for `/scrape`
>
> **Try it out:**
> - Run `/scrape` to search for matching jobs right now
> - Run `/apply` with a job posting URL to see the full application workflow
> - Run `/setup --section search` later to update your search queries as your priorities evolve

---

## Design Principles

- Each section is a natural conversation, not a form
- The user can skip optional sections
- Synthesize answers into structured formats (the user doesn't need to know markdown or LaTeX)
- Can be re-run with `--section <name>` to update specific sections (e.g., `/setup --section search` to reconfigure job search queries without re-doing the full profile)
- Section 9 (search) proactively suggests role types the user may not have considered
- At the end, suggest running `/scrape` and `/apply` with a test job posting
