import os
import shutil
import sqlite3
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


async def fake_probe_duration(_path):
    return 12.5


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
