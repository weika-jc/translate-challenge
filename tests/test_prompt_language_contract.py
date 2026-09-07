import re
import unittest
from pathlib import Path

from evaluate.evaluation_prompt import (
    EVALUATION_PROMPT_DIR,
    PROMPT_NAMES,
    build_evaluation_prompt,
)


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
LUNA_DIRECT_EXECUTION_BLOCK = (
    '# Execution Mode\n'
    'This is a direct translation task that does not require reasoning, analysis, '
    'or explanation. Translate immediately and return only the required JSON result.\n\n'
)


class PromptLanguageContractTests(unittest.TestCase):
    def test_haiku_opt_cache_only_adds_real_world_examples(self):
        marker = '  <!-- Real-world chat examples -->\n'
        for directory in (PROMPT_DIR, EVALUATION_PROMPT_DIR):
            baseline = (directory / 'haiku-4-5-opt').read_text(encoding='utf-8')
            variant = (directory / 'haiku-4-5-opt-cache').read_text(
                encoding='utf-8'
            )
            prefix, real_world = variant.split(marker, 1)
            _, suffix = real_world.split('</examples>', 1)
            with self.subTest(directory=directory.name):
                self.assertEqual(prefix + '</examples>' + suffix, baseline)

    def test_haiku_opt_cache_examples_cycle_through_all_target_languages(self):
        expected_targets = list(SUPPORTED_LANGUAGES) * 3
        for directory in (PROMPT_DIR, EVALUATION_PROMPT_DIR):
            content = (directory / 'haiku-4-5-opt-cache').read_text(
                encoding='utf-8'
            )
            section = content.split(
                '  <!-- Real-world chat examples -->\n', 1,
            )[1]
            section = section.split('</examples>', 1)[0]
            targets = re.findall(
                r'(?m)^    <input>.* -> (zh|en|es|jp|de|fr|nl|da|nb|it)</input>$',
                section,
            )
            with self.subTest(directory=directory.name):
                self.assertEqual(targets, expected_targets)

    def test_luna_no_reasoning_variant_only_adds_direct_execution_instruction(self):
        for directory in (PROMPT_DIR, EVALUATION_PROMPT_DIR):
            baseline = (directory / 'gpt-5-6-luna').read_text(encoding='utf-8')
            variant = (directory / 'gpt-5-6-luna-no-reasoning').read_text(
                encoding='utf-8'
            )
            expected = baseline.replace(
                '# Input Contract\n',
                f'{LUNA_DIRECT_EXECUTION_BLOCK}# Input Contract\n',
                1,
            )
            with self.subTest(directory=directory.name):
                self.assertEqual(variant, expected)

    def test_evaluation_prompts_only_remove_profanity_suppression(self):
        evaluation_names = {
            path.name for path in EVALUATION_PROMPT_DIR.iterdir() if path.is_file()
        }
        self.assertEqual(evaluation_names, set(PROMPT_NAMES))
        for prompt_name in PROMPT_NAMES:
            production = (PROMPT_DIR / prompt_name).read_text(encoding='utf-8')
            evaluation = (EVALUATION_PROMPT_DIR / prompt_name).read_text(encoding='utf-8')
            with self.subTest(prompt=prompt_name):
                self.assertEqual(
                    evaluation,
                    build_evaluation_prompt(prompt_name, production),
                )
                self.assertNotIn('inappropriate language', evaluation)
                self.assertNotIn('不文明用语', evaluation)
                self.assertNotIn('****', evaluation)

    def test_candidate_prompts_declare_the_product_language_mapping(self):
        prompt_paths = sorted(
            path
            for directory in (PROMPT_DIR, EVALUATION_PROMPT_DIR)
            for path in directory.iterdir()
            if path.is_file()
        )
        self.assertGreater(len(prompt_paths), 0)
        for path in prompt_paths:
            if path.name == 'haiku-4-5':
                # The non-opt Haiku prompt is an exact production snapshot whose
                # language codes are expressed by its terminology table.
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
        prompt_paths = [
            path
            for directory in (PROMPT_DIR, EVALUATION_PROMPT_DIR)
            for path in sorted(directory.iterdir())
            if path.is_file()
        ]
        for path in prompt_paths:
            content = path.read_text(encoding='utf-8')
            with self.subTest(prompt=path.name):
                self.assertNotIn('`no` ALWAYS means Norwegian', content)
                self.assertNotIn('`no` and `nb` are aliases', content)


if __name__ == '__main__':
    unittest.main()
