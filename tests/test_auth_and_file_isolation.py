import json
import os
import shutil
import sqlite3
import asyncio
from pathlib import Path

TEST_ROOT = Path("/tmp/asr_ui_tests")
shutil.rmtree(TEST_ROOT, ignore_errors=True)
TEST_ROOT.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_ROOT / 'test.db'}"
os.environ["DATA_DIR"] = str(TEST_ROOT / "data")
os.environ["UPLOADS_DIR"] = str(TEST_ROOT / "data" / "uploads")
os.environ["OUTPUTS_DIR"] = str(TEST_ROOT / "data" / "transcripts")
os.environ["MODELS_DIR"] = str(TEST_ROOT / "models")
os.environ["SECRET_KEY"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.routers import files as files_router  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.services.transcriber import parse_whisper_segment_line  # noqa: E402
from app.services.worker_runtime import try_merge_split_job  # noqa: E402


async def fake_probe_duration(_path):
    return 12.5


def test_live_whisper_segment_parser_extracts_segments():
    parsed = parse_whisper_segment_line(
        "[00:01:00.000 --> 00:01:29.980]  Hello world"
    )
    assert parsed == {
        "timestamps": {"from": "00:01:00,000", "to": "00:01:29,980"},
        "offsets": {"from": 60000, "to": 89980},
        "text": "Hello world",
    }
    assert parse_whisper_segment_line("whisper_print_progress_callback: progress =  33%") is None


def test_first_registration_creates_admin_and_closes_public_signup(monkeypatch):
    monkeypatch.setattr(files_router, "probe_duration_seconds", fake_probe_duration)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "admin",
                "email": "admin@example.com",
                "password": "password1",
            },
        )
        assert response.status_code == 200
        assert response.json()["role"] == "admin"

        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "user",
                "email": "user@example.com",
                "password": "password1",
            },
        )
        assert response.status_code == 403


def test_uploaded_files_are_visible_only_to_owner(monkeypatch):
    monkeypatch.setattr(files_router, "probe_duration_seconds", fake_probe_duration)
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200

        created = client.post(
            "/api/v1/users/",
            json={
                "username": "alice",
                "email": "alice@example.com",
                "password": "password1",
                "role": "user",
            },
        )
        assert created.status_code == 200
        bob_id = created.json()["id"]

        alice = TestClient(app)
        with alice:
            login = alice.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "password1"},
            )
            assert login.status_code == 200

            upload = alice.post(
                "/api/v1/files",
                files={"upload": ("voice.m4a", b"fake-audio", "audio/mp4")},
            )
            assert upload.status_code == 200
            file_id = upload.json()["id"]

            update = alice.patch(
                f"/api/v1/files/{file_id}",
                json={"display_name": "Interview with Alice", "notes": "Kitchen table notes"},
            )
            assert update.status_code == 200
            assert update.json()["display_name"] == "Interview with Alice"
            assert update.json()["notes"] == "Kitchen table notes"

            files = alice.get("/api/v1/files")
            assert files.status_code == 200
            assert [item["id"] for item in files.json()] == [file_id]

        admin_files = client.get("/api/v1/files")
        assert admin_files.status_code == 200
        assert admin_files.json() == []

        delete = client.delete(f"/api/v1/files/{file_id}")
        assert delete.status_code == 404

        update = client.patch(
            f"/api/v1/files/{file_id}",
            json={"display_name": "Admin should not edit this"},
        )
        assert update.status_code == 404


def test_transcription_delete_is_owner_scoped_and_removes_outputs(monkeypatch):
    monkeypatch.setattr(files_router, "probe_duration_seconds", fake_probe_duration)
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200

        created = client.post(
            "/api/v1/users/",
            json={
                "username": "bob",
                "email": "bob@example.com",
                "password": "password1",
                "role": "user",
            },
        )
        assert created.status_code == 200
        bob_id = created.json()["id"]

        bob = TestClient(app)
        with bob:
            login = bob.post(
                "/api/v1/auth/login",
                json={"username": "bob", "password": "password1"},
            )
            assert login.status_code == 200

            upload = bob.post(
                "/api/v1/files",
                files={"upload": ("meeting.m4a", b"fake-audio", "audio/mp4")},
            )
            assert upload.status_code == 200
            file_id = upload.json()["id"]

            output_dir = TEST_ROOT / "data" / "transcripts" / str(bob_id) / "99"
            output_dir.mkdir(parents=True, exist_ok=True)
            txt_path = output_dir / "transcript.txt"
            json_path = output_dir / "transcript.json"
            srt_path = output_dir / "transcript.srt"
            vtt_path = output_dir / "transcript.vtt"
            txt_path.write_text("hello\n", encoding="utf-8")
            json_path.write_text('{"text":"hello"}\n', encoding="utf-8")
            srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
            vtt_path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")

            conn = sqlite3.connect(TEST_ROOT / "test.db")
            model_id = conn.execute(
                """
                insert into transcription_models
                (provider, variant, display_name, language_mode, path, status, downloaded_bytes, is_deleted)
                values ('whisper.cpp', 'tiny', 'Tiny', 'multilingual', '/models/tiny.bin', 'installed', 0, 0)
                returning id
                """
            ).fetchone()[0]
            job_id = conn.execute(
                """
                insert into transcription_jobs
                (id, owner_user_id, audio_file_id, model_id, language, status, status_text,
                 transcript_text, output_txt_path, output_json_path, output_srt_path, output_vtt_path)
                values (99, ?, ?, ?, 'ru', 'succeeded', 'Done', 'hello', ?, ?, ?, ?)
                returning id
                """,
                (
                    bob_id,
                    file_id,
                    model_id,
                    str(txt_path),
                    str(json_path),
                    str(srt_path),
                    str(vtt_path),
                ),
            ).fetchone()[0]
            conn.commit()
            conn.close()

            admin_delete = client.delete(f"/api/v1/transcriptions/{job_id}")
            assert admin_delete.status_code == 404
            assert txt_path.exists()
            assert json_path.exists()
            assert srt_path.exists()
            assert vtt_path.exists()

            delete = bob.delete(f"/api/v1/transcriptions/{job_id}")
            assert delete.status_code == 200
            assert not txt_path.exists()
            assert not json_path.exists()
            assert not srt_path.exists()
            assert not vtt_path.exists()
            assert not output_dir.exists()


def test_model_stats_are_admin_only_and_report_runtime_per_audio_hour():
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200
        admin_id = login.json()["user"]["id"]

        created = client.post(
            "/api/v1/users/",
            json={
                "username": "modelstats_user",
                "email": "modelstats@example.com",
                "password": "password1",
                "role": "user",
            },
        )
        assert created.status_code == 200

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        model_id = conn.execute(
            """
            insert into transcription_models
            (provider, variant, display_name, language_mode, path, status, downloaded_bytes, is_deleted)
            values ('whisper.cpp', 'stats-model', 'Stats Model', 'multilingual', '/models/stats.bin', 'installed', 0, 0)
            returning id
            """
        ).fetchone()[0]
        audio_id = conn.execute(
            """
            insert into audio_files
            (owner_user_id, original_filename, display_name, source, stored_path, size_bytes, duration_seconds)
            values (?, 'hour.wav', 'hour.wav', 'web', '/tmp/hour.wav', 10, 3600)
            returning id
            """,
            (admin_id,),
        ).fetchone()[0]
        conn.execute(
            """
            insert into transcription_jobs
            (owner_user_id, audio_file_id, model_id, language, status, started_at, finished_at)
            values (?, ?, ?, 'en', 'succeeded', '2026-01-01 00:00:00', '2026-01-01 00:12:00')
            """,
            (admin_id, audio_id, model_id),
        )
        conn.commit()
        conn.close()

        stats = client.get("/api/v1/models/stats")
        assert stats.status_code == 200
        model_stats = next(item for item in stats.json() if item["model_id"] == model_id)
        assert model_stats["completed_job_count"] == 1
        assert model_stats["total_audio_seconds"] == 3600
        assert model_stats["total_runtime_seconds"] == 720
        assert model_stats["runtime_per_audio_hour_seconds"] == 720
        assert model_stats["median_runtime_per_audio_hour_seconds"] == 720

        non_admin = TestClient(app)
        with non_admin:
            login = non_admin.post(
                "/api/v1/auth/login",
                json={"username": "modelstats_user", "password": "password1"},
            )
            assert login.status_code == 200
        forbidden = non_admin.get("/api/v1/models/stats")
        assert forbidden.status_code == 403


def test_split_chunks_use_exact_model_worker_speed(monkeypatch):
    monkeypatch.setattr(files_router, "validate_transcription_runtime", lambda: None)
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200
        admin_id = login.json()["user"]["id"]

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        model_id = conn.execute(
            """
            insert into transcription_models
            (provider, variant, display_name, language_mode, path, status, downloaded_bytes, is_deleted)
            values ('whisper.cpp', 'split-speed-model', 'Split Speed Model', 'multilingual', '/models/split-speed.bin', 'installed', 0, 0)
            returning id
            """
        ).fetchone()[0]
        audio_id = conn.execute(
            """
            insert into audio_files
            (owner_user_id, original_filename, display_name, source, stored_path, size_bytes, duration_seconds)
            values (?, 'split.wav', 'split.wav', 'web', '/tmp/split.wav', 10, 120)
            returning id
            """,
            (admin_id,),
        ).fetchone()[0]
        slow_worker_id = conn.execute(
            """
            insert into transcription_workers
            (name, accepted, is_deleted, status, total_audio_seconds, total_runtime_seconds)
            values ('slow-exact-model', 1, 0, 'idle', 1000, 100)
            returning id
            """
        ).fetchone()[0]
        fast_worker_id = conn.execute(
            """
            insert into transcription_workers
            (name, accepted, is_deleted, status, total_audio_seconds, total_runtime_seconds)
            values ('fast-exact-model', 1, 0, 'idle', 10, 100)
            returning id
            """
        ).fetchone()[0]

        history_audio_id = conn.execute(
            """
            insert into audio_files
            (owner_user_id, original_filename, display_name, source, stored_path, size_bytes, duration_seconds)
            values (?, 'history.wav', 'history.wav', 'web', '/tmp/history.wav', 10, 100)
            returning id
            """,
            (admin_id,),
        ).fetchone()[0]
        conn.execute(
            """
            insert into transcription_jobs
            (owner_user_id, audio_file_id, model_id, language, status, worker_id, worker_name_snapshot, started_at, finished_at, split_enabled)
            values (?, ?, ?, 'ru', 'succeeded', ?, 'slow-exact-model', '2026-01-01 00:00:00', '2026-01-01 00:03:20', 0)
            """,
            (admin_id, history_audio_id, model_id, slow_worker_id),
        )
        conn.execute(
            """
            insert into transcription_jobs
            (owner_user_id, audio_file_id, model_id, language, status, worker_id, worker_name_snapshot, started_at, finished_at, split_enabled)
            values (?, ?, ?, 'ru', 'succeeded', ?, 'fast-exact-model', '2026-01-01 00:00:00', '2026-01-01 00:00:20', 0)
            """,
            (admin_id, history_audio_id, model_id, fast_worker_id),
        )
        conn.commit()
        conn.close()

        response = client.post(
            f"/api/v1/files/{audio_id}/transcriptions",
            json={
                "model_id": model_id,
                "language": "ru",
                "split_enabled": True,
                "split_worker_ids": [slow_worker_id, fast_worker_id],
            },
        )
        assert response.status_code == 200
        chunks = sorted(response.json()["split_chunks"], key=lambda item: item["index"])
        assert [chunk["worker_id"] for chunk in chunks] == [slow_worker_id, fast_worker_id]

        slow_seconds = chunks[0]["end_seconds"] - chunks[0]["start_seconds"] - chunks[0]["overlap_end_seconds"]
        fast_seconds = chunks[1]["end_seconds"] - chunks[1]["start_seconds"] - chunks[1]["overlap_start_seconds"]
        assert fast_seconds > slow_seconds * 4


def test_split_chunks_fallback_to_worker_speed_for_matching_model(monkeypatch):
    monkeypatch.setattr(files_router, "validate_transcription_runtime", lambda: None)
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200
        admin_id = login.json()["user"]["id"]

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        model_id = conn.execute(
            """
            insert into transcription_models
            (provider, variant, display_name, language_mode, path, status, downloaded_bytes, is_deleted)
            values ('whisper.cpp', 'base.ru', 'Whisper base Russian', 'russian', '/models/ggml-base.bin', 'installed', 0, 0)
            returning id
            """
        ).fetchone()[0]
        audio_id = conn.execute(
            """
            insert into audio_files
            (owner_user_id, original_filename, display_name, source, stored_path, size_bytes, duration_seconds)
            values (?, 'split-model-speed.wav', 'split-model-speed.wav', 'web', '/tmp/split-model-speed.wav', 10, 120)
            returning id
            """,
            (admin_id,),
        ).fetchone()[0]
        slow_stats = json.dumps(
            [
                {
                    "variant": "base",
                    "completed_count": 1,
                    "total_runtime_seconds": 200,
                    "total_audio_seconds": 100,
                    "runtime_per_audio_hour_seconds": 7200,
                },
                {
                    "variant": "small",
                    "completed_count": 1,
                    "total_runtime_seconds": 10,
                    "total_audio_seconds": 100,
                    "runtime_per_audio_hour_seconds": 360,
                },
            ]
        )
        fast_stats = json.dumps(
            [
                {
                    "variant": "base",
                    "completed_count": 1,
                    "total_runtime_seconds": 20,
                    "total_audio_seconds": 100,
                    "runtime_per_audio_hour_seconds": 720,
                },
                {
                    "variant": "small",
                    "completed_count": 1,
                    "total_runtime_seconds": 200,
                    "total_audio_seconds": 100,
                    "runtime_per_audio_hour_seconds": 7200,
                },
            ]
        )
        slow_worker_id = conn.execute(
            """
            insert into transcription_workers
            (name, accepted, is_deleted, status, total_audio_seconds, total_runtime_seconds, model_speed_stats_json)
            values ('slow-base-model', 1, 0, 'idle', 1000, 10, ?)
            returning id
            """,
            (slow_stats,),
        ).fetchone()[0]
        fast_worker_id = conn.execute(
            """
            insert into transcription_workers
            (name, accepted, is_deleted, status, total_audio_seconds, total_runtime_seconds, model_speed_stats_json)
            values ('fast-base-model', 1, 0, 'idle', 10, 1000, ?)
            returning id
            """,
            (fast_stats,),
        ).fetchone()[0]
        conn.commit()
        conn.close()

        response = client.post(
            f"/api/v1/files/{audio_id}/transcriptions",
            json={
                "model_id": model_id,
                "language": "ru",
                "split_enabled": True,
                "split_worker_ids": [slow_worker_id, fast_worker_id],
            },
        )
        assert response.status_code == 200
        chunks = sorted(response.json()["split_chunks"], key=lambda item: item["index"])

        slow_seconds = chunks[0]["end_seconds"] - chunks[0]["start_seconds"] - chunks[0]["overlap_end_seconds"]
        fast_seconds = chunks[1]["end_seconds"] - chunks[1]["start_seconds"] - chunks[1]["overlap_start_seconds"]
        assert fast_seconds > slow_seconds * 4


def test_partial_transcription_fields_and_segments_are_visible(monkeypatch):
    monkeypatch.setattr(files_router, "probe_duration_seconds", fake_probe_duration)
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200
        admin_id = login.json()["user"]["id"]

        upload = client.post(
            "/api/v1/files",
            files={"upload": ("partial.m4a", b"fake-audio", "audio/mp4")},
        )
        assert upload.status_code == 200
        file_id = upload.json()["id"]

        partial_payload = {
            "transcription": [
                {
                    "timestamps": {"from": "00:00:00,000", "to": "00:00:02,000"},
                    "offsets": {"from": 0, "to": 2000},
                    "text": "first partial",
                },
                {
                    "timestamps": {"from": "00:00:02,000", "to": "00:00:04,000"},
                    "offsets": {"from": 2000, "to": 4000},
                    "text": "second partial",
                },
            ]
        }
        conn = sqlite3.connect(TEST_ROOT / "test.db")
        model_id = conn.execute(
            """
            insert into transcription_models
            (provider, variant, display_name, language_mode, path, status, downloaded_bytes, is_deleted)
            values ('whisper.cpp', 'partial-model', 'Partial Model', 'multilingual', '/models/tiny.bin', 'installed', 0, 0)
            returning id
            """
        ).fetchone()[0]
        job_id = conn.execute(
            """
            insert into transcription_jobs
            (owner_user_id, audio_file_id, model_id, language, status, status_text,
             partial_transcript_text, partial_transcript_json, partial_updated_at)
            values (?, ?, ?, 'ru', 'running', 'Transcribing 50%', ?, ?, CURRENT_TIMESTAMP)
            returning id
            """,
            (
                admin_id,
                file_id,
                model_id,
                "first partial\nsecond partial",
                json.dumps(partial_payload),
            ),
        ).fetchone()[0]
        conn.commit()
        conn.close()

        listed = client.get("/api/v1/transcriptions")
        assert listed.status_code == 200
        partial_job = next(item for item in listed.json() if item["id"] == job_id)
        assert partial_job["partial_transcript_text"] == "first partial\nsecond partial"
        assert partial_job["partial_updated_at"] is not None

        auto_segments = client.get(f"/api/v1/transcriptions/{job_id}/segments")
        assert auto_segments.status_code == 200
        assert auto_segments.json() == [
            {"start": 0.0, "end": 2.0, "text": "first partial"},
            {"start": 2.0, "end": 4.0, "text": "second partial"},
        ]

        final_segments = client.get(f"/api/v1/transcriptions/{job_id}/segments?source=final")
        assert final_segments.status_code == 409


def test_projects_group_files_and_related_transcriptions(monkeypatch):
    monkeypatch.setattr(files_router, "probe_duration_seconds", fake_probe_duration)
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200
        admin_id = login.json()["user"]["id"]

        created = client.post(
            "/api/v1/projects",
            json={"name": "Interviews", "description": "Candidate calls"},
        )
        assert created.status_code == 200
        project_id = created.json()["id"]

        duplicate = client.post(
            "/api/v1/projects",
            json={"name": " interviews "},
        )
        assert duplicate.status_code == 400

        upload = client.post(
            "/api/v1/files",
            data={"project_id": str(project_id)},
            files={"upload": ("candidate.m4a", b"fake-audio", "audio/mp4")},
        )
        assert upload.status_code == 200
        file_id = upload.json()["id"]
        assert upload.json()["project_id"] == project_id
        assert upload.json()["project"]["name"] == "Interviews"

        all_files = client.get("/api/v1/files")
        assert [item["id"] for item in all_files.json()] == [file_id]
        project_files = client.get(f"/api/v1/files?project_id={project_id}")
        assert [item["id"] for item in project_files.json()] == [file_id]
        unassigned_files = client.get("/api/v1/files?project_id=none")
        assert unassigned_files.json() == []

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        model_id = conn.execute(
            """
            insert into transcription_models
            (provider, variant, display_name, language_mode, path, status, downloaded_bytes, is_deleted)
            values ('whisper.cpp', 'tiny-projects', 'Tiny Projects', 'multilingual', '/models/tiny.bin', 'installed', 0, 0)
            returning id
            """
        ).fetchone()[0]
        job_id = conn.execute(
            """
            insert into transcription_jobs
            (owner_user_id, audio_file_id, model_id, language, status, status_text, transcript_text)
            values (?, ?, ?, 'ru', 'succeeded', 'Done', 'hello')
            returning id
            """,
            (admin_id, file_id, model_id),
        ).fetchone()[0]
        conn.commit()
        conn.close()

        transcriptions = client.get(f"/api/v1/transcriptions?project_id={project_id}")
        assert transcriptions.status_code == 200
        assert [item["id"] for item in transcriptions.json()] == [job_id]
        assert transcriptions.json()[0]["audio_file"]["project"]["name"] == "Interviews"

        unassigned_transcriptions = client.get("/api/v1/transcriptions?project_id=none")
        assert unassigned_transcriptions.status_code == 200
        assert unassigned_transcriptions.json() == []

        update = client.patch(f"/api/v1/files/{file_id}", json={"project_id": None})
        assert update.status_code == 200
        assert update.json()["project_id"] is None
        assert update.json()["project"] is None

        unassigned_transcriptions = client.get("/api/v1/transcriptions?project_id=none")
        assert [item["id"] for item in unassigned_transcriptions.json()] == [job_id]

        update = client.patch(f"/api/v1/files/{file_id}", json={"project_id": project_id})
        assert update.status_code == 200
        delete = client.delete(f"/api/v1/projects/{project_id}")
        assert delete.status_code == 200
        after_delete = client.get("/api/v1/files?project_id=none")
        assert [item["id"] for item in after_delete.json()] == [file_id]
        after_delete_transcriptions = client.get("/api/v1/transcriptions?project_id=none")
        assert [item["id"] for item in after_delete_transcriptions.json()] == [job_id]


def test_project_assignment_is_owner_scoped(monkeypatch):
    monkeypatch.setattr(files_router, "probe_duration_seconds", fake_probe_duration)
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200

        created = client.post(
            "/api/v1/users/",
            json={
                "username": "charlie",
                "email": "charlie@example.com",
                "password": "password1",
                "role": "user",
            },
        )
        assert created.status_code == 200

        admin_project = client.post("/api/v1/projects", json={"name": "Admin project"})
        assert admin_project.status_code == 200
        admin_project_id = admin_project.json()["id"]

        charlie = TestClient(app)
        with charlie:
            login = charlie.post(
                "/api/v1/auth/login",
                json={"username": "charlie", "password": "password1"},
            )
            assert login.status_code == 200

            upload = charlie.post(
                "/api/v1/files",
                data={"project_id": str(admin_project_id)},
                files={"upload": ("private.m4a", b"fake-audio", "audio/mp4")},
            )
            assert upload.status_code == 404

            own_project = charlie.post("/api/v1/projects", json={"name": "Own project"})
            assert own_project.status_code == 200
            own_project_id = own_project.json()["id"]

            upload = charlie.post(
                "/api/v1/files",
                files={"upload": ("private.m4a", b"fake-audio", "audio/mp4")},
            )
            assert upload.status_code == 200
            file_id = upload.json()["id"]

            forbidden_update = client.patch(
                f"/api/v1/files/{file_id}",
                json={"project_id": admin_project_id},
            )
            assert forbidden_update.status_code == 404

            update = charlie.patch(
                f"/api/v1/files/{file_id}",
                json={"project_id": own_project_id},
            )
            assert update.status_code == 200
            assert update.json()["project_id"] == own_project_id


def test_whisper_cli_settings_are_admin_only():
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200

        current = client.get("/api/v1/system/whisper-cli")
        assert current.status_code == 200
        assert current.json()["whisper_threads"] == 4
        assert current.json()["whisper_max_context"] == 0
        assert "-mc" in current.json()["cli_preview"]

        updated = client.patch(
            "/api/v1/system/whisper-cli",
            json={
                "whisper_threads": 2,
                "whisper_max_context": 128,
                "whisper_use_gpu": False,
                "whisper_flash_attn": False,
                "whisper_suppress_non_speech": True,
                "whisper_suppress_regex": "subtitle",
                "transcript_filter_regex": "credits",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["whisper_threads"] == 2
        assert updated.json()["whisper_max_context"] == 128
        assert updated.json()["whisper_suppress_regex"] == "subtitle"

        created = client.post(
            "/api/v1/users/",
            json={
                "username": "dave",
                "email": "dave@example.com",
                "password": "password1",
                "role": "user",
            },
        )
        assert created.status_code == 200

        dave = TestClient(app)
        with dave:
            login = dave.post(
                "/api/v1/auth/login",
                json={"username": "dave", "password": "password1"},
            )
            assert login.status_code == 200
            forbidden = dave.get("/api/v1/system/whisper-cli")
            assert forbidden.status_code == 403

        reset = client.post("/api/v1/system/whisper-cli/reset")
        assert reset.status_code == 200
        assert reset.json()["whisper_threads"] == 4
        assert reset.json()["whisper_max_context"] == 0


def test_telegram_bot_settings_are_admin_only_validated_and_masked(monkeypatch):
    from app.routers import system as system_router

    async def fake_restart():
        return None

    monkeypatch.setattr(system_router, "restart_telegram_bot", fake_restart)
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200
        admin_id = login.json()["user"]["id"]

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        model_id = conn.execute(
            """
            insert into transcription_models
            (provider, variant, display_name, language_mode, path, status, downloaded_bytes, is_deleted)
            values ('whisper.cpp', 'telegram-model', 'Telegram Model', 'multilingual', '/models/tiny.bin', 'installed', 0, 0)
            returning id
            """
        ).fetchone()[0]
        conn.commit()
        conn.close()

        created = client.post(
            "/api/v1/users/",
            json={
                "username": "telegram_non_admin",
                "email": "telegram-non-admin@example.com",
                "password": "password1",
                "role": "user",
            },
        )
        assert created.status_code == 200

        invalid = client.patch(
            "/api/v1/system/telegram-bot",
            json={
                "enabled": True,
                "bot_token": "123456:SECRET",
                "default_model_id": model_id,
                "default_language": "auto",
                "allowed_users": [{"telegram_user_id": 1001, "app_user_id": 999999}],
            },
        )
        assert invalid.status_code == 400

        updated = client.patch(
            "/api/v1/system/telegram-bot",
            json={
                "enabled": True,
                "bot_token": "123456:SECRET",
                "proxy_url": "http://proxy.internal:10809",
                "default_model_id": model_id,
                "default_language": "auto",
                "allowed_users": [{"telegram_user_id": 1001, "app_user_id": admin_id}],
            },
        )
        assert updated.status_code == 200
        data = updated.json()
        assert data["enabled"] is True
        assert data["token_configured"] is True
        assert data["token_preview"] == "1234...CRET"
        assert "bot_token" not in data
        assert data["proxy_url"] == "http://proxy.internal:10809"
        assert data["allowed_users"] == [
            {
                "telegram_user_id": 1001,
                "app_user_id": admin_id,
                "preferred_worker_id": None,
                "preferred_model_id": None,
                "split_enabled": None,
                "split_worker_ids": [],
                "summarize_enabled": False,
            }
        ]

        login = client.post(
            "/api/v1/auth/login",
            json={"username": "telegram_non_admin", "password": "password1"},
        )
        assert login.status_code == 200
        forbidden = client.get("/api/v1/system/telegram-bot")
        assert forbidden.status_code == 403

        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200
        disabled = client.patch("/api/v1/system/telegram-bot", json={"enabled": False})
        assert disabled.status_code == 200


def test_cancel_requested_split_job_with_mixed_terminal_chunks_stays_cancelled():
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200
        admin_id = login.json()["user"]["id"]

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        model_id = conn.execute(
            """
            insert into transcription_models
            (provider, variant, display_name, language_mode, path, status, downloaded_bytes, is_deleted)
            values ('whisper.cpp', 'cancel-split-model', 'Cancel Split Model', 'multilingual', '/models/cancel.bin', 'installed', 0, 0)
            returning id
            """
        ).fetchone()[0]
        audio_id = conn.execute(
            """
            insert into audio_files
            (owner_user_id, original_filename, display_name, source, stored_path, size_bytes, duration_seconds)
            values (?, 'split.wav', 'split.wav', 'web', '/tmp/split.wav', 10, 600)
            returning id
            """,
            (admin_id,),
        ).fetchone()[0]
        job_id = conn.execute(
            """
            insert into transcription_jobs
            (owner_user_id, audio_file_id, model_id, language, status, status_text,
             split_enabled, split_status, cancel_requested_at, started_at)
            values (?, ?, ?, 'ru', 'queued', 'Split transcription 0/2 chunks',
             1, 'queued', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            returning id
            """,
            (admin_id, audio_id, model_id),
        ).fetchone()[0]
        conn.execute(
            """
            insert into transcription_job_chunks
            (parent_job_id, "index", start_seconds, end_seconds, overlap_start_seconds,
             overlap_end_seconds, status, status_text, finished_at)
            values (?, 0, 0, 300, 0, 5, 'cancelled', 'Cancelled', CURRENT_TIMESTAMP)
            """,
            (job_id,),
        )
        conn.execute(
            """
            insert into transcription_job_chunks
            (parent_job_id, "index", start_seconds, end_seconds, overlap_start_seconds,
             overlap_end_seconds, status, status_text, finished_at)
            values (?, 1, 295, 600, 5, 0, 'succeeded', 'Chunk finished', CURRENT_TIMESTAMP)
            """,
            (job_id,),
        )
        conn.commit()
        conn.close()

        async def merge() -> None:
            async with async_session_factory() as db:
                await try_merge_split_job(db, job_id)

        asyncio.run(merge())

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        row = conn.execute(
            "select status, split_status, status_text, finished_at from transcription_jobs where id = ?",
            (job_id,),
        ).fetchone()
        conn.close()

        assert row[0] == "cancelled"
        assert row[1] == "cancelled"
        assert row[2] == "Cancelled"
        assert row[3] is not None


def test_cancel_running_split_job_cancels_queued_chunks_and_returns_cancelling():
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200
        admin_id = login.json()["user"]["id"]

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        model_id = conn.execute(
            """
            insert into transcription_models
            (provider, variant, display_name, language_mode, path, status, downloaded_bytes, is_deleted)
            values ('whisper.cpp', 'cancel-api-model', 'Cancel API Model', 'multilingual', '/models/cancel-api.bin', 'installed', 0, 0)
            returning id
            """
        ).fetchone()[0]
        audio_id = conn.execute(
            """
            insert into audio_files
            (owner_user_id, original_filename, display_name, source, stored_path, size_bytes, duration_seconds)
            values (?, 'split-api.wav', 'split-api.wav', 'web', '/tmp/split-api.wav', 10, 600)
            returning id
            """,
            (admin_id,),
        ).fetchone()[0]
        job_id = conn.execute(
            """
            insert into transcription_jobs
            (owner_user_id, audio_file_id, model_id, language, status, status_text,
             split_enabled, split_status, started_at)
            values (?, ?, ?, 'ru', 'running', 'Split transcription running',
             1, 'running', CURRENT_TIMESTAMP)
            returning id
            """,
            (admin_id, audio_id, model_id),
        ).fetchone()[0]
        conn.execute(
            """
            insert into transcription_job_chunks
            (parent_job_id, "index", start_seconds, end_seconds, overlap_start_seconds,
             overlap_end_seconds, status, status_text, started_at)
            values (?, 0, 0, 300, 0, 5, 'running', 'Transcribing chunk', CURRENT_TIMESTAMP)
            """,
            (job_id,),
        )
        conn.execute(
            """
            insert into transcription_job_chunks
            (parent_job_id, "index", start_seconds, end_seconds, overlap_start_seconds,
             overlap_end_seconds, status, status_text)
            values (?, 1, 295, 600, 5, 0, 'queued', 'Queued')
            """,
            (job_id,),
        )
        conn.commit()
        conn.close()

        cancelled = client.post(f"/api/v1/transcriptions/{job_id}/cancel")
        assert cancelled.status_code == 200
        payload = cancelled.json()
        assert payload["status"] == "running"
        assert payload["split_status"] == "running"
        assert payload["status_text"] == "Cancelling…"

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        rows = conn.execute(
            "select status from transcription_job_chunks where parent_job_id = ? order by \"index\"",
            (job_id,),
        ).fetchall()
        conn.close()

        assert [row[0] for row in rows] == ["running", "cancelled"]


def test_summarization_settings_defaults_and_update():
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200

        defaults = client.get("/api/v1/system/summarization")
        assert defaults.status_code == 200
        assert defaults.json()["ollama_base_url"] == "http://ollama:11434"

        updated = client.patch(
            "/api/v1/system/summarization",
            json={
                "enabled": True,
                "ollama_base_url": "http://ollama:11434",
                "selected_model": "qwen2.5:1.5b",
                "auto_summarize": True,
                "prompt": "Summarize the transcript into concise notes with key points and action items.",
            },
        )
        assert updated.status_code == 200
        payload = updated.json()
        assert payload["enabled"] is True
        assert payload["selected_model"] == "qwen2.5:1.5b"
        assert payload["auto_summarize"] is True


def test_manual_summary_rejects_unfinished_transcription():
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200
        admin_id = login.json()["user"]["id"]

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        model_id = conn.execute(
            """
            insert into transcription_models
            (provider, variant, display_name, language_mode, path, status, downloaded_bytes, is_deleted)
            values ('whisper.cpp', 'summary-reject-model', 'Summary Reject Model', 'multilingual', '/models/summary-reject.bin', 'installed', 0, 0)
            returning id
            """
        ).fetchone()[0]
        audio_id = conn.execute(
            """
            insert into audio_files
            (owner_user_id, original_filename, display_name, source, stored_path, size_bytes, duration_seconds)
            values (?, 'summary-reject.wav', 'summary-reject.wav', 'web', '/tmp/summary-reject.wav', 10, 60)
            returning id
            """,
            (admin_id,),
        ).fetchone()[0]
        job_id = conn.execute(
            """
            insert into transcription_jobs
            (owner_user_id, audio_file_id, model_id, language, status, status_text, transcript_text)
            values (?, ?, ?, 'ru', 'running', 'Transcribing', 'partial text')
            returning id
            """,
            (admin_id, audio_id, model_id),
        ).fetchone()[0]
        conn.commit()
        conn.close()

        response = client.post(f"/api/v1/transcriptions/{job_id}/summary")
        assert response.status_code == 409


def test_cancel_dangling_summary_job():
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200
        admin_id = login.json()["user"]["id"]

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        model_id = conn.execute(
            """
            insert into transcription_models
            (provider, variant, display_name, language_mode, path, status, downloaded_bytes, is_deleted)
            values ('whisper.cpp', 'summary-cancel-model', 'Summary Cancel Model', 'multilingual', '/models/summary-cancel.bin', 'installed', 0, 0)
            returning id
            """
        ).fetchone()[0]
        audio_id = conn.execute(
            """
            insert into audio_files
            (owner_user_id, original_filename, display_name, source, stored_path, size_bytes, duration_seconds)
            values (?, 'summary-cancel.wav', 'summary-cancel.wav', 'web', '/tmp/summary-cancel.wav', 10, 60)
            returning id
            """,
            (admin_id,),
        ).fetchone()[0]
        job_id = conn.execute(
            """
            insert into transcription_jobs
            (owner_user_id, audio_file_id, model_id, language, status, status_text, transcript_text, summary_status)
            values (?, ?, ?, 'ru', 'succeeded', 'Done', 'Finished text', 'running')
            returning id
            """,
            (admin_id, audio_id, model_id),
        ).fetchone()[0]
        conn.commit()
        conn.close()

        response = client.post(f"/api/v1/transcriptions/{job_id}/summary/cancel")
        assert response.status_code == 200
        payload = response.json()
        assert payload["summary_status"] == "cancelled"
        assert payload["summary_finished_at"] is not None


def test_summarize_job_records_success_and_failure(monkeypatch):
    from app.services import summarizer

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200
        admin_id = login.json()["user"]["id"]

        client.patch(
            "/api/v1/system/summarization",
            json={
                "enabled": True,
                "ollama_base_url": "http://ollama:11434",
                "selected_model": "qwen2.5:1.5b",
                "auto_summarize": False,
                "prompt": "Summarize the transcript into concise notes with key points and action items.",
            },
        )

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        model_id = conn.execute(
            """
            insert into transcription_models
            (provider, variant, display_name, language_mode, path, status, downloaded_bytes, is_deleted)
            values ('whisper.cpp', 'summary-ok-model', 'Summary OK Model', 'multilingual', '/models/summary-ok.bin', 'installed', 0, 0)
            returning id
            """
        ).fetchone()[0]
        audio_id = conn.execute(
            """
            insert into audio_files
            (owner_user_id, original_filename, display_name, source, stored_path, size_bytes, duration_seconds)
            values (?, 'summary-ok.wav', 'summary-ok.wav', 'web', '/tmp/summary-ok.wav', 10, 60)
            returning id
            """,
            (admin_id,),
        ).fetchone()[0]
        job_id = conn.execute(
            """
            insert into transcription_jobs
            (owner_user_id, audio_file_id, model_id, language, status, status_text, transcript_text)
            values (?, ?, ?, 'ru', 'succeeded', 'Done', 'Обсудили план и задачи.')
            returning id
            """,
            (admin_id, audio_id, model_id),
        ).fetchone()[0]
        conn.commit()
        conn.close()

        async def fake_summary(_config, _text):
            return "Краткое резюме."

        monkeypatch.setattr(summarizer, "_summarize_text", fake_summary)
        asyncio.run(summarizer.summarize_job(job_id))

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        row = conn.execute(
            "select status, summary_status, summary_text, summary_model from transcription_jobs where id = ?",
            (job_id,),
        ).fetchone()
        conn.close()
        assert row == ("succeeded", "succeeded", "Краткое резюме.", "qwen2.5:1.5b")

        async def failing_summary(_config, _text):
            raise RuntimeError("ollama unavailable")

        monkeypatch.setattr(summarizer, "_summarize_text", failing_summary)
        asyncio.run(summarizer.summarize_job(job_id))

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        row = conn.execute(
            "select status, summary_status, summary_error from transcription_jobs where id = ?",
            (job_id,),
        ).fetchone()
        conn.close()
        assert row[0] == "succeeded"
        assert row[1] == "failed"
        assert "ollama unavailable" in row[2]


def test_telegram_requested_summary_is_sent_when_ready(monkeypatch):
    from app.services import summarizer
    from app.services import telegram_bot

    sent_documents = []

    class FakeTelegramResponse:
        status_code = 200
        text = "ok"

    async def fake_summary(_config, _text):
        return "Telegram summary text."

    async def fake_telegram_request(_config, _http_method, api_method, **kwargs):
        if api_method == "sendDocument":
            sent_documents.append(kwargs)
        return FakeTelegramResponse()

    monkeypatch.setattr(summarizer, "_summarize_text", fake_summary)
    monkeypatch.setattr(telegram_bot, "telegram_api_request", fake_telegram_request)

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password1"},
        )
        assert login.status_code == 200
        admin_id = login.json()["user"]["id"]

        client.patch(
            "/api/v1/system/summarization",
            json={
                "enabled": True,
                "ollama_base_url": "http://ollama:11434",
                "selected_model": "qwen2.5:1.5b",
                "auto_summarize": False,
                "prompt": "Summarize the transcript into concise notes with key points and action items.",
            },
        )

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        conn.execute(
            """
            insert into app_settings (key, value)
            values ('telegram_bot_settings', ?)
            on conflict(key) do update set value = excluded.value
            """,
            (json.dumps({"bot_token": "123456:SECRET"}),),
        )
        model_id = conn.execute(
            """
            insert into transcription_models
            (provider, variant, display_name, language_mode, path, status, downloaded_bytes, is_deleted)
            values ('whisper.cpp', 'telegram-summary-model', 'Telegram Summary Model', 'multilingual', '/models/telegram-summary.bin', 'installed', 0, 0)
            returning id
            """
        ).fetchone()[0]
        audio_id = conn.execute(
            """
            insert into audio_files
            (owner_user_id, original_filename, display_name, source, stored_path, size_bytes, duration_seconds)
            values (?, 'telegram-summary.wav', 'telegram-summary.wav', 'telegram', '/tmp/telegram-summary.wav', 10, 60)
            returning id
            """,
            (admin_id,),
        ).fetchone()[0]
        job_id = conn.execute(
            """
            insert into transcription_jobs
            (owner_user_id, audio_file_id, model_id, language, status, status_text, transcript_text,
             source, telegram_chat_id, telegram_summary_requested)
            values (?, ?, ?, 'ru', 'succeeded', 'Done', 'Discussed the launch plan.',
                    'telegram', '1001', 1)
            returning id
            """,
            (admin_id, audio_id, model_id),
        ).fetchone()[0]
        conn.commit()
        conn.close()

        asyncio.run(summarizer.summarize_job(job_id))

        assert len(sent_documents) == 1
        document = sent_documents[0]
        assert document["data"] == {
            "chat_id": "1001",
            "caption": f"Summary for transcription job #{job_id}.",
        }
        assert document["files"] == {
            "document": (
                f"summary_{job_id}.txt",
                b"Telegram summary text.",
                "text/plain; charset=utf-8",
            )
        }

        conn = sqlite3.connect(TEST_ROOT / "test.db")
        row = conn.execute(
            "select telegram_summary_sent_at, telegram_summary_error from transcription_jobs where id = ?",
            (job_id,),
        ).fetchone()
        conn.close()
        assert row[0] is not None
        assert row[1] is None


def test_long_transcripts_are_chunked(monkeypatch):
    from app.schemas.summarization_settings import SummarizationSettings
    from app.services import summarizer

    calls = []

    async def fake_generate(_config, prompt):
        calls.append(prompt)
        return f"summary {len(calls)}"

    monkeypatch.setattr(summarizer, "_CHUNK_CHAR_LIMIT", 50)
    monkeypatch.setattr(summarizer, "_ollama_generate", fake_generate)
    config = SummarizationSettings(enabled=True, selected_model="qwen2.5:1.5b")
    text = "\n".join(["one two three four five six seven eight nine ten"] * 8)

    result = asyncio.run(summarizer._summarize_text(config, text))

    assert result == f"summary {len(calls)}"
    assert len(calls) > 2


def test_ollama_request_uses_bounded_context_and_prediction(monkeypatch):
    from app.schemas.summarization_settings import SummarizationSettings
    from app.services import summarizer

    captured = {}

    class FakeResponse:
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "Bounded summary"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, path, json):
            captured["path"] = path
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(summarizer.httpx, "AsyncClient", FakeClient)

    config = SummarizationSettings(enabled=True, selected_model="qwen2.5:1.5b")
    result = asyncio.run(summarizer._ollama_generate(config, "Transcript"))

    assert result == "Bounded summary"
    assert captured["path"] == "/api/generate"
    assert captured["json"]["options"]["num_ctx"] == 4096
    assert captured["json"]["options"]["num_predict"] == 512
    assert captured["client_kwargs"]["timeout"].timeout == 900


def test_summary_timeout_error_is_not_empty():
    from app.services import summarizer

    assert summarizer._summary_error_message(summarizer.httpx.ReadTimeout("")) == (
        "Ollama request timed out after 900 seconds"
    )
