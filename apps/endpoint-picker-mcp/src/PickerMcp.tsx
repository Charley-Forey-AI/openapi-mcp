import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { useApp } from "@modelcontextprotocol/ext-apps/react";
import { useMemo, useState } from "react";

type OpRow = {
  operation_key: string;
  method: string;
  path: string;
  tags: string[];
  operation_id: string | null;
};

type Payload = {
  ok: boolean;
  spec_url?: string;
  platform_max_openapi_operations?: number;
  operation_count?: number;
  operations?: OpRow[];
  error?: string;
  message?: string;
};

function parseToolPayload(result: CallToolResult): Payload | null {
  if (result.isError) {
    return null;
  }
  const sc = result.structuredContent;
  if (sc && typeof sc === "object" && !Array.isArray(sc)) {
    return sc as Payload;
  }
  const textBlock = result.content?.find(
    (c): c is { type: "text"; text: string } => c.type === "text" && "text" in c,
  );
  if (textBlock?.type === "text" && typeof textBlock.text === "string") {
    try {
      return JSON.parse(textBlock.text) as Payload;
    } catch {
      return null;
    }
  }
  return null;
}

export function PickerMcp() {
  const [rows, setRows] = useState<OpRow[]>([]);
  const [specUrl, setSpecUrl] = useState("");
  const [platformMax, setPlatformMax] = useState(50);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState(false);
  const [exportResult, setExportResult] = useState<string | null>(null);

  const { app, isConnected, error: connectErr } = useApp({
    appInfo: { name: "openapi-endpoint-picker", version: "0.1.0" },
    capabilities: {},
    onAppCreated: (a) => {
      a.ontoolinput = (params) => {
        const args = params.arguments as { spec_url?: string } | undefined;
        if (args?.spec_url) {
          setSpecUrl(args.spec_url);
        }
      };
      a.ontoolresult = (params) => {
        const p = parseToolPayload(params as unknown as CallToolResult);
        if (!p) {
          setError("Could not parse tool result");
          setRows([]);
          return;
        }
        if (!p.ok) {
          setError(p.message ?? p.error ?? "Request failed");
          setRows([]);
          return;
        }
        setError(null);
        setSpecUrl(p.spec_url ?? "");
        setPlatformMax(p.platform_max_openapi_operations ?? 50);
        setRows(p.operations ?? []);
        setSelected(new Set());
        setExportResult(null);
      };
    },
  });

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) {
      return rows;
    }
    return rows.filter(
      (o) =>
        o.path.toLowerCase().includes(q) ||
        o.operation_key.toLowerCase().includes(q) ||
        o.tags.some((t) => t.toLowerCase().includes(q)) ||
        (o.operation_id && o.operation_id.toLowerCase().includes(q)),
    );
  }, [rows, filter]);

  const toggle = (key: string) => {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(key)) {
        n.delete(key);
      } else {
        n.add(key);
      }
      return n;
    });
  };

  const selectAllVisible = () => {
    setSelected((prev) => {
      const n = new Set(prev);
      for (const o of filtered) {
        n.add(o.operation_key);
      }
      return n;
    });
  };

  const clearSelected = () => setSelected(new Set());

  const exportJson = useMemo(() => {
    const keys = [...selected].sort();
    return JSON.stringify({ include_operation_keys: keys }, null, 2);
  }, [selected]);

  const overCap = selected.size > platformMax;

  const runExport = async () => {
    if (!app || !specUrl || selected.size === 0) {
      return;
    }
    setExportBusy(true);
    setExportResult(null);
    try {
      const result = await app.callServerTool({
        name: "export_trimmed_openapi_spec",
        arguments: {
          spec_url: specUrl,
          include_operation_keys: [...selected].sort(),
        },
      });
      setExportResult(JSON.stringify(result, null, 2));
    } catch (e) {
      setExportResult(e instanceof Error ? e.message : String(e));
    } finally {
      setExportBusy(false);
    }
  };

  const copyExport = async () => {
    if (!exportResult) {
      return;
    }
    try {
      await navigator.clipboard.writeText(exportResult);
    } catch {
      /* host may deny clipboard */
    }
  };

  if (connectErr) {
    return (
      <div className="wrap">
        <div className="err">Connection error: {connectErr.message}</div>
      </div>
    );
  }

  if (!isConnected) {
    return (
      <div className="wrap">
        <p className="lead">Connecting to MCP host…</p>
      </div>
    );
  }

  return (
    <div className="wrap">
      <h1>OpenAPI endpoint picker</h1>
      <p className="lead">
        Operations from <code>{specUrl || "—"}</code>. Select endpoints, then run export (calls{" "}
        <code>export_trimmed_openapi_spec</code> on this server).
      </p>
      {error ? <div className="err">{error}</div> : null}
      {rows.length > 0 && rows.length > platformMax ? (
        <div className="banner banner-warn">
          This spec has {rows.length} operations (platform typical max {platformMax}). Select at
          most {platformMax} for upload, or trim in multiple passes.
        </div>
      ) : null}
      {rows.length > 0 ? (
        <>
          <p className="lead" style={{ marginTop: "0.5rem" }}>
            {rows.length} operation(s). Selected: {selected.size}
            {overCap ? ` (over typical limit ${platformMax})` : ""}
          </p>
          <div className="tools">
            <input
              className="filter"
              type="search"
              placeholder="Filter by path, tag, operationId…"
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
                  <th style={{ width: 36 }}>Keep</th>
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
          <h2 style={{ fontSize: "1rem", marginTop: "12px" }}>Selection JSON</h2>
          <div className="out">{exportJson}</div>
          <div className="tools">
            <button
              type="button"
              className="btn"
              disabled={selected.size === 0 || exportBusy}
              onClick={runExport}
            >
              {exportBusy ? "Exporting…" : "Run export_trimmed_openapi_spec"}
            </button>
            <button type="button" className="btn btn-ghost" disabled={!exportResult} onClick={copyExport}>
              Copy export result
            </button>
          </div>
          {exportResult ? (
            <>
              <h2 style={{ fontSize: "1rem", marginTop: "8px" }}>Export tool result</h2>
              <div className="out">{exportResult}</div>
            </>
          ) : null}
        </>
      ) : !error ? (
        <p className="lead">Waiting for tool data from host…</p>
      ) : null}
    </div>
  );
}
