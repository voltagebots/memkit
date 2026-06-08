// Command memkit-mcp is a thin MCP (Model Context Protocol) stdio bridge to a
// running memkit server. It lets any MCP client (Claude Code, Claude Desktop,
// Cursor, …) use memkit as its long-term memory backend without speaking REST.
//
// Protocol: newline-delimited JSON-RPC 2.0 over stdin/stdout. Only the handful
// of methods a tools server needs are implemented — initialize, tools/list,
// tools/call, ping — so it stays dependency-free.
//
// Config (env):
//
//	MEMKIT_URL      base URL of the memkit server (default http://localhost:8420)
//	MEMKIT_API_KEY  bearer token (tenant). Required.
//	MEMKIT_USER     user_id all memories are scoped to (default "default")
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

const serverName = "memkit-mcp"
const serverVersion = "0.1.0"

func main() {
	cfg := config{
		baseURL: envOr("MEMKIT_URL", "http://localhost:8420"),
		apiKey:  os.Getenv("MEMKIT_API_KEY"),
		user:    envOr("MEMKIT_USER", "default"),
		http:    &http.Client{Timeout: 15 * time.Second},
	}
	b := &bridge{cfg: cfg}

	in := bufio.NewScanner(os.Stdin)
	in.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	out := json.NewEncoder(os.Stdout)

	for in.Scan() {
		line := bytes.TrimSpace(in.Bytes())
		if len(line) == 0 {
			continue
		}
		var req rpcRequest
		if err := json.Unmarshal(line, &req); err != nil {
			continue // not valid JSON-RPC; ignore
		}
		resp, isNotification := b.handle(req)
		if isNotification {
			continue // notifications get no reply
		}
		if err := out.Encode(resp); err != nil {
			fmt.Fprintf(os.Stderr, "memkit-mcp: write: %v\n", err)
			return
		}
	}
}

// ── JSON-RPC plumbing ────────────────────────────────────────────────────────

type rpcRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id"` // absent for notifications
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params"`
}

type rpcResponse struct {
	JSONRPC string    `json:"jsonrpc"`
	ID      any       `json:"id"`
	Result  any       `json:"result,omitempty"`
	Error   *rpcError `json:"error,omitempty"`
}

type rpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type bridge struct{ cfg config }

type config struct {
	baseURL, apiKey, user string
	http                  *http.Client
}

func (b *bridge) handle(req rpcRequest) (rpcResponse, bool) {
	if len(req.ID) == 0 { // notification (e.g. notifications/initialized)
		return rpcResponse{}, true
	}
	var id any
	_ = json.Unmarshal(req.ID, &id)
	ok := func(result any) rpcResponse {
		return rpcResponse{JSONRPC: "2.0", ID: id, Result: result}
	}
	fail := func(code int, msg string) rpcResponse {
		return rpcResponse{JSONRPC: "2.0", ID: id, Error: &rpcError{Code: code, Message: msg}}
	}

	switch req.Method {
	case "initialize":
		return ok(b.initialize(req.Params)), false
	case "ping":
		return ok(map[string]any{}), false
	case "tools/list":
		return ok(map[string]any{"tools": toolList()}), false
	case "tools/call":
		res, err := b.callTool(req.Params)
		if err != nil {
			return fail(-32602, err.Error()), false
		}
		return ok(res), false
	default:
		return fail(-32601, "method not found: "+req.Method), false
	}
}

func (b *bridge) initialize(params json.RawMessage) map[string]any {
	// Echo the client's protocol version when supplied for clean negotiation.
	proto := "2025-06-18"
	var p struct {
		ProtocolVersion string `json:"protocolVersion"`
	}
	if json.Unmarshal(params, &p) == nil && p.ProtocolVersion != "" {
		proto = p.ProtocolVersion
	}
	return map[string]any{
		"protocolVersion": proto,
		"capabilities":    map[string]any{"tools": map[string]any{}},
		"serverInfo":      map[string]any{"name": serverName, "version": serverVersion},
	}
}

// ── tools ────────────────────────────────────────────────────────────────────

func toolList() []map[string]any {
	str := func(d string) map[string]any { return map[string]any{"type": "string", "description": d} }
	return []map[string]any{
		{
			"name":        "remember",
			"description": "Store a fact in long-term memory. memkit auto-resolves conflicts: a contradicting fact supersedes the old one, a restatement is deduped.",
			"inputSchema": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"content":  str("The fact to remember"),
					"category": str("Category, e.g. 'preferences', 'projects' (default 'general')"),
				},
				"required": []string{"content"},
			},
		},
		{
			"name":        "recall",
			"description": "Retrieve relevant memories for a query, ranked by relevance and recency. Returns only active (non-superseded) facts.",
			"inputSchema": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"query":    str("What to look for"),
					"category": str("Optional category filter"),
				},
				"required": []string{"query"},
			},
		},
		{
			"name":        "update_memory",
			"description": "Supersede a memory by ID with a corrected fact (old kept as history).",
			"inputSchema": map[string]any{
				"type":       "object",
				"properties": map[string]any{"id": str("Memory ID"), "content": str("Corrected fact")},
				"required":   []string{"id", "content"},
			},
		},
		{
			"name":        "forget",
			"description": "Permanently delete a memory by ID.",
			"inputSchema": map[string]any{
				"type": "object", "properties": map[string]any{"id": str("Memory ID")}, "required": []string{"id"},
			},
		},
		{
			"name":        "list_categories",
			"description": "List memory categories with counts.",
			"inputSchema": map[string]any{"type": "object", "properties": map[string]any{}},
		},
	}
}

type callParams struct {
	Name      string         `json:"name"`
	Arguments map[string]any `json:"arguments"`
}

func (b *bridge) callTool(params json.RawMessage) (map[string]any, error) {
	var p callParams
	if err := json.Unmarshal(params, &p); err != nil {
		return nil, err
	}
	arg := func(k string) string {
		if v, ok := p.Arguments[k].(string); ok {
			return v
		}
		return ""
	}

	var body string
	var err error
	switch p.Name {
	case "remember":
		body, err = b.req("POST", "/v1/memories", map[string]any{
			"user_id": b.cfg.user, "content": arg("content"), "category": orDefault(arg("category"), "general"),
		})
	case "recall":
		q := url.Values{"user_id": {b.cfg.user}, "q": {arg("query")}}
		if c := arg("category"); c != "" {
			q.Set("category", c)
		}
		body, err = b.req("GET", "/v1/memories/search?"+q.Encode(), nil)
	case "update_memory":
		body, err = b.req("PUT", "/v1/memories/"+url.PathEscape(arg("id")), map[string]any{"content": arg("content")})
	case "forget":
		body, err = b.req("DELETE", "/v1/memories/"+url.PathEscape(arg("id")), nil)
	case "list_categories":
		body, err = b.req("GET", "/v1/categories?user_id="+url.QueryEscape(b.cfg.user), nil)
	default:
		return nil, fmt.Errorf("unknown tool: %s", p.Name)
	}
	if err != nil {
		return textResult("memkit error: "+err.Error(), true), nil
	}
	return textResult(body, false), nil
}

func textResult(text string, isError bool) map[string]any {
	return map[string]any{
		"content": []map[string]any{{"type": "text", "text": text}},
		"isError": isError,
	}
}

func (b *bridge) req(method, path string, payload any) (string, error) {
	if b.cfg.apiKey == "" {
		return "", fmt.Errorf("MEMKIT_API_KEY not set")
	}
	var rdr io.Reader
	if payload != nil {
		raw, _ := json.Marshal(payload)
		rdr = bytes.NewReader(raw)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, method, b.cfg.baseURL+path, rdr)
	if err != nil {
		return "", err
	}
	req.Header.Set("Authorization", "Bearer "+b.cfg.apiKey)
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := b.cfg.http.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	out, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		return "", fmt.Errorf("status %d: %s", resp.StatusCode, strings.TrimSpace(string(out)))
	}
	return string(out), nil
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
func orDefault(s, def string) string {
	if s == "" {
		return def
	}
	return s
}
