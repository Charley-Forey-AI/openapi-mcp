import { useMemo, useState } from "react";
import { enumerateOperations, parseSpecText, type OpRow } from "./openapiOps";

export function App() {
  const [raw, setRaw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ops, setOps] = useState<OpRow[] | null>(null);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());

  const load = () => {
    setError(null);
    setOps(null);
    setSelected(new Set());
    try {
      const spec = parseSpecText(raw);
      if (!("openapi" in spec) && !("swagger" in spec)) {
        throw new Error("Not an OpenAPI document (need openapi or swagger at top level)");
      }
      setOps(enumerateOperations(spec));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const filtered = useMemo(() => {
    if (!ops) return [];
    const q = filter.trim().toLowerCase();
    if (!q) return ops;
    return ops.filter(
      (o) =>
        o.path.toLowerCase().includes(q) ||
        o.operation_key.toLowerCase().includes(q) ||
        o.tags.some((t) => t.toLowerCase().includes(q)) ||
        (o.operation_id && o.operation_id.toLowerCase().includes(q))
    );
  }, [ops, filter]);

  const toggle = (key: string) => {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });
  };

  const selectAllVisible = () => {
    setSelected((prev) => {
      const n = new Set(prev);
      for (const o of filtered) n.add(o.operation_key);
      return n;
    });
  };

  const clearSelected = () => setSelected(new Set());

  const exportJson = useMemo(() => {
    const keys = [...selected].sort();
    return JSON.stringify({ include_operation_keys: keys }, null, 2);
  }, [selected]);

  return (
    <div className="wrap">
      <h1>OpenAPI endpoint picker</h1>
      <p className="lead">
        Paste an OpenAPI JSON or YAML spec. Load operations, tick the endpoints to keep, then
        copy the JSON for the MCP tool <code>export_trimmed_openapi_spec</code> (parameter{" "}
        <code>include_operation_keys</code>) together with <code>spec_url</code>, or use the same
        array in your own trim pipeline.
      </p>
      <label>
        <strong>Spec (JSON or YAML)</strong>
        <textarea
          className="textarea"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          spellCheck={false}
          placeholder='{ "openapi": "3.0.0", ... }'
        />
      </label>
      <div>
        <button type="button" className="btn" onClick={load}>
          Load operations
        </button>
      </div>
      {error ? <div className="err">{error}</div> : null}
      {ops && ops.length === 0 ? <p className="lead">No operations found in paths.</p> : null}
      {ops && ops.length > 0 ? (
        <>
          <p className="lead" style={{ marginTop: "1rem" }}>
            {ops.length} operation(s). Selected: {selected.size}
          </p>
          <div className="tools">
            <input
              className="filter"
              type="search"
              placeholder="Filter by path, tag, operationId..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <button type="button" className="btn btn-ghost" onClick={selectAllVisible}>
              Select all in filter
            </button>
            <button type="button" className="btn btn-ghost" onClick={clearSelected}>
              Clear selection
            </button>
          </div>
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 40 }}>Keep</th>
                  <th>operation_key</th>
                  <th>Tags</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((o) => (
                  <tr key={o.operation_key}>
                    <td>
                      <input
                        type="checkbox"
                        checked={selected.has(o.operation_key)}
                        onChange={() => toggle(o.operation_key)}
                        aria-label={`Keep ${o.operation_key}`}
                      />
                    </td>
                    <td>
                      <code>{o.operation_key}</code>
                    </td>
                    <td>{o.tags.length ? o.tags.join(", ") : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h2 style={{ fontSize: "1rem", marginTop: "1rem" }}>Export</h2>
          <p className="lead">
            Pass this object as the tool input along with <code>spec_url</code> (same document you
            pasted, hosted at a URL the MCP can fetch), or use the list from your workflow.
          </p>
          <div className="out">{exportJson}</div>
          <button
            type="button"
            className="btn"
            disabled={selected.size === 0}
            onClick={() => navigator.clipboard.writeText(exportJson)}
          >
            Copy to clipboard
          </button>
        </>
      ) : null}
    </div>
  );
}
