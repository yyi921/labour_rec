# Labour Reconciliation System

## Overview
POC system that reconciles labour costs between Tanda timesheets, Micropay IQB, and Micropay Journal, then exports to Sage Intacct.

## Setup

### Prerequisites
- Python 3.10+
- PostgreSQL (for production)

### Installation

1. Clone repository
2. Create virtual environment:
```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
   pip install -r requirements.txt
```

4. Run migrations:
```bash
   python manage.py migrate
```

5. Create superuser:
```bash
   python manage.py createsuperuser
```

6. Load reference data:
```bash
   python manage.py load_reference_data
```

7. Run development server:
```bash
   python manage.py runserver
```

## Project Structure
```
labour_reconciliation/
├── config/              # Django project settings
├── reconciliation/      # Main app
│   ├── models.py       # Database models
│   ├── views/          # API views
│   ├── management/     # Management commands
│   └── admin.py        # Admin interface
├── templates/          # HTML templates
├── media/              # Uploaded files
├── data/               # Reference data (Split_Data.csv)
└── manage.py
```

## Features (Phase 1)

- [x] Smart file upload with auto-detection
- [x] Database models and migrations
- [x] Reference data loading
- [ ] File parsing (Tanda, IQB, Journal)
- [ ] Three-way reconciliation
- [ ] Exception detection
- [ ] Chat-based resolution
- [ ] Dashboard UI
- [ ] Sage Intacct export
- [ ] Labour cost reports

## Development Timeline

- **Week 1**: Core reconciliation engine
- **Week 2**: UI, chat resolution, exports
- **Demo**: November 30, 2025

## API Endpoints (Coming Soon)

- `POST /api/uploads/smart` - Smart file upload
- `GET /api/periods/` - List pay periods
- `POST /api/periods/{id}/reconcile/` - Trigger reconciliation
- `GET /api/periods/{id}/exceptions/` - List exceptions
- `POST /api/exceptions/{id}/chat-resolve/` - Chat resolution

## Environment Variables

See `.env.example` for required environment variables.

## License

Internal use only.
```

### ✅ Day 1 Afternoon Complete!

You now have:
- ✅ Management command for loading reference data
- ✅ Split_Data.csv loaded (90+ records)
- ✅ Directory structure for uploads and exports
- ✅ Environment variables configured
- ✅ Git ignore file
- ✅ URL structure set up
- ✅ Database verified working
- ✅ Project documentation

### Current Project Status
```
labour_reconciliation/
├── venv/
├── config/
│   ├── __init__.py
│   ├── settings.py ✅
│   ├── urls.py ✅
│   ├── asgi.py
│   └── wsgi.py
├── reconciliation/
│   ├── __init__.py
│   ├── admin.py ✅
│   ├── apps.py
│   ├── models.py ✅
│   ├── urls.py ✅
│   ├── views/
│   │   └── __init__.py
│   └── management/
│       ├── __init__.py
│       └── commands/
│           ├── __init__.py
│           └── load_reference_data.py ✅
├── templates/
├── static/
├── media/
│   ├── uploads/
│   ├── temp/
│   └── exports/
├── data/
│   └── Split_Data.csv ✅
├── manage.py
├── requirements.txt ✅
├── .env ✅
├── .gitignore ✅
├── README.md ✅
└── db.sqlite3 ✅