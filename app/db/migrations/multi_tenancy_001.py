"""
Multi-tenancy database migration
Creates organisations table and updates existing tables for tenant isolation
"""

from sqlalchemy import text
from app.core.database import engine


async def run_migration():
    """Run the multi-tenancy migration"""

    async with engine.begin() as conn:
        # Create organisations table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS organisations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(255) NOT NULL,
                slug VARCHAR(100) UNIQUE NOT NULL,
                subscription_tier VARCHAR(50) DEFAULT 'essentials',
                max_users INTEGER DEFAULT 3,
                settings JSONB DEFAULT '{}',
                is_active BOOLEAN DEFAULT true,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """))

        # Create index on slug for fast lookups
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_organisations_slug
            ON organisations(slug);
        """))

        # Add organisation_id to users table if not exists
        await conn.execute(text("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS organisation_id UUID REFERENCES organisations(id);
        """))

        # Add role column to users if not exists
        await conn.execute(text("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'member';
        """))

        # Create index on users.organisation_id
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_users_organisation_id
            ON users(organisation_id);
        """))

        # Create financial_data table for storing uploaded financial data
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS financial_data (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organisation_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
                period_date DATE NOT NULL,
                period_type VARCHAR(20) DEFAULT 'monthly',
                account_category VARCHAR(100) NOT NULL,
                account_name VARCHAR(255) NOT NULL,
                actual_amount DECIMAL(15, 2) DEFAULT 0,
                budget_amount DECIMAL(15, 2) DEFAULT 0,
                prior_year_amount DECIMAL(15, 2) DEFAULT 0,
                variance_amount DECIMAL(15, 2) GENERATED ALWAYS AS (actual_amount - budget_amount) STORED,
                variance_percent DECIMAL(10, 4),
                notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE(organisation_id, period_date, account_category, account_name)
            );
        """))

        # Create indexes for financial_data
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_financial_data_org_id
            ON financial_data(organisation_id);
        """))

        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_financial_data_period
            ON financial_data(organisation_id, period_date);
        """))

        # Create data_uploads table to track file uploads
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS data_uploads (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organisation_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
                uploaded_by UUID NOT NULL REFERENCES users(id),
                filename VARCHAR(255) NOT NULL,
                file_type VARCHAR(50) NOT NULL,
                file_size_bytes INTEGER,
                row_count INTEGER DEFAULT 0,
                status VARCHAR(50) DEFAULT 'pending',
                error_message TEXT,
                processing_started_at TIMESTAMP WITH TIME ZONE,
                processing_completed_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """))

        # Create index for uploads
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_data_uploads_org_id
            ON data_uploads(organisation_id);
        """))

        # Create kpi_metrics table for dashboard KPIs
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS kpi_metrics (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organisation_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
                metric_date DATE NOT NULL,
                metric_name VARCHAR(100) NOT NULL,
                metric_value DECIMAL(15, 4),
                metric_unit VARCHAR(50),
                target_value DECIMAL(15, 4),
                prior_period_value DECIMAL(15, 4),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE(organisation_id, metric_date, metric_name)
            );
        """))

        # Create index for KPIs
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_kpi_metrics_org_id
            ON kpi_metrics(organisation_id);
        """))

        print("✅ Multi-tenancy migration completed successfully!")


async def rollback_migration():
    """Rollback the migration (use with caution!)"""

    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS kpi_metrics CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS data_uploads CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS financial_data CASCADE;"))
        await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS organisation_id;"))
        await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS role;"))
        await conn.execute(text("DROP TABLE IF EXISTS organisations CASCADE;"))

        print("⚠️ Multi-tenancy migration rolled back!")
