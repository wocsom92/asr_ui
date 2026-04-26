import shutil
from pathlib import Path

from app.config import settings
from app.models.transcription_job import TranscriptionJob


def delete_transcription_outputs(job: TranscriptionJob) -> None:
    for path_value in (
        job.output_txt_path,
        job.output_json_path,
        job.output_srt_path,
        job.output_vtt_path,
    ):
        if path_value:
            Path(path_value).unlink(missing_ok=True)

    shutil.rmtree(
        settings.outputs_dir / str(job.owner_user_id) / str(job.id),
        ignore_errors=True,
    )
