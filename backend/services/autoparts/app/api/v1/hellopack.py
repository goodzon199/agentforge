from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.hellopack import HelloPackService
from app.models import User

router = APIRouter(prefix="/hellopack", tags=["hellopack"])


@router.get("/hello")
def hello(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Demo endpoint: greets the caller's company."""
    company_id = user.company_id
    return {"message": HelloPackService(db).greet(company_id)}
