from fastapi import APIRouter, Query
from .query import get_concept, get_customer_profile, search_concepts, get_pages_by_tag
from .compiler import compile_all

router = APIRouter(prefix="/api/wiki", tags=["wiki"])

@router.get("/pages/{slug}")
def api_get_page(slug: str):
    page = get_concept(slug) or get_customer_profile(slug)
    if not page:
        return {"mode": "not_found", "slug": slug}
    return {"mode": "ok", "data": page}

@router.get("/search")
def api_search(keyword: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)):
    results = search_concepts(keyword, limit)
    return {"mode": "ok", "results": results, "count": len(results)}

@router.get("/by-tag/{tag}")
def api_by_tag(tag: str, limit: int = Query(20, ge=1, le=100)):
    results = get_pages_by_tag(tag, limit)
    return {"mode": "ok", "results": results, "count": len(results)}

@router.get("/customer/{customer_id}")
def api_customer_profile(customer_id: str):
    profile = get_customer_profile(customer_id)
    if not profile:
        return {"mode": "not_found", "customer_id": customer_id}
    return {"mode": "ok", "data": profile}

@router.post("/compile")
def api_compile():
    result = compile_all()
    return {"mode": "ok", **result}
