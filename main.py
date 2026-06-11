from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager

from database.connection import database, initialize_database, settings
from routes import applications, auth, jobs, mongo_features, negotiations, profiles, skills, users, pages, admin

@asynccontextmanager
async def lifespan(app: FastAPI):
    database.connect()
    initialize_database()
    try:
        yield
    finally:
        database.close()


app = FastAPI(title="Job Board API", version="1.0.0", lifespan=lifespan)

# Templates
templates = Jinja2Templates(directory="templates")
# Add app-wide template globals to avoid passing complex objects in context
templates.env.globals["base_url"] = settings.API_PREFIX

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")



@app.exception_handler(HTTPException)
def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and "errors" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "data": None,
            "meta": {},
            "errors": [{"code": "HTTP_ERROR", "message": str(exc.detail)}],
        },
    )


@app.exception_handler(RequestValidationError)
def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        errors.append(
            {
                "code": "VALIDATION_ERROR",
                "message": error.get("msg", "Validation error"),
                "field": ".".join(str(item) for item in error.get("loc", [])),
            }
        )
    return JSONResponse(
        status_code=422,
        content={"data": None, "meta": {}, "errors": errors},
    )


@app.get("/")
def root(request: Request):
    template = templates.env.get_template("index.html")
    content = template.render(request=request, base_url=settings.API_PREFIX)
    return HTMLResponse(content)


app.include_router(users.router, prefix=settings.API_PREFIX)
app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(profiles.router, prefix=settings.API_PREFIX)
app.include_router(skills.router, prefix=settings.API_PREFIX)
app.include_router(jobs.router, prefix=settings.API_PREFIX)
app.include_router(applications.router, prefix=settings.API_PREFIX)
app.include_router(mongo_features.router, prefix=settings.API_PREFIX)
app.include_router(negotiations.router, prefix=settings.API_PREFIX)
app.include_router(pages.router)
app.include_router(admin.router, prefix=settings.API_PREFIX)
