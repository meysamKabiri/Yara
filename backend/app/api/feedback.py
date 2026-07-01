from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import authenticated_user_id, get_current_user
from app.dependencies.database import DbSession
from app.models.core import Project
from app.schemas.feedback import InterpretationFeedbackCreate, InterpretationFeedbackRead
from app.services.interpretation_feedback import create_interpretation_feedback

router = APIRouter(
    prefix="/feedback",
    tags=["feedback"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/interpretation", response_model=InterpretationFeedbackRead)
def submit_interpretation_feedback(
    payload: InterpretationFeedbackCreate,
    db: DbSession,
) -> InterpretationFeedbackRead:
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.owner_id != authenticated_user_id():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project access forbidden")

    feedback = create_interpretation_feedback(
        db,
        project_id=payload.project_id,
        trace_id=payload.trace_id,
        raw_input=payload.raw_input,
        system_output=payload.system_output,
        user_final_state=payload.user_final_state,
        correction_source=payload.correction_source,
    )
    db.commit()
    db.refresh(feedback)
    return feedback
