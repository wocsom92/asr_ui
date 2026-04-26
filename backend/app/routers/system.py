from fastapi import APIRouter

from app.__version__ import __version__

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/health")
async def health():
    return {"status": "ok", "version": __version__}
