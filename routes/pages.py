"""HTML page routes for the Job Board web interface."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from database.connection import settings

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")


@router.get("/", include_in_schema=False)
def home_page(request: Request):
    template = templates.env.get_template("index.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/jobs", include_in_schema=False)
def jobs_list_page(request: Request):
    template = templates.env.get_template("jobs.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/jobs/{job_id}", include_in_schema=False)
def job_detail_page(request: Request, job_id: str):
    template = templates.env.get_template("job_detail.html")
    content = template.render(request=request, job_id=job_id, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/login", include_in_schema=False)
def login_page(request: Request):
    template = templates.env.get_template("login.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/register", include_in_schema=False)
def register_page(request: Request):
    template = templates.env.get_template("register.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/profile", include_in_schema=False)
def profile_page(request: Request):
    template = templates.env.get_template("profile.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/post-job", include_in_schema=False)
def post_job_page(request: Request):
    template = templates.env.get_template("post_job.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/applications", include_in_schema=False)
def applications_page(request: Request):
    template = templates.env.get_template("applications.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/saved-jobs", include_in_schema=False)
def saved_jobs_page(request: Request):
    template = templates.env.get_template("saved_jobs.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/employers", include_in_schema=False)
def employers_page(request: Request):
    template = templates.env.get_template("employers.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/about", include_in_schema=False)
def about_page(request: Request):
    template = templates.env.get_template("about.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/terms-of-use", include_in_schema=False)
def terms_of_use_page(request: Request):
    template = templates.env.get_template("terms_of_use.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/privacy-policy", include_in_schema=False)
def privacy_policy_page(request: Request):
    template = templates.env.get_template("privacy_policy.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


# ── Admin Pages ──

@router.get("/admin/login", include_in_schema=False)
def admin_login_page(request: Request):
    template = templates.env.get_template("admin/admin_login.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/admin", include_in_schema=False)
def admin_dashboard_page(request: Request):
    template = templates.env.get_template("admin/dashboard.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/admin/users", include_in_schema=False)
def admin_users_page(request: Request):
    template = templates.env.get_template("admin/users.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/admin/users/{user_id}", include_in_schema=False)
def admin_user_detail_page(request: Request, user_id: str):
    template = templates.env.get_template("admin/user_detail.html")
    content = template.render(request=request, user_id=user_id, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/admin/jobs", include_in_schema=False)
def admin_jobs_page(request: Request):
    template = templates.env.get_template("admin/jobs.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/admin/jobs/{job_id}", include_in_schema=False)
def admin_job_detail_page(request: Request, job_id: str):
    template = templates.env.get_template("admin/job_detail.html")
    content = template.render(request=request, job_id=job_id, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/admin/applications", include_in_schema=False)
def admin_applications_page(request: Request):
    template = templates.env.get_template("admin/applications.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/admin/settings", include_in_schema=False)
def admin_settings_page(request: Request):
    template = templates.env.get_template("admin/settings.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


@router.get("/admin/logs", include_in_schema=False)
def admin_logs_page(request: Request):
    template = templates.env.get_template("admin/logs.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)
