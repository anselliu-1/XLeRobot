# 檢查網站安裝包資訊是否維持 2026/10/15 版本，防止後續合併退回舊連結。
from pathlib import Path
import unittest

HTML = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
SECTION = HTML.split('<!-- 專題安裝包 -->', 1)[1].split('</section>', 1)[0]

class InstallerReleaseGuard(unittest.TestCase):
    def test_latest_download_and_checksum(self):
        self.assertIn("https://drive.google.com/file/d/18h680rAEuu_qYmQ0o24DAFnIzBTaOzgQ/view", SECTION)
        self.assertIn("06d1127c5af608e2ceb9f1d5e96906de06faeb23ed8ab5fdd41ed53c17946ed6", SECTION)
        self.assertNotIn("1zNVCxP0fCyPh7KCgdTRClWZCyd7XgncY", SECTION)
    def test_release_notes_are_preserved(self):
        for item in ("2026/10/15 更新重點", "COM 埠自動偵測", "Rerun Viewer", "xle_run.py"):
            with self.subTest(item=item):
                self.assertIn(item, SECTION)

if __name__ == "__main__":
    unittest.main()
