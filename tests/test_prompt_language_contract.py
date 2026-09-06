import re
import unittest
from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().parents[1] / 'prompt'
SUPPORTED_LANGUAGES = {
    'zh': 'Simplified Chinese',
    'en': 'English',
    'es': 'Spanish',
    'jp': 'Japanese',
    'de': 'German',
    'fr': 'French',
    'nl': 'Dutch',
    'da': 'Danish',
    'nb': 'Norwegian Bokmål',
    'it': 'Italian',
}


class PromptLanguageContractTests(unittest.TestCase):
    def test_candidate_prompts_declare_the_product_language_mapping(self):
        prompt_paths = sorted(path for path in PROMPT_DIR.iterdir() if path.is_file())
        self.assertGreater(len(prompt_paths), 0)
        for path in prompt_paths:
            if path.name == 'haiku-4-5':
                # The non-opt Haiku prompt is an exact snapshot of the current
                # production control and must not be altered for this contract.
                continue
            content = path.read_text(encoding='utf-8')
            with self.subTest(prompt=path.name):
                for code, language in SUPPORTED_LANGUAGES.items():
                    mapping = re.compile(
                        rf'(?m)^(?:-\s+`?{re.escape(code)}`?\s*:|'
                        rf'{re.escape(code)}\s*=)\s*{re.escape(language)}\s*$',
                    )
                    self.assertRegex(content, mapping)

    def test_no_prompt_contains_the_old_no_language_patch(self):
        for path in sorted(PROMPT_DIR.iterdir()):
            if not path.is_file():
                continue
            content = path.read_text(encoding='utf-8')
            with self.subTest(prompt=path.name):
                self.assertNotIn('`no` ALWAYS means Norwegian', content)
                self.assertNotIn('`no` and `nb` are aliases', content)


if __name__ == '__main__':
    unittest.main()
