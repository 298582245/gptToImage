from app import *  # noqa: F401,F403


def parse_page_params(default_per_page: int, allowed_per_page: tuple[int, ...]) -> tuple[int, int]:
    page = max(1, request.args.get("page", default=1, type=int) or 1)
    per_page = request.args.get("per_page", default=default_per_page, type=int) or default_per_page
    if per_page not in allowed_per_page:
        per_page = default_per_page
    return page, per_page


def pagination_meta(total: int, page: int, per_page: int) -> dict:
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, page), total_pages)
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }
