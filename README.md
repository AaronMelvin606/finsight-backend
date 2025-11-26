# FinSight AI Backend

**The Operating System for Modern Finance**

FastAPI backend for FinSight AI - an FP&A automation platform that transforms finance teams from reactive reporters to proactive strategic partners.

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Neon PostgreSQL database (https://neon.tech)
- Git

### Local Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/finsight-backend.git
   cd finsight-backend
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your actual values
   ```

5. **Run database migrations:**
   ```bash
   alembic upgrade head
   ```

6. **Start the development server:**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

7. **View API documentation:**
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

## 📁 Project Structure

```
finsight-backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application entry point
│   ├── core/
│   │   ├── config.py        # Configuration settings
│   │   ├── database.py      # Database connection
│   │   └── security.py      # JWT authentication
│   ├── models/
│   │   ├── user.py          # User model
│   │   ├── organisation.py  # Organisation & membership models
│   │   ├── data_source.py   # Data source & financial record models
│   │   └── demo.py          # Demo access model
│   ├── schemas/
│   │   ├── auth.py          # Auth request/response schemas
│   │   ├── organisation.py  # Organisation schemas
│   │   └── demo.py          # Demo access schemas
│   ├── routers/
│   │   ├── auth.py          # Authentication endpoints
│   │   ├── users.py         # User management endpoints
│   │   ├── organisations.py # Organisation endpoints
│   │   ├── subscriptions.py # Stripe subscription endpoints
│   │   ├── dashboards.py    # Dashboard access endpoints
│   │   └── demo.py          # Demo access endpoints
│   └── services/            # Business logic services
├── alembic/
│   ├── env.py               # Alembic configuration
│   ├── script.py.mako       # Migration template
│   └── versions/            # Migration files
├── tests/                   # Test files
├── requirements.txt
├── .env.example
├── .gitignore
├── Dockerfile
├── railway.toml             # Railway deployment config
├── render.yaml              # Render deployment config
└── README.md
```

## 🔐 API Endpoints

### Authentication
- `POST /api/v1/auth/register` - Register new user
- `POST /api/v1/auth/login` - Login and get tokens
- `POST /api/v1/auth/refresh` - Refresh access token
- `POST /api/v1/auth/logout` - Logout
- `GET /api/v1/auth/me` - Get current user

### Users
- `GET /api/v1/users/me` - Get user profile
- `PATCH /api/v1/users/me` - Update profile
- `POST /api/v1/users/me/change-password` - Change password

### Organisations
- `GET /api/v1/organisations` - List user's organisations
- `POST /api/v1/organisations` - Create organisation
- `GET /api/v1/organisations/{id}` - Get organisation details
- `PATCH /api/v1/organisations/{id}` - Update organisation
- `GET /api/v1/organisations/{id}/members` - List members
- `GET /api/v1/organisations/{id}/subscription` - Get subscription info

### Subscriptions (Stripe)
- `GET /api/v1/subscriptions/plans` - List subscription plans
- `POST /api/v1/subscriptions/create-checkout-session` - Start checkout
- `POST /api/v1/subscriptions/create-portal-session` - Manage subscription
- `POST /api/v1/subscriptions/webhook` - Stripe webhook

### Dashboards
- `GET /api/v1/dashboards/available` - List available dashboards
- `GET /api/v1/dashboards/{id}` - Get dashboard info
- `GET /api/v1/dashboards/{id}/access` - Get dashboard access URL

### Demo Access
- `POST /api/v1/demo/request-access` - Request demo access (email-gated)
- `POST /api/v1/demo/verify-access` - Verify demo token
- `POST /api/v1/demo/contact` - Submit contact inquiry

## 💳 Subscription Tiers

| Tier | Price | Features |
|------|-------|----------|
| **Essentials** | £500/month | 5 core dashboards, CSV upload, 1 integration |
| **Professional** | £1,500/month | 12 dashboards, Tableau, AI insights, 3 integrations |
| **Enterprise** | £3,500/month | Unlimited dashboards, custom integrations, dedicated CSM |

## 🗄️ Database Schema

### Core Tables
- `users` - User accounts
- `organisations` - Multi-tenant organisations
- `organisation_members` - User-organisation relationships
- `data_sources` - CSV uploads and ERP connections
- `financial_records` - Financial data
- `demo_access` - Email-gated demo signups
- `contact_inquiries` - Contact form submissions

## 🚢 Deployment

### Railway (Recommended)

1. Create account at https://railway.app
2. Connect your GitHub repository
3. Add environment variables in Railway dashboard
4. Deploy!

```bash
# Environment variables to set:
DATABASE_URL=postgresql://...
SECRET_KEY=...
STRIPE_SECRET_KEY=...
FRONTEND_URL=https://www.finsightai.tech
```

### Render

1. Create account at https://render.com
2. Create new Web Service
3. Connect GitHub repository
4. Configure environment variables
5. Deploy!

### Docker

```bash
# Build image
docker build -t finsight-api .

# Run container
docker run -p 8000:8000 --env-file .env finsight-api
```

## 🔧 Development Commands

```bash
# Run development server
uvicorn app.main:app --reload

# Run tests
pytest

# Run tests with coverage
pytest --cov=app

# Format code
black app/
isort app/

# Type checking
mypy app/

# Generate new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```

## 🔒 Security

- JWT-based authentication
- Password hashing with bcrypt
- Row-Level Security (RLS) for multi-tenancy
- CORS configured for frontend domain
- Environment variables for secrets
- Non-root Docker user

## 📊 Monitoring

For production, consider adding:
- Sentry for error tracking
- Prometheus + Grafana for metrics
- CloudWatch/Datadog for logging

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## 📄 License

Copyright (c) 2025 FinSight AI Limited. All rights reserved.

## 📞 Support

- Website: https://www.finsightai.tech
- Email: hello@finsightai.tech
- Phone: +44 7960 984820

---

Built with ❤️ by Aaron Melvin, Founder of FinSight AI
