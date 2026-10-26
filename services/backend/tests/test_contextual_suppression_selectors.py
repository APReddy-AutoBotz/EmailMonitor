"""Locked selector-engine proof on authored nodes; not genuine browser acceptance."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import playwright
import pytest
from playwright._impl._locator import get_by_label_selector
from playwright.async_api import Locator, Page


@pytest.mark.parametrize("address", ["Authored.Contact@example.org", "Authored+tag@example.org"])
def test_selectors_match_wrapped_label_and_exact_address_boundary(address: str) -> None:
    from operator_ui_acceptance import suppression_address_cells, suppression_reason

    labels = []
    filters = []
    paths = []
    page = SimpleNamespace(get_by_label=lambda *args, **kwargs: labels.append((args, kwargs)))

    def locate(path: str) -> SimpleNamespace:
        paths.append(path)
        return SimpleNamespace(filter=lambda **kwargs: filters.append(kwargs))

    table = SimpleNamespace(locator=locate)
    suppression_reason(cast(Page, page))
    suppression_address_cells(cast(Locator, table), address)
    args, kwargs = labels[0]
    selector = get_by_label_selector(*args, **kwargs).removeprefix("internal:label=")
    assert paths == ["tbody tr td:nth-child(3)"]
    pattern = filters[0]["has_text"].pattern
    # Execute the installed, locked Playwright text collector and matcher. The
    # minimal node objects model only the authored wrapping label and cell; no
    # browser is launched and no hosted guard or application authority is changed.
    bundle = Path(playwright.__file__).parent / "driver/package/lib/coreBundle.js"
    program = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const bundle = fs.readFileSync(process.argv[1], 'utf8');
const start = bundle.indexOf("source4 = '") + 'source4 = '.length;
if(start < 'source4 = '.length) throw Error('locked injected source missing');
let end = start + 1;
for(;end < bundle.length;end++) {
 if(bundle[end] === '\\') {end++;continue;}
 if(bundle[end] === "'") break;
}
const source = vm.runInNewContext(bundle.slice(start,end+1));
const fn = name => {
 const start = source.indexOf('function '+name+'(');
 return source.slice(start,source.indexOf('\nfunction ',start+1));
};
const normalizeWhiteSpace = s => s.replace(/\s+/g,' ').trim();
const shouldSkipForTextMatching = () => false;
class HTMLInputElement {};
const Node = {TEXT_NODE:3,COMMENT_NODE:8,ELEMENT_NODE:1};
eval(fn('elementText'));
const tail = source.slice(source.indexOf('function createTextMatcher('));
eval(tail.slice(0,tail.indexOf('\nvar ')));
function element(children) {
 const e={nodeType:1,shadowRoot:null};
 children.forEach((c,i)=>c.nextSibling=children[i+1]||null);
 e.firstChild=children[0]||null;return e;
}
const text=s=>({nodeType:3,nodeValue:s});
const label=element([text('Suppression reason'),element([
 element([text('Choose a reason')]),element([text('Privacy request')]),
 element([text('Source restriction')])])]);
const cell = address => element([text(address),element([]),
 element([text('Normalized: '+address.toLowerCase())])]);
const l=elementText(new Map(),label);
const c=elementText(new Map(),cell(input.address));
const other=elementText(new Map(),cell('prefix'+input.address));
const longer=elementText(new Map(),cell(input.address+'.invalid'));
const match=createTextMatcher('/'+input.pattern+'/',true).matcher;
console.log(JSON.stringify({
 oldLabel:createTextMatcher(JSON.stringify('Suppression reason')+'s',true).matcher(l),
 newLabel:createTextMatcher(input.selector,true).matcher(l),
 oldAddress:createTextMatcher(JSON.stringify(input.address)+'s',true).matcher(c),
 newAddress:match(c), other:match(other), longer:match(longer)
}));
"""
    result = subprocess.run(
        ["node", "-e", program, str(bundle)],
        input=json.dumps({"address": address, "selector": selector, "pattern": pattern}),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == {
        "oldLabel": False,
        "newLabel": True,
        "oldAddress": False,
        "newAddress": True,
        "other": False,
        "longer": False,
    }
