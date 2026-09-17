# TalentMatch

TalentMatch is a local AI-assisted recruitment screening application. It extracts a job description from PDF, reads candidates from a CSV export and/or resume PDFs, ranks candidates against the job, and displays results in a React dashboard.

The project also includes an ATS converter that turns candidate CSV rows into clean, searchable PDF resumes.

## Features

- Job Description PDF extraction with pdfplumber, PyPDF2, and Groq/LLaMA.
- Candidate input from a Google Forms-style CSV, resume PDFs, or both.
- Resume rendering and OCR with PyMuPDF and EasyOCR.
- Online Hugging Face model loading; no local sentence-transformer folder is required.
- Resume category classification with SwaKyxd/resume-analyser-bert.
- Semantic matching with sentence-transformers/all-mpnet-base-v2.
- Fuzzy skill matching and structured keyword scoring.
- Nine-criterion RMFL scoring with learned role-specific weights.
- Optional GitHub, LinkedIn, and personal-site portfolio enrichment. GitHub profiles are enriched from every accessible public repository README and reduced into one combined profile summary.
- Candidate rankings show whether portfolio output was generated, empty and requiring human review, not processed, or not provided; empty results retain a direct link and extraction error for manual checking.
- Dashboard, candidate details, JD management, and analytics.
- Pipeline Analytics includes total-score leaders, match distributions, skill coverage, category mix, portfolio-output health, and a direct human-review queue for empty portfolio results.
- ATS PDF batch generation from candidate CSV data.
- Hiring-feedback endpoints for updating and auditing the RMFL policy.

## Project layout

The backend and frontend live in the same repository root.

~~~text
talent-match/
|-- main.py                    FastAPI application and ranking pipeline
|-- ats_converter.py           CSV-to-ATS-PDF generator
|-- requirements.txt           Python dependencies
|-- package.json               Frontend dependencies and scripts
|-- src/
|   |-- components/            React UI components
|   |-- pages/Index.tsx        Dashboard and view routing
|   |-- lib/api.ts             FastAPI client
|   |-- lib/types.ts           API and UI types
|   `-- assets/                Frontend assets
|-- models/                    Optional models and RMFL checkpoint
|-- ocr_output/                OCR working output
`-- output/pdf/                Generated PDF examples
~~~

## Processing flow

~~~text
JD PDF ------------------------------> PDF text extraction -> Groq structured JD

Candidate CSV -----------------------+
Resume PDFs -> PyMuPDF -> EasyOCR ---+--> normalized candidate records
Portfolio URLs -> web/GitHub --------+--> optional skill enrichment

JD + candidates
    -> BERT category classification
    -> SBERT semantic similarity
    -> fuzzy skill and keyword matching
    -> nine RMFL criteria and learned weights
    -> final score and ranked candidates
    -> React dashboard and analytics
~~~

The ATS workflow is independent of candidate ranking:

~~~text
Candidate CSV -> header mapping -> ATS sections -> ReportLab PDFs -> ZIP download
~~~

## Prerequisites

- Python 3.10 or newer. Python 3.13 is used by the current local environment.
- Node.js 18 or newer.
- Internet access for first-time model downloads.
- A Groq API key for JD extraction.
- Ollama running locally with `qwen2.5:7b` for portfolio and GitHub README analysis.

The ATS converter does not call Groq, but the FastAPI application initializes the SBERT model when the server starts.

Install and prepare the default local portfolio model:

~~~powershell
ollama pull qwen2.5:7b
ollama list
~~~

The Ollama desktop application normally starts the local service automatically. If it is not running, start it with `ollama serve` before launching the backend.

## Installation

Run commands from the repository root, where main.py and package.json are located.

### Python environment

Windows PowerShell:

~~~powershell
py -3.13 -m venv backend_env
.ackend_envScriptspython.exe -m pip install --upgrade pip
.ackend_envScriptspython.exe -m pip install -r requirements.txt
~~~

macOS/Linux:

~~~bash
python3 -m venv backend_env
./backend_env/bin/python -m pip install --upgrade pip
./backend_env/bin/python -m pip install -r requirements.txt
~~~

### OneDrive warning

Virtual environments inside a OneDrive-synchronized project can become slow or return errors such as OSError: [Errno 22] Invalid argument while importing packages.

If that happens, create the environment outside OneDrive:

~~~powershell
py -3.13 -m venv "$env:LOCALAPPDATAenvs	alent-match"
& "$env:LOCALAPPDATAenvs	alent-matchScriptspython.exe" -m pip install --upgrade pip
& "$env:LOCALAPPDATAenvs	alent-matchScriptspython.exe" -m pip install -r requirements.txt
~~~

Use that environment's Python executable in the backend commands below.

### Environment variables

Required for AI extraction and ranking:

~~~powershell
$env:GROQ_API_KEY="your_groq_api_key"
~~~

Optional backend variables:

| Variable | Default | Purpose |
|---|---|---|
| SBERT_MODEL_ID | sentence-transformers/all-mpnet-base-v2 | Hugging Face model ID or compatible model location |
| NER_MODEL_PATH | C:\PROJECTS\models\ner | Optional spaCy NER model directory |
| GROQ_MODEL | openai/gpt-oss-20b | Groq model for JD extraction |
| OLLAMA_BASE_URL | http://127.0.0.1:11434 | Local Ollama API used for portfolio analysis |
| OLLAMA_MODEL | qwen2.5:7b | Installed Ollama model for portfolio and GitHub README summaries |

The NER model is optional. The backend logs a warning and continues without NER enrichment when the directory does not exist.

Variables may also be stored in .env when Uvicorn is started with --env-file .env.

### Start the backend

Using the repository environment:

~~~powershell
.ackend_envScriptspython.exe -m uvicorn main:app --reload --port 8000
~~~

Using an environment outside OneDrive:

~~~powershell
& "$env:LOCALAPPDATAenvs	alent-matchScriptspython.exe" -m uvicorn main:app --reload --port 8000
~~~

Backend URLs:

- API: http://127.0.0.1:8000
- Interactive documentation: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

The first startup can be slow because SBERT downloads all-mpnet-base-v2. BERT downloads when a model-dependent route is first called or /load-models is called. EasyOCR downloads its English recognition weights the first time resume OCR runs.

### Start the frontend

~~~powershell
npm install
npm run dev
~~~

The frontend normally runs at http://localhost:5173.

To use a different backend, set:

~~~text
VITE_API_BASE=http://127.0.0.1:8000
~~~

## User workflows

### Rank candidates against a JD

1. Open **Upload Files**.
2. Select one or more JD PDFs.
3. Add candidate data using a CSV, resume PDFs, or both.
4. Optionally enable portfolio scraping.
5. Select **Process & Rank Candidates**.
6. Review results in Dashboard, Candidates, and Analytics.

The frontend can store multiple extracted JDs. The current ranking request uses the first selected JD file; multi-JD ranking is not yet performed independently by the backend.

### Rank resume PDFs

For each uploaded candidate PDF, the backend:

1. renders each page with PyMuPDF;
2. runs English EasyOCR;
3. extracts likely name, email, phone, portfolio URL, skills, and resume text;
4. passes the record into the normal JD ranking pipeline.

Text-based and scanned PDFs both use this OCR path.

### Convert candidate CSV data to ATS PDFs

1. Open **ATS Converter**.
2. Upload a candidate CSV.
3. Select **Convert and Download PDFs**.
4. The browser downloads ats_cv_pdfs.zip.

Each candidate row becomes one searchable, single-column PDF. Duplicate candidate names receive numbered filenames.

Recognized ATS data groups:

| Section | Typical headers |
|---|---|
| Identity | Full Name, Email Address, Phone Number |
| Address | Present Address, Division |
| Work experience | Designation, Organization, Starting Date, Ending Date, Job Description |
| Education | University, Subject, Major, Year, CGPA |
| Skills | Technical, Digital, Language, Soft Skills |
| Certifications | Certification/Course Name, Start Date, Duration |
| Training | Training Name, Organization, Duration |
| Additional | Area of Interest, Gender, Date of Birth, Age, Nationality, Portfolio |

Numbered headers ending in 2 or 3 map to later work, education, certification, or training entries.

## Candidate CSV behavior

The ranking pipeline uses common aliases instead of requiring one exact schema.

- Candidate ID: email, candidate ID, ID, or row number.
- Name: Name, Full Name, Candidate Name, First Name, or Last Name.
- Resume text: Resume, CV, CV Text, Resume Text, Cover Letter, Summary, Profile, About, or Bio.
- Skills: recognized technical-skills column, otherwise extracted from resume text.
- Portfolio: Portfolio, GitHub, Website, LinkedIn, Link, or URL.

When no resume-text column exists, the backend joins all non-empty row values into a candidate profile.

## Ranking method

Each candidate receives these signals:

- BERT resume category and confidence.
- SBERT similarity between JD and candidate text.
- RapidFuzz skill match percentage.
- Weighted keyword coverage over structured fields.
- Optional portfolio skills.
- Priority boost from relevant structured fields.
- Nine RMFL criteria:
  - relevant background;
  - results and achievements;
  - relevant courses;
  - training and certification;
  - relevant skills;
  - work experience;
  - projects and coursework;
  - thesis and publications;
  - portfolio.

The RMFL policy generates role-specific criterion weights. The current final score is:

~~~text
50% RMFL criteria total
30% SBERT semantic match
20% blended technical score

blended technical score =
    60% fuzzy skill match
    40% keyword score
~~~

A small priority boost is added afterwards. Candidates are sorted by total_score.

The semantic_weight and tech_weight form fields are accepted and returned for compatibility, but the current final-score calculation uses the fixed formula above.

## API reference

File endpoints use multipart/form-data unless stated otherwise.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | / | API metadata |
| GET | /health | Model and RMFL status |
| POST | /load-models | Preload BERT, Groq, optional NER, and the RMFL checkpoint |
| POST | /extract-jd | Extract structured fields from a JD PDF |
| POST | /rank-cvs | Rank CSV candidates and/or resume PDFs against a JD |
| POST | /extract-portfolio | Analyze one portfolio URL |
| POST | /convert-ats-cvs | Convert candidate CSV rows into a ZIP of ATS PDFs |
| POST | /feedback | Submit JSON hiring outcomes to train RMFL |
| GET | /rmfl-weights | Inspect learned weights for a role |
| POST | /skill-match | Run standalone fuzzy skill matching |
| GET | /categories | Return supported resume categories |
| POST | /search-cvs | Search a candidate CSV with semantic and keyword relevance |

### POST /rank-cvs

| Field | Type | Required | Description |
|---|---|---|---|
| jd_file | PDF | Yes | Job Description |
| cv_file | CSV | No | Candidate CSV |
| resume_files | PDF list | No | Candidate resume PDFs |
| extract_portfolios | boolean | No | Scrape detected portfolio URLs |
| semantic_weight | float | No | Compatibility response field |
| tech_weight | float | No | Compatibility response field |

At least one of cv_file or resume_files is required.

The response includes:

- JD title and skills;
- candidate and portfolio counts;
- full and compact ranking records;
- category, semantic, skill, keyword, and final scores;
- matched and missing skills;
- RMFL criteria, weights, contributions, and entropy;
- optional portfolio details.

### POST /convert-ats-cvs

| Field | Type | Required |
|---|---|---|
| file | CSV | Yes |

Returns application/zip with one ATS PDF per row. The X-Generated-Count header contains the generated PDF count.

### POST /feedback

This endpoint accepts JSON. Supported outcomes:

- hired
- shortlisted
- screened_out
- rejected

Feedback updates the replay buffer and policy, then saves models/rmfl_weights.pt.

## Frontend views

| View | Purpose |
|---|---|
| Dashboard | JD overview, metrics, and selected-JD rankings |
| Job Descriptions | Stored JD cards and candidate counts |
| Candidates | Ranked candidates with JD filters |
| Analytics | Scores, categories, skill gaps, and candidate charts |
| Upload Files | JD, CSV, and resume PDF workflow |
| ATS Converter | Candidate CSV to ATS PDF ZIP conversion |
| Settings | Placeholder for future configuration |

JD and candidate results are stored in browser localStorage, not a database.

## Configuration

Important main.py constants:

~~~python
MAX_CHARS_JD = 4000
MAX_CHARS_CV = 2000
MAX_CHARS_WEB = 3000

SEMANTIC_WEIGHT = 0.7
TECH_WEIGHT = 0.3
~~~

RMFL learning rate, replay capacity, entropy coefficient, and weight floor are also defined near the top of main.py.

## Development commands

Frontend:

~~~powershell
npm run dev
npm run build
npm run lint
npm run test
~~~

Backend syntax check:

~~~powershell
.ackend_envScriptspython.exe -m py_compile main.py ats_converter.py
~~~

Validate requirements without installing:

~~~powershell
.ackend_envScriptspython.exe -m pip install --dry-run -r requirements.txt
~~~

## Troubleshooting

### ATS PDF dependencies are unavailable

Confirm that the Python executable used for Uvicorn can import ReportLab:

~~~powershell
.ackend_envScriptspython.exe -c "import reportlab; print(reportlab.Version)"
~~~

Install it if missing:

~~~powershell
.ackend_envScriptspython.exe -m pip install reportlab
~~~

If it is installed but import hangs or raises Windows Errno 22, recreate the environment outside OneDrive.

### Sentence-transformer path not found

The current code uses sentence-transformers/all-mpnet-base-v2 and downloads it from Hugging Face. The old C:\PROJECTS\models\sentence_trasnformers path is no longer used.

### NER model not found

This warning is non-fatal. Set NER_MODEL_PATH to a valid spaCy model directory only if NER enrichment is required.

### Groq key error

Set GROQ_API_KEY in the terminal that starts Uvicorn, or use:

~~~powershell
.ackend_envScriptspython.exe -m uvicorn main:app --reload --port 8000 --env-file .env
~~~

### Slow first request

Model downloads and initialization may take several minutes on the first run. Later runs reuse the Hugging Face and EasyOCR caches.

## Known limitations

- No authentication or authorization.
- Results persist in browser localStorage instead of a database.
- The frontend accepts multiple JD PDFs, but ranking currently uses only the first.
- EasyOCR is configured for English only.
- Portfolio scraping is sequential and can be slow. GitHub extraction uses the unauthenticated public API only, so GitHub rate limits may affect very large batches.
- Local portfolio summarization requires Ollama to remain running and can be slower without GPU acceleration.
- LinkedIn commonly blocks automated scraping.
- ATS conversion requires recognizable CSV headers and does not parse arbitrary existing DOCX/PDF layouts.
- SBERT initializes during backend import, including for non-ranking routes.
- The default NER path is machine-specific, but NER is optional.

## Technology stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python |
| Classification | Hugging Face Transformers, BERT |
| Embeddings | sentence-transformers, MPNet |
| OCR and PDF parsing | EasyOCR, PyMuPDF, pdfplumber, PyPDF2 |
| ATS PDF generation | ReportLab |
| Ranking | PyTorch, RapidFuzz, RMFL policy |
| LLM | Groq for JD extraction; local Ollama with Qwen 2.5 7B for portfolios |
| Data processing | pandas, NumPy, scikit-learn, NLTK, Gensim |
| Portfolio extraction | requests, BeautifulSoup |
| Frontend | React, TypeScript, Vite |
| UI | Tailwind CSS, shadcn/ui, Lucide |
| Charts | Recharts |
| Data fetching | TanStack Query |

## License

No license file is currently included. Add one before distributing the project publicly.
