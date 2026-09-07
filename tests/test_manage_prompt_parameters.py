import unittest
from unittest.mock import Mock

from evaluate.manage_prompt_parameters import (
    _delete_path,
    _public_model_id,
    _set_path,
    build_updated_variants,
    update_parameters,
)


def _prompt() -> dict:
    return {
        'id': 'example-id',
        'name': 'translation',
        'description': 'test',
        'customerEncryptionKeyArn': 'arn:aws:kms:us-west-2:000000000000:'
        'key/00000000-0000-0000-0000-000000000000',
        'defaultVariant': 'variantOne',
        'variants': [{
            'name': 'variantOne',
            'modelId': 'arn:aws:bedrock:region:000000000000:'
            'inference-profile/us.openai.gpt-5.6-luna',
            'templateType': 'CHAT',
            'templateConfiguration': {
                'chat': {
                    'inputVariables': [{'name': 'input'}],
                    'messages': [{
                        'role': 'user',
                        'content': [{'text': '{{input}}'}],
                    }],
                    'system': [{'text': 'system prompt'}],
                },
            },
            'inferenceConfiguration': {
                'text': {
                    'maxTokens': 300,
                    'temperature': 1.0,
                    'stopSequences': ['END'],
                },
            },
            'additionalModelRequestFields': {'top_k': 250.0},
        }],
    }


class ManagePromptParametersTests(unittest.TestCase):
    def test_public_model_id_redacts_inference_profile_arn(self):
        model_id = _prompt()['variants'][0]['modelId']

        self.assertEqual(_public_model_id(model_id), 'us.openai.gpt-5.6-luna')

    def test_set_and_delete_nested_parameters(self):
        state = {'inference': None, 'additional': {'thinking': {'budget': 10}}}

        _set_path(state, 'inference.maxTokens', 300)
        _set_path(state, 'additional.thinking.type', 'enabled')
        _delete_path(state, 'additional.thinking.budget')

        self.assertEqual(state['inference'], {'maxTokens': 300})
        self.assertEqual(state['additional'], {'thinking': {'type': 'enabled'}})

    def test_luna_parameters_remove_unsupported_fields_only(self):
        prompt = _prompt()

        variants = build_updated_variants(prompt, {
            'inference': {'maxTokens': 300},
            'additional': None,
        })

        variant = variants[0]
        self.assertEqual(
            variant['inferenceConfiguration'],
            {'text': {'maxTokens': 300}},
        )
        self.assertNotIn('additionalModelRequestFields', variant)
        self.assertEqual(
            variant['templateConfiguration'],
            prompt['variants'][0]['templateConfiguration'],
        )
        self.assertEqual(variant['modelId'], prompt['variants'][0]['modelId'])

    def test_update_reloads_and_verifies_prompt(self):
        original = _prompt()
        verified = _prompt()
        verified['variants'][0]['inferenceConfiguration'] = {
            'text': {'maxTokens': 300},
        }
        verified['variants'][0].pop('additionalModelRequestFields')
        client = Mock()
        client.get_prompt.side_effect = [original, verified]

        result = update_parameters(
            client,
            'example-id',
            original,
            {'inference': {'maxTokens': 300}, 'additional': None},
        )

        self.assertIs(result, verified)
        update = client.update_prompt.call_args.kwargs
        self.assertEqual(update['promptIdentifier'], 'example-id')
        self.assertEqual(
            update['customerEncryptionKeyArn'],
            original['customerEncryptionKeyArn'],
        )
        self.assertEqual(
            update['variants'][0]['inferenceConfiguration'],
            {'text': {'maxTokens': 300}},
        )
        self.assertNotIn(
            'additionalModelRequestFields', update['variants'][0],
        )


if __name__ == '__main__':
    unittest.main()
