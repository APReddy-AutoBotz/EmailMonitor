export default function App() {
  return (
    <main>
      <header><p className="eyebrow">Academic contact research</p><h1>EmailMonitor</h1></header>
      <section aria-labelledby="status-title" className="notice">
        <h2 id="status-title">Extraction is not implemented</h2>
        <p>This is the EM-001 development scaffold. No live searches, contact results,
          tenant login, exports, outbound email or external AI are available.</p>
      </section>
      <section aria-labelledby="input-title">
        <h2 id="input-title">Plan a research job</h2>
        <p>Keyword and URL workflows will become available after tenant and source protections.</p>
        <fieldset disabled aria-describedby="status-title">
          <legend>Research input (unavailable)</legend>
          <label htmlFor="keyword">Keyword</label>
          <input id="keyword" name="keyword" placeholder="Enter a research topic" />
          <label htmlFor="source">Source</label>
          <select id="source" name="source"><option>No approved sources available</option></select>
          <label htmlFor="url">Or an article, search-results or PDF URL</label>
          <input id="url" name="url" type="url" placeholder="https://…" />
          <button type="button">Start extraction (unavailable)</button>
        </fieldset>
      </section>
      <section aria-labelledby="results-title">
        <h2 id="results-title">Results</h2><p>No extraction jobs have run. No contact records are shown.</p>
      </section>
      <footer>First author, corresponding author, observed email, identity association,
        technical validation and outreach eligibility will remain separate.</footer>
    </main>
  )
}
