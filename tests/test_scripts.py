from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "storyboard-scene-pipeline-skill" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from init_story_session import find_existing_sessions  # noqa: E402
from release_audit import audit_text_files  # noqa: E402
from validate_story_session import validate_video_readiness  # noqa: E402


def run_script(name: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / name), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


class WorkspaceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="storyboard-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        shutil.copy2(REPO_ROOT / "storyboard.config.json", self.root / "storyboard.config.json")

    def init_session(self, title: str, *extra: str) -> Path:
        result = run_script("init_story_session.py", title, *extra, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        return Path(result.stdout.strip().splitlines()[-1])

    def edit_state(self, state_path: Path, **changes: object) -> None:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.update(changes)
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


class InitSessionTests(WorkspaceTestCase):
    def test_title_does_not_reopen_session_with_matching_suffix(self) -> None:
        hot_dog = self.init_session("Hot Dog")
        dog = self.init_session("Dog")

        self.assertNotEqual(hot_dog.parent, dog.parent)
        self.assertTrue(dog.parent.name.endswith("-dog"))
        self.assertFalse(dog.parent.name.endswith("-hot-dog"))
        self.assertEqual(self.init_session("Dog"), dog)

    def test_render_failure_removes_half_created_session(self) -> None:
        skill_copy = self.root / "skill"
        shutil.copytree(REPO_ROOT / "storyboard-scene-pipeline-skill", skill_copy)
        (skill_copy / "assets" / "story_session_template.html").unlink()

        result = subprocess.run(
            [sys.executable, str(skill_copy / "scripts" / "init_story_session.py"), "Broken"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("已删除未完成的 session 目录", result.stderr)
        self.assertEqual(list((self.root / "sessions").iterdir()), [])

    def test_find_existing_sessions_orders_collision_suffix_after_base(self) -> None:
        sessions = self.root / "sessions"
        for name in ("20260101-120000-2-dog", "20260101-120000-dog", "20260101-120000-hot-dog", "20251231-235959-dog"):
            (sessions / name).mkdir(parents=True)

        names = [path.name for path in find_existing_sessions(sessions, "dog")]

        self.assertEqual(names, ["20251231-235959-dog", "20260101-120000-dog", "20260101-120000-2-dog"])


class RenderTests(WorkspaceTestCase):
    def test_placeholder_text_in_user_content_is_not_expanded(self) -> None:
        state_path = self.init_session("Placeholder")
        self.edit_state(
            state_path,
            project_title="Title {{SHOT_BOARDS}}",
            shots=[{"id": "Shot 01", "duration": "3", "frame": "f", "camera": "c", "action": "a"}],
        )

        result = run_script("render_story_session.py", str(state_path), cwd=self.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        html = state_path.with_name("session.html").read_text(encoding="utf-8")
        self.assertIn("Title {{SHOT_BOARDS}}", html)
        self.assertEqual(html.count('<article class="shot-board">'), 1)

    def test_render_tolerates_malformed_sections(self) -> None:
        state_path = self.init_session("Malformed")
        self.edit_state(state_path, line_art="oops", final_generation={"gallery": ["oops"]}, outline=[], shots=["oops"])

        result = run_script("render_story_session.py", str(state_path), cwd=self.root)

        self.assertEqual(result.returncode, 0, result.stderr)


class ValidateTests(WorkspaceTestCase):
    def test_malformed_sections_are_reported_as_failures(self) -> None:
        state_path = self.init_session("Malformed")
        self.edit_state(state_path, line_art="oops", final_generation={"gallery": ["oops"]})

        result = run_script("validate_story_session.py", "--profile", "smoke", str(state_path), cwd=self.root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("line_art must be an object", result.stdout)
        self.assertIn("final_generation.gallery[0] must be an object", result.stdout)
        self.assertNotIn("未预期错误", result.stderr)

    def test_process_language_check_matches_whole_words_only(self) -> None:
        state_path = self.init_session("Words")
        shots = [{"id": "Shot 01", "duration": "3", "frame": "f", "camera": "c", "action": "a"}]

        self.edit_state(state_path, shots=shots, project_summary="An unapproved plan backstage 10 times.")
        run_script("render_story_session.py", str(state_path), cwd=self.root)
        clean = run_script("validate_story_session.py", "--profile", "smoke", str(state_path), cwd=self.root)

        self.edit_state(state_path, project_summary="The plan was approved at stage 1.")
        run_script("render_story_session.py", str(state_path), cwd=self.root)
        leaky = run_script("validate_story_session.py", "--profile", "smoke", str(state_path), cwd=self.root)

        self.assertEqual(clean.returncode, 0, clean.stdout)
        self.assertEqual(leaky.returncode, 1)
        self.assertIn("approved/draft process language", leaky.stdout)
        self.assertIn("Stage 1/2 language", leaky.stdout)

    def test_first_frame_path_must_stay_inside_assets(self) -> None:
        state_path = self.root / "sessions" / "s" / "session.json"
        (state_path.parent / "assets").mkdir(parents=True)
        outside = self.root / "outside.jpg"
        outside.write_bytes(b"\0")
        readiness = {
            "status": "s",
            "motion_intensity": "m",
            "camera_motion": "c",
            "risk_level": "r",
            "test_status": "t",
            "must_preserve": ["x"],
        }
        shots = [
            {"id": "Shot 01", "video_readiness": {**readiness, "first_frame_path": str(outside)}},
            {"id": "Shot 02", "video_readiness": {**readiness, "first_frame_path": "../../outside.jpg"}},
        ]

        failures: list[str] = []
        validate_video_readiness(state_path, shots, "assets", failures)

        self.assertTrue(any("Shot 01 first frame uses an absolute path" in failure for failure in failures))
        self.assertTrue(any("Shot 02 first frame is outside the session assets directory" in failure for failure in failures))

    def test_examples_pass_release_profile(self) -> None:
        for state_path in sorted((REPO_ROOT / "examples").glob("*/*/session.json")):
            with self.subTest(example=state_path.parent.name):
                result = run_script(
                    "validate_story_session.py",
                    "--profile",
                    "release",
                    "--workspace-root",
                    str(REPO_ROOT),
                    str(state_path),
                    cwd=REPO_ROOT,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class RegisterAssetTests(WorkspaceTestCase):
    def test_validation_failure_reports_details_and_rolls_back(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")

        state_path = self.init_session("Register")
        self.edit_state(
            state_path,
            shots=[{"id": "Shot 01", "duration": "3", "frame": "f", "camera": "c", "action": "a"}],
        )
        run_script("render_story_session.py", str(state_path), cwd=self.root)
        original_state = state_path.read_text(encoding="utf-8")
        source = self.root / "source.png"
        Image.new("RGB", (64, 36)).save(source)

        result = run_script(
            "register_story_asset.py",
            str(state_path),
            "--source",
            str(source),
            "--shot-id",
            "Shot 01",
            "--asset-type",
            "line-art",
            "--validate-profile",
            "release",
            cwd=self.root,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("VALIDATION FAILED (release)", result.stderr)
        self.assertIn("已自动回滚", result.stderr)
        self.assertEqual(state_path.read_text(encoding="utf-8"), original_state)
        self.assertFalse((state_path.parent / "assets" / "shot01-line.jpg").exists())


class SubprocessInterpreterTests(WorkspaceTestCase):
    def test_child_scripts_use_the_running_interpreter(self) -> None:
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        fake_python = fake_bin / "python3"
        fake_python.write_text("#!/bin/sh\necho 'wrong interpreter' >&2\nexit 97\n", encoding="utf-8")
        fake_python.chmod(0o755)
        state_path = self.init_session("Interpreter")
        patch_path = self.root / "patch.json"
        patch_path.write_text(json.dumps({"project_summary": "updated"}), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "update_story_session.py"), str(state_path), str(patch_path)],
            cwd=self.root,
            capture_output=True,
            text=True,
            env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("updated", state_path.read_text(encoding="utf-8"))


class ReleaseAuditTests(unittest.TestCase):
    def test_source_scan_skips_files_excluded_from_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "scripts"
            (source / "__pycache__").mkdir(parents=True)
            (source / "__pycache__" / "module.cpython-312.pyc").write_bytes(b"\0")
            (source / "module.py").write_text("print('ok')\n", encoding="utf-8")

            source_failures: list[str] = []
            audit_text_files(source, source_failures, skip_bundle_excluded=True)
            artifact_failures: list[str] = []
            audit_text_files(source, artifact_failures)

        self.assertEqual(source_failures, [])
        self.assertEqual(len(artifact_failures), 1)
        self.assertIn("Python 临时文件", artifact_failures[0])


if __name__ == "__main__":
    unittest.main()
