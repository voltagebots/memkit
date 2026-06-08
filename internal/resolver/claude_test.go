package resolver

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	conflict "github.com/voltagebots/conflict-lens"
)

// mockAnthropic returns a server that replies with the given assistant text and
// captures the last request body for assertions.
func mockAnthropic(t *testing.T, replyText string, captured *map[string]any) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("x-api-key") == "" {
			t.Error("missing x-api-key header")
		}
		if r.Header.Get("anthropic-version") == "" {
			t.Error("missing anthropic-version header")
		}
		body, _ := io.ReadAll(r.Body)
		if captured != nil {
			_ = json.Unmarshal(body, captured)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"content": []map[string]any{{"type": "text", "text": replyText}},
		})
	}))
}

func newResolver(url string) *Claude {
	c := NewClaude("test-key", "")
	c.Endpoint = url
	return c
}

func TestClaudeResolve_Update(t *testing.T) {
	var captured map[string]any
	srv := mockAnthropic(t, `{"action":"update","reason":"sentiment reversed"}`, &captured)
	defer srv.Close()

	act, reason, err := newResolver(srv.URL).Resolve("I hate my job", conflict.Fact{ID: "x", Content: "I love my job"})
	if err != nil {
		t.Fatal(err)
	}
	if act != conflict.ActionUpdate {
		t.Fatalf("want update, got %s", act)
	}
	if !strings.Contains(reason, "sentiment reversed") {
		t.Fatalf("reason not propagated: %q", reason)
	}

	// The stable system prompt must carry cache_control (prompt caching).
	sys, _ := captured["system"].([]any)
	if len(sys) == 0 {
		t.Fatal("system block missing")
	}
	if _, ok := sys[0].(map[string]any)["cache_control"]; !ok {
		t.Fatal("system block must set cache_control for prompt caching")
	}
}

func TestClaudeResolve_AddAndDuplicate(t *testing.T) {
	for _, tc := range []struct {
		reply string
		want  conflict.Action
	}{
		{`{"action":"add","reason":"compatible"}`, conflict.ActionAdd},
		{`{"action":"duplicate","reason":"restated"}`, conflict.ActionDuplicate},
	} {
		srv := mockAnthropic(t, tc.reply, nil)
		act, _, err := newResolver(srv.URL).Resolve("new", conflict.Fact{Content: "old"})
		srv.Close()
		if err != nil || act != tc.want {
			t.Fatalf("reply %s: want %s, got %s (err=%v)", tc.reply, tc.want, act, err)
		}
	}
}

func TestClaudeResolve_ToleratesProseWrappedJSON(t *testing.T) {
	srv := mockAnthropic(t, "Sure!\n{\"action\":\"update\",\"reason\":\"x\"} done", nil)
	defer srv.Close()
	act, _, err := newResolver(srv.URL).Resolve("a", conflict.Fact{Content: "b"})
	if err != nil || act != conflict.ActionUpdate {
		t.Fatalf("want update from wrapped JSON, got %s err=%v", act, err)
	}
}

func TestClaudeResolve_ErrorOnNon200(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusTooManyRequests)
	}))
	defer srv.Close()
	if _, _, err := newResolver(srv.URL).Resolve("a", conflict.Fact{Content: "b"}); err == nil {
		t.Fatal("want error on non-200 so the engine can fall back to heuristic")
	}
}
