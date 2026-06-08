// Package resolver provides a Claude-backed implementation of the conflict-lens
// Resolver interface. conflict-lens stays dependency-free; the LLM dependency
// lives here, in memkit, where it's opt-in.
//
// The Resolver is consulted only for the ambiguous similarity band, so cost is
// bounded: clear adds/duplicates/conflicts are decided by the cheap heuristic
// and never reach the API.
package resolver

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	conflict "github.com/voltagebots/conflict-lens"
)

const (
	defaultEndpoint = "https://api.anthropic.com/v1/messages"
	defaultModel    = "claude-haiku-4-5-20251001" // small + fast: per-conflict judgments
	anthropicVer    = "2023-06-01"
)

// The classification instructions are stable across calls, so they go in the
// system block with cache_control to hit the prompt cache. Only the two facts
// vary per request (in the user message).
const systemPrompt = `You judge how a NEW fact relates to an EXISTING fact about the same user.
Reply with ONLY a compact JSON object: {"action":"<add|update|duplicate>","reason":"<≤8 words>"}.
- "update": the new fact CONTRADICTS or replaces the existing one (e.g. changed job, switched preference, reversed sentiment). The existing fact should be archived.
- "duplicate": the new fact RESTATES the existing one with no new information.
- "add": the new fact is COMPATIBLE and adds information (both can be true at once).
Output JSON only, no prose.`

// Claude implements conflict.Resolver via the Anthropic Messages API.
type Claude struct {
	APIKey   string
	Model    string
	Endpoint string
	HTTP     *http.Client
}

// NewClaude builds a resolver. model/endpoint fall back to sane defaults.
func NewClaude(apiKey, model string) *Claude {
	if model == "" {
		model = defaultModel
	}
	return &Claude{
		APIKey:   apiKey,
		Model:    model,
		Endpoint: defaultEndpoint,
		HTTP:     &http.Client{Timeout: 12 * time.Second},
	}
}

// Resolve asks Claude to classify the relationship. On any error it returns the
// error so the engine can fall back to its heuristic (which favours preserving
// history). Implements conflict.Resolver.
func (c *Claude) Resolve(newContent string, candidate conflict.Fact) (conflict.Action, string, error) {
	reqBody := messagesRequest{
		Model:     c.Model,
		MaxTokens: 64,
		System: []systemBlock{{
			Type:         "text",
			Text:         systemPrompt,
			CacheControl: &cacheControl{Type: "ephemeral"},
		}},
		Messages: []message{{
			Role: "user",
			Content: fmt.Sprintf("EXISTING: %s\nNEW: %s",
				strings.TrimSpace(candidate.Content), strings.TrimSpace(newContent)),
		}},
	}
	raw, err := json.Marshal(reqBody)
	if err != nil {
		return conflict.ActionAdd, "", err
	}

	ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.Endpoint, bytes.NewReader(raw))
	if err != nil {
		return conflict.ActionAdd, "", err
	}
	req.Header.Set("content-type", "application/json")
	req.Header.Set("x-api-key", c.APIKey)
	req.Header.Set("anthropic-version", anthropicVer)

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return conflict.ActionAdd, "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return conflict.ActionAdd, "", fmt.Errorf("anthropic: status %d", resp.StatusCode)
	}

	var mr messagesResponse
	if err := json.NewDecoder(resp.Body).Decode(&mr); err != nil {
		return conflict.ActionAdd, "", err
	}
	text := mr.firstText()
	if text == "" {
		return conflict.ActionAdd, "", fmt.Errorf("anthropic: empty response")
	}
	return parseDecision(text)
}

func parseDecision(text string) (conflict.Action, string, error) {
	// Be tolerant: extract the first {...} object from the reply.
	start, end := strings.IndexByte(text, '{'), strings.LastIndexByte(text, '}')
	if start < 0 || end <= start {
		return conflict.ActionAdd, "", fmt.Errorf("no JSON in response: %q", text)
	}
	var d struct {
		Action string `json:"action"`
		Reason string `json:"reason"`
	}
	if err := json.Unmarshal([]byte(text[start:end+1]), &d); err != nil {
		return conflict.ActionAdd, "", err
	}
	reason := "llm: " + d.Reason
	switch strings.ToLower(strings.TrimSpace(d.Action)) {
	case "update":
		return conflict.ActionUpdate, reason, nil
	case "duplicate":
		return conflict.ActionDuplicate, reason, nil
	case "add":
		return conflict.ActionAdd, reason, nil
	default:
		return conflict.ActionAdd, "", fmt.Errorf("unknown action %q", d.Action)
	}
}

// ── Anthropic wire types ─────────────────────────────────────────────────────

type messagesRequest struct {
	Model     string        `json:"model"`
	MaxTokens int           `json:"max_tokens"`
	System    []systemBlock `json:"system"`
	Messages  []message     `json:"messages"`
}

type systemBlock struct {
	Type         string        `json:"type"`
	Text         string        `json:"text"`
	CacheControl *cacheControl `json:"cache_control,omitempty"`
}

type cacheControl struct {
	Type string `json:"type"`
}

type message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type messagesResponse struct {
	Content []struct {
		Type string `json:"type"`
		Text string `json:"text"`
	} `json:"content"`
}

func (m messagesResponse) firstText() string {
	for _, c := range m.Content {
		if c.Type == "text" && c.Text != "" {
			return c.Text
		}
	}
	return ""
}
