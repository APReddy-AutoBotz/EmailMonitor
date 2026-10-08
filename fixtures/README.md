# Synthetic fixture pack

These files are authored test examples, not harvested publisher pages or real contact data. Names, institutions, article titles, dates and addresses are synthetic. All addresses and source URLs use reserved example domains. No DNS lookup, mail send, live publisher call or identity claim is authorized by a fixture.

## Scenario

`html/search-page-1.html` links to article A, article B and page 2. Page 2 repeats article A and links to the tooltip article and no-contact article. Expected result: four unique articles and four corresponding-author address associations, not five unique articles and not the footer support mailbox.

Article A: Mira Rao is first author; Alex Chen is corresponding. Mira must not receive Alex's address.

Article B: Ravi Das is both first and corresponding; Noor Ibrahim is also corresponding, with a different address.

Tooltip article: Elena Park is first/corresponding. A public address becomes DOM text after hover/focus. The static extractor must not scan arbitrary JavaScript strings as contact evidence; the browser fixture route exercises the actual reveal.

No-contact article: Leena Shah is first; no correspondence/email is declared. Preserve the article as no-contact, not a failed job or invented address.

`expected/results.json` contains manually authored expected outcomes. It is a specification for future connector/E2E tests, not an executed extraction result. The contact schema example uses the exact SHA-256 of `html/article-a.html` for consistency.

## Harness boundaries

EM-001 creates an offline transport or isolated fixture server mapping the synthetic source host to these bytes. Production must reject that test mode. Do not weaken production URL/egress validation to serve fixtures. No external resources are required by these pages.

EM-008 adds generated synthetic PDFs and parser tests. The baseline deliberately contains no publisher PDFs or application extractor. See [test strategy](../docs/14-test-strategy-and-benchmark.md) for missing adversarial cases that implementation must add.
