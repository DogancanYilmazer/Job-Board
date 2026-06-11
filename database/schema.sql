CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    email VARCHAR UNIQUE NOT NULL,
    password TEXT NOT NULL DEFAULT 'NO_AUTH',
    full_name VARCHAR,
    phone VARCHAR,
    avatar_url TEXT,
    status VARCHAR DEFAULT 'ONBOARDING',
    onboarding_status VARCHAR DEFAULT 'IN_PROGRESS',
    preferred_locale VARCHAR DEFAULT 'tr',
    otp_secret TEXT,
    otp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    otp_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS otp_secret TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS otp_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS otp_verified BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_token TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS user_roles (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, role)
);

CREATE TABLE IF NOT EXISTS user_preferences (
    id UUID PRIMARY KEY,
    user_id UUID UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    hide_taken_jobs BOOLEAN DEFAULT FALSE,
    profile_visibility VARCHAR DEFAULT 'PUBLIC',
    notification_settings JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS onboarding_steps (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    step_key VARCHAR,
    status VARCHAR DEFAULT 'PENDING',
    data JSONB DEFAULT '{}'::jsonb,
    completed_at TIMESTAMPTZ,
    UNIQUE (user_id, step_key)
);

CREATE TABLE IF NOT EXISTS applicant_profiles (
    id UUID PRIMARY KEY,
    user_id UUID UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    headline VARCHAR,
    bio TEXT,
    city VARCHAR,
    country VARCHAR,
    expected_salary_min_minor INT,
    expected_salary_max_minor INT,
    currency VARCHAR DEFAULT 'EGP',
    cv_url TEXT,
    availability VARCHAR DEFAULT 'OPEN_TO_WORK',
    visibility VARCHAR DEFAULT 'PUBLIC',
    rating_avg NUMERIC DEFAULT 0,
    rating_count INT DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS employer_profiles (
    id UUID PRIMARY KEY,
    user_id UUID UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    display_name VARCHAR,
    company_name VARCHAR,
    website_url TEXT,
    bio TEXT,
    verification_status VARCHAR DEFAULT 'PENDING',
    rating_avg NUMERIC DEFAULT 0,
    rating_count INT DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS skills (
    id UUID PRIMARY KEY,
    canonical_name VARCHAR UNIQUE,
    normalized_name VARCHAR UNIQUE,
    category VARCHAR,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS skill_aliases (
    id UUID PRIMARY KEY,
    skill_id UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    alias VARCHAR,
    normalized_alias VARCHAR UNIQUE
);

CREATE TABLE IF NOT EXISTS applicant_skills (
    id UUID PRIMARY KEY,
    applicant_profile_id UUID NOT NULL REFERENCES applicant_profiles(id) ON DELETE CASCADE,
    skill_id UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    proficiency_level INT DEFAULT 1,
    years_experience NUMERIC DEFAULT 0,
    verified BOOLEAN DEFAULT FALSE,
    UNIQUE (applicant_profile_id, skill_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY,
    owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    employer_profile_id UUID NOT NULL REFERENCES employer_profiles(id) ON DELETE CASCADE,
    title VARCHAR,
    description TEXT,
    country VARCHAR,
    city VARCHAR,
    area VARCHAR,
    remote_allowed BOOLEAN DEFAULT FALSE,
    workplace_type VARCHAR,
    job_type VARCHAR,
    career_level VARCHAR,
    salary_min_minor INT,
    salary_max_minor INT,
    currency VARCHAR DEFAULT 'EGP',
    salary_period VARCHAR DEFAULT 'PROJECT',
    price_negotiable BOOLEAN DEFAULT TRUE,
    status VARCHAR DEFAULT 'DRAFT',
    visibility VARCHAR DEFAULT 'PUBLIC',
    taken_visibility VARCHAR DEFAULT 'SHOW_TAKEN_ONLY',
    published_at TIMESTAMPTZ,
    closes_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS job_required_skills (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    skill_id UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    importance_weight INT DEFAULT 1,
    required_level INT DEFAULT 1,
    must_have BOOLEAN DEFAULT FALSE,
    UNIQUE (job_id, skill_id)
);

CREATE TABLE IF NOT EXISTS applications (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    applicant_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    applicant_profile_id UUID NOT NULL REFERENCES applicant_profiles(id) ON DELETE CASCADE,
    cover_letter TEXT,
    proposed_amount_minor INT,
    proposed_currency VARCHAR,
    status VARCHAR DEFAULT 'APPLIED',
    match_score INT DEFAULT 0,
    match_snapshot JSONB DEFAULT '{}'::jsonb,
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (job_id, applicant_user_id)
);

CREATE TABLE IF NOT EXISTS application_status_history (
    id UUID PRIMARY KEY,
    application_id UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    from_status VARCHAR,
    to_status VARCHAR,
    changed_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS job_status_history (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    from_status VARCHAR,
    to_status VARCHAR,
    changed_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS price_proposals (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    application_id UUID REFERENCES applications(id) ON DELETE SET NULL,
    proposer_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    receiver_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    amount_minor INT,
    currency VARCHAR,
    message TEXT,
    status VARCHAR DEFAULT 'PENDING',
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS offers (
    id UUID PRIMARY KEY,
    application_id UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    owner_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    applicant_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    amount_minor INT,
    currency VARCHAR,
    terms TEXT,
    status VARCHAR DEFAULT 'PENDING',
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contracts (
    id UUID PRIMARY KEY,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    application_id UUID REFERENCES applications(id) ON DELETE SET NULL,
    offer_id UUID REFERENCES offers(id) ON DELETE SET NULL,
    owner_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    worker_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    agreed_amount_minor INT,
    currency VARCHAR,
    escrow_status VARCHAR DEFAULT 'NOT_FUNDED',
    status VARCHAR DEFAULT 'PENDING_ESCROW',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS job_assignments (
    id UUID PRIMARY KEY,
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    application_id UUID REFERENCES applications(id) ON DELETE SET NULL,
    contract_id UUID REFERENCES contracts(id) ON DELETE SET NULL,
    assigned_to_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    status VARCHAR DEFAULT 'ASSIGNED',
    visibility VARCHAR DEFAULT 'SHOW_TAKEN_ONLY',
    assigned_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payment_ledger (
    id UUID PRIMARY KEY,
    contract_id UUID REFERENCES contracts(id) ON DELETE CASCADE,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    counterparty_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    type VARCHAR,
    amount_minor INT,
    currency VARCHAR,
    status VARCHAR DEFAULT 'SUCCEEDED',
    provider VARCHAR DEFAULT 'demo',
    provider_reference VARCHAR,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cancellations (
    id UUID PRIMARY KEY,
    contract_id UUID REFERENCES contracts(id) ON DELETE CASCADE,
    requested_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    requested_by_role VARCHAR,
    reason TEXT,
    refund_to_owner_minor INT,
    payout_to_worker_minor INT,
    platform_fee_minor INT DEFAULT 0,
    policy_snapshot JSONB DEFAULT '{}'::jsonb,
    status VARCHAR DEFAULT 'DONE',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- job_conversations moved to MongoDB (conversations collection)

CREATE TABLE IF NOT EXISTS ratings (
    id UUID PRIMARY KEY,
    contract_id UUID REFERENCES contracts(id) ON DELETE CASCADE,
    rater_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    ratee_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    rating INT CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    role_context VARCHAR,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (contract_id, rater_user_id, ratee_user_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_location_status ON jobs (country, city, status);
CREATE INDEX IF NOT EXISTS idx_jobs_type_workplace ON jobs (job_type, workplace_type);
CREATE INDEX IF NOT EXISTS idx_jobs_salary_range ON jobs (currency, salary_min_minor, salary_max_minor);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_required_skills_job ON job_required_skills (job_id);
CREATE INDEX IF NOT EXISTS idx_job_required_skills_skill ON job_required_skills (skill_id);
CREATE INDEX IF NOT EXISTS idx_applications_job_status ON applications (job_id, status);
-- idx_conversations_participants removed (conversations moved to MongoDB)

-- Admin panel support
ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS site_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_name VARCHAR DEFAULT 'JobBoard',
    logo_url TEXT,
    contact_email VARCHAR,
    contact_phone VARCHAR,
    default_country VARCHAR DEFAULT 'TR',
    default_phone_code VARCHAR DEFAULT '+90',
    terms_url TEXT,
    privacy_url TEXT,
    email_notifications_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_activity_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action_type VARCHAR NOT NULL,
    target_type VARCHAR,
    target_id VARCHAR,
    description TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_logs_admin ON admin_activity_logs (admin_user_id);
CREATE INDEX IF NOT EXISTS idx_admin_logs_created ON admin_activity_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_blocked ON users (is_blocked) WHERE is_blocked = TRUE;
