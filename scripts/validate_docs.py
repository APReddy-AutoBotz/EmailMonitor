#!/usr/bin/env python3
"""Validate the documentation pack offline; this does not test the application."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> object:
    def unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_keys)


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == 'a':
            self.links.append(dict(attrs))


def main() -> int:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:
        print('ERROR: install docs dependencies: python -m pip install -r scripts/requirements-docs.txt')
        return 2

    errors: list[str] = []
    md_files = set(ROOT.glob('*.md'))
    for directory in ('docs', 'contracts', 'fixtures', '.github'):
        md_files.update((ROOT / directory).rglob('*.md'))
    local_link_count = 0
    for path in sorted(md_files):
        text = re.sub(r'```.*?```', '', path.read_text(encoding='utf-8'), flags=re.S)
        for raw in re.findall(r'\[[^\]]*\]\(([^)]+)\)', text):
            target = raw.strip().split()[0].strip('<>')
            parsed = urlsplit(target)
            if parsed.scheme or target.startswith('#'):
                continue
            relative = unquote(parsed.path)
            if not relative:
                continue
            resolved = (path.parent / relative).resolve()
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                errors.append(f'{path.relative_to(ROOT)}: link escapes repository: {target}')
                continue
            local_link_count += 1
            if not resolved.exists():
                errors.append(f'{path.relative_to(ROOT)}: missing link target: {target}')

    json_paths = sorted(set((ROOT / 'contracts').rglob('*.json')) | set((ROOT / 'fixtures').rglob('*.json')))
    for path in json_paths:
        try:
            load_json(path)
        except (ValueError, OSError) as exc:
            errors.append(f'{path.relative_to(ROOT)}: {exc}')
    if errors:
        for error in errors:
            print(f'FAIL: {error}')
        return 1

    validators = {}
    for path in sorted((ROOT / 'contracts').glob('*.schema.json')):
        schema = load_json(path)
        try:
            Draft202012Validator.check_schema(schema)
            validators[path.name] = Draft202012Validator(schema, format_checker=FormatChecker())
        except Exception as exc:
            errors.append(f'{path.name}: invalid schema: {exc}')

    examples = {
        'keyword-job.json': 'job-request.schema.json',
        'url-job.json': 'job-request.schema.json',
        'contact-record.json': 'contact-record.schema.json',
        'source-policy.json': 'source-policy.schema.json',
        'event.json': 'event.schema.json',
    }
    loaded = {}
    for name, schema_name in examples.items():
        instance = load_json(ROOT / 'contracts' / 'examples' / name)
        loaded[name] = instance
        validator = validators.get(schema_name)
        if validator is None:
            errors.append(f'{name}: missing valid schema {schema_name}')
            continue
        for error in validator.iter_errors(instance):
            location = '.'.join(map(str, error.absolute_path))
            errors.append(f'{name}:{location}: {error.message}')

    negative_count = 0
    def rejects(schema_name: str, instance: object, label: str) -> None:
        nonlocal negative_count
        validator = validators.get(schema_name)
        if validator is None or validator.is_valid(instance):
            errors.append(f'negative contract case incorrectly accepted: {label}')
        negative_count += 1

    bad = copy.deepcopy(loaded['keyword-job.json']); del bad['input']['source_id']
    rejects('job-request.schema.json', bad, 'keyword missing source')
    bad = copy.deepcopy(loaded['keyword-job.json']); bad['organization_id'] = 'client-must-not-grant-tenant-access'
    rejects('job-request.schema.json', bad, 'unknown tenant body field')
    bad = copy.deepcopy(loaded['url-job.json']); bad['input']['url'] = 'file:///etc/passwd'
    rejects('job-request.schema.json', bad, 'non-HTTP URL')
    bad = copy.deepcopy(loaded['keyword-job.json']); bad['options']['max_articles'] = 0
    rejects('job-request.schema.json', bad, 'zero article cap')
    bad = copy.deepcopy(loaded['keyword-job.json']); bad['options']['allow_ocr'] = True
    rejects('job-request.schema.json', bad, 'deferred OCR enabled')
    bad = copy.deepcopy(loaded['contact-record.json']); bad['evidence'] = []
    rejects('contact-record.schema.json', bad, 'accepted association without evidence')
    bad = copy.deepcopy(loaded['contact-record.json']); bad['email'] = None
    rejects('contact-record.schema.json', bad, 'accepted association without email')
    bad = copy.deepcopy(loaded['contact-record.json']); bad['association']['state'] = 'suppressed'
    rejects('contact-record.schema.json', bad, 'suppressed but export eligible')
    bad = copy.deepcopy(loaded['contact-record.json']); bad['association']['calibrated_probability'] = 0.99
    rejects('contact-record.schema.json', bad, 'unsupported calibrated probability')
    bad = copy.deepcopy(loaded['source-policy.json']); bad['state'] = 'revoked'
    rejects('source-policy.schema.json', bad, 'revoked policy permits exports')
    bad = copy.deepcopy(loaded['source-policy.json']); bad['permission_reference'] = None
    rejects('source-policy.schema.json', bad, 'approved policy without permission reference')
    bad = copy.deepcopy(loaded['event.json']); bad['payload']['email'] = 'private@example.org'
    rejects('event.schema.json', bad, 'PII field in event payload')

    prd = (ROOT / 'docs/02-product-requirements.md').read_text(encoding='utf-8')
    trace = (ROOT / 'docs/17-acceptance-and-traceability.md').read_text(encoding='utf-8')
    requirement_counts = {}
    for prefix in ('FR', 'NFR'):
        expected = set(re.findall(rf'\b{prefix}-\d{{3}}\b', prd))
        actual = set(re.findall(rf'\b{prefix}-\d{{3}}\b', trace))
        requirement_counts[prefix] = len(expected)
        if expected != actual:
            errors.append(f'{prefix} traceability mismatch: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}')
    brd = (ROOT / 'docs/01-business-requirements.md').read_text(encoding='utf-8')
    if set(re.findall(r'\bBR-\d{2}\b', brd)) != set(re.findall(r'\bBR-\d{2}\b', trace)):
        errors.append('Business requirement traceability mismatch')
    backlog = (ROOT / 'docs/16-delivery-backlog.md').read_text(encoding='utf-8')
    status = (ROOT / 'docs/22-implementation-status.md').read_text(encoding='utf-8')
    for number in range(1, 19):
        task = f'EM-{number:03d}'
        if task not in backlog or task not in status:
            errors.append(f'Missing backlog/status task: {task}')

    fixture_dir = ROOT / 'fixtures/html'
    html_paths = sorted(fixture_dir.glob('*.html'))
    article_links: list[str] = []
    for path in html_paths:
        parser = Links(); content = path.read_text(encoding='utf-8'); parser.feed(content)
        for item in parser.links:
            href = item.get('href') or ''
            parsed = urlsplit(href)
            if not parsed.scheme and parsed.path:
                if not (path.parent / unquote(parsed.path)).is_file():
                    errors.append(f'{path.name}: broken fixture link {href}')
            if path.name.startswith('search-page') and item.get('class') == 'article-link':
                article_links.append(parsed.path)
        for domain in re.findall(r'@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', content):
            if domain[1:] not in ('example.org', 'example.com', 'example.net'):
                errors.append(f'{path.name}: non-synthetic contact domain {domain}')
    expected = load_json(ROOT / 'fixtures/expected/results.json')
    expected_paths = {item['path'] for item in expected['articles']}
    if set(article_links) != expected_paths or len(set(article_links)) != expected['expected_unique_articles']:
        errors.append('Fixture discovered-article specification mismatch')
    if len(article_links) != expected['source_reported_entries']:
        errors.append('Fixture result-entry count mismatch')
    pair_count = sum(len(item['corresponding_authors']) for item in expected['articles'])
    if pair_count != expected['expected_corresponding_email_pairs']:
        errors.append('Fixture expected author-email pair count mismatch')
    digest = hashlib.sha256((fixture_dir / 'article-a.html').read_bytes()).hexdigest()
    if loaded['contact-record.json']['evidence'][0]['content_sha256'] != digest:
        errors.append('Synthetic article-a evidence digest mismatch')
    if loaded['source-policy.json']['execution_mode'] != 'fixture':
        errors.append('Example source policy must be fixture-only')

    print(f'Markdown documents: {len(md_files)}; local link targets checked: {local_link_count}')
    print(f'JSON files parsed: {len(json_paths)}; schemas: {len(validators)}; valid examples: {len(examples)}')
    print(f'Negative contract cases: {negative_count}; FR traceability: {requirement_counts["FR"]}; NFR traceability: {requirement_counts["NFR"]}')
    print(f'Core tasks present: 18; HTML fixtures: {len(html_paths)}; unique fixture articles: {len(expected_paths)}; expected contact pairs: {pair_count}')
    if errors:
        for error in errors:
            print(f'FAIL: {error}')
        return 1
    print('PASS: documentation, contracts, examples, traceability and fixture consistency checks.')
    print('NOT TESTED: application behavior, live extraction, security enforcement, legal permission, deployment or benchmark performance.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
