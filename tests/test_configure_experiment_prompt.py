import unittest

from evaluate.configure_experiment_prompt import (
    EXPERIMENT_PROMPT_ID,
    build_variant,
)


class ConfigureExperimentPromptTests(unittest.TestCase):
    def test_tool_is_hard_scoped_to_the_experiment_prompt(self):
        self.assertEqual(EXPERIMENT_PROMPT_ID, '7ZJL56AKIU')

    def test_builds_default_chat_variant_with_optional_cache(self):
        cached = build_variant('system text', 'model-id', True)
        uncached = build_variant('system text', 'model-id', False)

        self.assertEqual(cached['modelId'], 'model-id')
        self.assertEqual(
            cached['templateConfiguration']['chat']['messages'][0]['content'][0]['text'],
            '{{input}}',
        )
        self.assertEqual(
            cached['templateConfiguration']['chat']['system'],
            [{'text': 'system text'}, {'cachePoint': {'type': 'default'}}],
        )
        self.assertEqual(
            uncached['templateConfiguration']['chat']['system'],
            [{'text': 'system text'}],
        )
        self.assertNotIn('additionalModelRequestFields', uncached)

    def test_builds_console_reasoning_configuration(self):
        variant = build_variant('system text', 'model-id', False, True)

        self.assertEqual(
            variant['inferenceConfiguration'],
            {'text': {'temperature': 1.0, 'topP': 1.0}},
        )
        self.assertEqual(
            variant['additionalModelRequestFields'],
            {'thinking': {'type': 'enabled', 'budget_tokens': 1024}},
        )


if __name__ == '__main__':
    unittest.main()
