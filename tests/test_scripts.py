from __future__ import annotations

import json
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
