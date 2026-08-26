# Job Evaluation Framework

<!-- SETUP: Skill match areas and career goals are personalized by running /setup -->

## Scoring Dimensions

Evaluate each job posting against these five dimensions:

### 1. Technical Skills Match (0-100)
How well do the required/preferred skills align with the candidate's capabilities?

| Score | Meaning |
|-------|---------|
| 80-100 | Core requirements are primary skills |
| 60-79 | Most requirements match, 1-2 gaps that are learnable |
| 40-59 | Partial match, significant upskilling needed |
| 0-39 | Fundamental mismatch |

**Strong match areas:** Classical ML / ensemble modeling (RandomForest, XGBoost, gradient boosting, ensemble stacking, feature engineering) — see "Proficient" tier in `01-candidate-profile.md`
**Moderate match areas:** Python/SQL/R, core data science stack (Pandas/NumPy/Scikit-learn), deep learning frameworks (TensorFlow/PyTorch/Hugging Face), LLM/agent/RAG stack, forecasting/time-series, PySpark/Microsoft Fabric/Azure, Docker/Git/Power BI, Data Engineering & BI domain experience — see "Working Knowledge" tier in `01-candidate-profile.md`
**Weak match areas:** Anything listed only under "Familiar / Exposure" in `01-candidate-profile.md` (e.g. Kubernetes, Terraform, Snowflake/dbt, Computer Vision/MLOps/Graph Databases cluster, ESG reporting, SAP BW, Salesforce, A/B testing/uplift modelling) — coursework or brief exposure only, not applied experience

**Tier-weighted scoring guidance:** Cross-reference required/preferred skills against the proficiency tiers in `01-candidate-profile.md`. Matches against "Proficient" or "Working Knowledge" items support scores of 60+. If a posting's *core* requirements (not nice-to-haves) are met only by "Familiar / Exposure" tier items, cap this dimension around 40-50 even if the keyword overlap looks high — these represent conceptual exposure, not production experience, and overselling them invites interview follow-up questions the candidate can't back up. Note such cases explicitly in "Gaps to Address" rather than letting a keyword match inflate the score.

### 2. Experience Match (0-100)
Does work history align with what they're looking for?

| Score | Meaning |
|-------|---------|
| 80-100 | Direct experience in the same domain and role type |
| 60-79 | Related experience, transferable skills clear |
| 40-59 | Adjacent experience, would need to make the case |
| 0-39 | Unrelated experience |

<!-- SETUP: populate Strong/Moderate/Entry-level role-type match areas based on your actual experience -->
**Strong:** [ROLE TYPES where your professional experience directly matches]
**Moderate:** [ROLE TYPES with related/transferable experience]
**Entry-level:** [ROLE TYPES with academic exposure but limited professional experience]

### 3. Behavioral/Culture Fit (0-100)
Does the role and company culture match the behavioral profile?

| Score | Meaning |
|-------|---------|
| 80-100 | Culture strongly matches behavioral preferences |
| 60-79 | Mixed signals but mostly compatible |
| 40-59 | Some friction areas |
| 0-39 | Significant culture mismatch |

**Red flags to research:** Department disorganization, work dominated by maintenance over development, poor chemistry with leadership, culture mismatches. Check reviews, media coverage, LinkedIn connections, and network contacts for insider perspective.

### 4. Location & Logistics (Pass/Fail + Notes)
- Within commute range: PASS
- Remote with occasional office: PASS
- Requires relocation: FAIL (deal-breaker)
- Frequent international travel: FLAG (discuss with user)

### 5. Career Alignment & Motivation (0-100)
Does this role advance career goals and contain tasks that energize?

| Score | Meaning |
|-------|---------|
| 80-100 | Strongly aligned with career direction, clear growth path |
| 60-79 | Good role but only partially aligned with long-term goals |
| 40-59 | Decent job but doesn't build toward career goals |
| 0-39 | Dead end or backwards step |

<!-- SETUP: populate near/medium/long-term career goals based on your actual aspirations -->
**Career goals:**
- **Near-term (0–2 years):** [YOUR_NEAR_TERM_GOAL]
- **Medium-term (2–5 years):** [YOUR_MEDIUM_TERM_GOAL]
- **Long-term:** [YOUR_LONG_TERM_GOAL]

**Motivation filter:** Evaluate not just whether the candidate *can* do the tasks, but whether the tasks will *energize* them. Consider:
- Tasks that energize: building new things (pipelines, tools, systems), learning new technologies quickly, optimizing processes, solving real business problems that impact people's day-to-day work, LLM/AI development, anything with measurable efficiency gains
- Tasks that drain: pure maintenance with no development track, bureaucratic process without impact, repetitive work without intellectual challenge, environments that don't reward initiative
- Non-task factors: room for initiative and self-direction, culture of high standards (not just compliance), quality-first mentality, some degree of client or business impact visibility, no burnout culture

<!-- SETUP: populate your actual life-situation constraints -->
**Life situation alignment:** Consider personal constraints:
- **Security:** [YOUR_EMPLOYMENT_STATUS_AND_SALARY_FLOOR/TARGET]
- **Flexibility:** [YOUR_RELOCATION_TIERS]
- **Professional development:** [WHETHER GROWTH/TRAINING IS A PRIMARY MOTIVATOR FOR YOU]

### 6. Salary Benchmark (Optional)

If the salary lookup tool is configured (`salary_data.json` exists), look up the company:
```
python salary_lookup.py "<Company Name>" --json
```

If a city is known from the posting, add `--city "<City>"` to narrow results.

Present findings as:
```
### Salary Benchmark
| Metric | Value |
|--------|-------|
| [Category] index | XX.X (+/-X.X% vs baseline) |
| Overall index | XX.X (+/-X.X% vs baseline) |
```

Interpret results relative to the baseline defined in the data file's metadata. For index-based data, higher typically means above-market compensation.

If the salary tool is not configured, skip this section.

## Output Format

Present the evaluation as:

```
## Job Fit Evaluation: [Role] at [Company]

| Dimension | Score | Notes |
|-----------|-------|-------|
| Technical Skills | XX/100 | [brief note] |
| Experience Match | XX/100 | [brief note] |
| Behavioral Fit | XX/100 | [brief note] |
| Location | PASS/FAIL | [brief note] |
| Career Alignment | XX/100 | [brief note] |

**Overall Score: XX/100** (weighted average of scored dimensions)

### Verdict: [Strong Fit / Good Fit / Moderate Fit / Weak Fit / Poor Fit]

### Key Strengths for This Role
- [bullet points]

### Gaps to Address
- [bullet points]

### Recommendation
[1-2 sentences: apply/skip/apply with caveats]

### Company Research Checklist
- [ ] Checked company website (mission, values, recent news)
- [ ] Checked review sites (Glassdoor, Jobindex, etc.)
- [ ] Checked LinkedIn for team size, recent hires, connections
- [ ] Checked media for restructuring, growth, or workplace issues
- [ ] Identified network contacts who may know the team/manager
```

## Weighting
- Technical Skills: 30%
- Experience Match: 25%
- Behavioral Fit: 15%
- Career Alignment: 30%

(Location is pass/fail, not weighted)

## Thresholds
- **Strong Fit** (75+): Definitely apply, tailor everything
- **Good Fit** (60-74): Apply, address gaps in cover letter
- **Moderate Fit** (45-59): Consider carefully, discuss with user
- **Weak Fit** (30-44): Probably skip unless strategic reasons
- **Poor Fit** (<30): Skip

## Pre-Application: Call the Employer (Best Practice)

Before writing the application, consider whether the candidate should call the contact person listed in the posting. **Only call if there are substantive questions** - never call just to "be remembered."

### When to Suggest Calling
- The posting has unclear or ambiguous requirements
- It's unclear which competencies are essential vs. nice-to-have
- The role description is vague about day-to-day tasks
- There's a named contact person who invites questions

### Good Questions to Ask
- "What are the primary challenges in this role?"
- "How is time typically divided across the listed responsibilities?"
- "Which competencies are most critical for success in this position?"
- "What does success look like in the first 6-12 months?"

### Rules for the Call
- Prepare a 30-second "elevator pitch" about your background in case they ask
- The call's purpose is **gathering information**, not delivering a pitch
- Take notes - use what you learn to tailor the application
- Reference the conversation naturally in the cover letter ("After speaking with [name], I was especially drawn to...")
