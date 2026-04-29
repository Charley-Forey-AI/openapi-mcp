/** Mirror of Python `enumerate_operations` / `operation_key` for the MCP export tool. */

import { load as yamlLoad } from "js-yaml";

const OAS3_HTTP = new Set([
  "get",
  "put",
  "post",
  "delete",
  "options",
  "head",
  "patch",
  "trace",
]);

const PATH_ITEM_NON = new Set([
  "parameters",
  "servers",
  "summary",
  "description",
  "$ref",
]);

export type OpRow = {
  method: string;
  path: string;
  operation_key: string;
  tags: string[];
  operation_id: string | null;
};

export function enumerateOperations(spec: Record<string, unknown>): OpRow[] {
  const paths = spec.paths;
  if (!paths || typeof paths !== "object") return [];
  const out: OpRow[] = [];
  for (const [path, item] of Object.entries(paths)) {
    if (typeof item !== "object" || item === null) continue;
    const pitem = item as Record<string, unknown>;
    for (const [method, rawOp] of Object.entries(pitem)) {
      if (PATH_ITEM_NON.has(method)) continue;
      const lower = method.toLowerCase();
      if (!OAS3_HTTP.has(lower)) continue;
      if (typeof rawOp !== "object" || rawOp === null) continue;
      const op = rawOp as Record<string, unknown>;
      let opId: string | null = null;
      if (typeof op.operationId === "string" && op.operationId.trim()) {
        opId = op.operationId.trim();
      }
      const tagList: string[] = [];
      if (Array.isArray(op.tags)) {
        for (const t of op.tags) {
          if (typeof t === "string" && t.trim()) tagList.push(t.trim());
        }
      }
      const m = lower.toUpperCase();
      const key = `${m} ${path}`;
      out.push({
        method: m,
        path,
        operation_key: key,
        tags: tagList,
        operation_id: opId,
      });
    }
  }
  return out;
}

export function parseSpecText(text: string): Record<string, unknown> {
  const t = text.trim();
  if (!t) throw new Error("Empty input");
  try {
    const j = JSON.parse(t) as unknown;
    if (typeof j === "object" && j !== null) {
      return j as Record<string, unknown>;
    }
    throw new Error("Not a JSON object");
  } catch {
    const y = yamlLoad(t) as unknown;
    if (typeof y === "object" && y !== null) {
      return y as Record<string, unknown>;
    }
    throw new Error("Invalid JSON or YAML");
  }
}
