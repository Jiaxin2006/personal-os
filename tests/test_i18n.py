"""Backend messages and the default plan follow the interface language."""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from personal_os import i18n  # noqa: E402

CJK = re.compile(r'[㐀-鿿　-〿＀-￯]')
PLACEHOLDER = re.compile(r'%s|\{\w+\}')


def chinese_strings(path):
    """(line, text, is_f_string) for Chinese strings in code, skipping docstrings."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body
                  and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and CJK.search(ast.unparse(node)):
            yield node.lineno, ast.unparse(node), True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and CJK.search(node.value) \
                and id(node) not in docstrings:
            yield node.lineno, node.value, False


class TranslationTableTests(unittest.TestCase):
    def test_every_backend_message_has_english(self):
        # An f-string cannot be looked up; use _('…{name}…').format(name=…) instead.
        missing = ['%s:%d %s' % (path.name, line, text)
                   for path in sorted((PROJECT / 'personal_os').glob('*.py')) if path.name != 'i18n.py'
                   for line, text, formatted in chinese_strings(path) if formatted or text not in i18n.EN]
        self.assertEqual(missing, [])

    def test_default_plan_has_english(self):
        profile = json.loads((PROJECT / 'personal_os/initial_profile.json').read_text(encoding='utf-8'))
        texts = [profile['name']] + [item[key] for group in ('categories', 'goals', 'task_templates')
                                     for item in profile[group] for key in ('name', 'description') if key in item]
        self.assertEqual([text for text in texts if text not in i18n.EN], [])

    def test_translations_keep_placeholders(self):
        for chinese, english in i18n.EN.items():
            self.assertEqual(sorted(PLACEHOLDER.findall(chinese)), sorted(PLACEHOLDER.findall(english)), chinese)
            self.assertFalse(CJK.search(english), english)


class LanguageTests(unittest.TestCase):
    def request(self, language, payload, folder=None):
        if folder is None:
            with tempfile.TemporaryDirectory() as temporary:
                return self.request(language, payload, temporary)
        (Path(folder) / 'bar').mkdir(exist_ok=True)
        env = dict(os.environ, HOME=folder, PERSONAL_OS_DATA_DIR=folder + '/app', SKETCHYBAR_DATA_DIR=folder + '/bar',
                   PERSONAL_OS_NO_BAR='1', PERSONAL_OS_LANGUAGE=language)
        result = subprocess.run([sys.executable, str(PROJECT / 'personal_os/cli.py')], input=json.dumps(payload),
                                text=True, capture_output=True, cwd=PROJECT, env=env, timeout=20)
        return json.loads(result.stdout)

    def test_new_plan_and_errors_in_english(self):
        profile = self.request('en', {'action': 'snapshot'})['profile']
        self.assertEqual(profile['name'], 'My weekly plan')
        self.assertIn('Research', [category['name'] for category in profile['categories']])
        self.assertIn('Weekly time review', [task['name'] for task in profile['task_templates']])
        self.assertEqual(self.request('en', {'action': 'no-such-action'})['error'], 'Unknown action')
        failure = self.request('en', {'action': 'add_activity', 'day': 'soon', 'category': 'reading', 'seconds': 60})
        self.assertEqual(failure['error'], 'Activity date must be a YYYY-MM-DD date')

    def test_chinese_by_default(self):
        profile = self.request('', {'action': 'snapshot'})['profile']
        self.assertEqual(profile['name'], '我的每周计划')
        self.assertEqual(self.request('zh', {'action': 'no-such-action'})['error'], '未知操作')

    def test_existing_builtin_labels_follow_the_language_without_rewriting_profile(self):
        with tempfile.TemporaryDirectory() as workspace:
            def request(language, action, **payload):
                return self.request(language, dict(action=action, **payload), workspace)

            chinese = request('zh', 'snapshot')
            profile = chinese['profile']
            profile['categories'][0]['name'] = '自定科研'
            self.assertTrue(request('zh', 'save_profile', profile=profile)['ok'])
            self.assertTrue(request('zh', 'save_review', week_start=chinese['week_start'],
                                    text='示例复盘', completed=True)['ok'])

            english = request('en', 'snapshot')
            profile = english['profile']
            self.assertEqual(profile['name'], 'My weekly plan')
            self.assertEqual(profile['categories'][0]['name'], '自定科研')
            self.assertIn('Reading', [item['name'] for item in profile['categories']])
            self.assertIn('Total work', [goal['name'] for goal in english['statistics']['goals']])
            self.assertIn('Weekly time review', [task['name'] for task in english['tasks']])
            review = english['reviews'][0]
            self.assertEqual(review['text'], '示例复盘')
            self.assertIn('Total work', [goal['name'] for goal in review['statistics']['goals']])

            self.assertTrue(request('en', 'save_profile', profile=profile)['ok'])
            restored = request('zh', 'snapshot')
            self.assertEqual(restored['profile']['revision'], profile['revision'])
            self.assertIn('总工作投入', [goal['name'] for goal in restored['statistics']['goals']])


if __name__ == '__main__':
    unittest.main()
