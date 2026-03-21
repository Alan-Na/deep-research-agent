from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.graph import create_research_graph
from app.schemas import AnalyzeRequest, CompanyIdentifiers, FinalReport
from app.utils.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)
app = FastAPI(title="Company Deep Research Agent", version="0.1.0")
graph = create_research_graph()
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def user_dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/developer", include_in_schema=False)
def developer_dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "developer.html")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze", response_model=FinalReport)
def analyze_company(request: AnalyzeRequest) -> FinalReport:
    try:
        result = graph.invoke(
            {
                "company_name": request.company_name,
                "identifiers": CompanyIdentifiers(),
                "module_results": {},
                "evidence_cards": [],
                "warnings": [],
                "errors": [],
            }
        )
        final_report = result.get("final_report")
        if final_report is None:
            raise RuntimeError("Graph execution finished without final_report.")
        return FinalReport.model_validate(final_report)
    except Exception as exc:
        logger.exception("Analyze endpoint failed.")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
