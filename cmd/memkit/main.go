// Command memkit is a self-hostable memory server for AI agents: a single
// static binary exposing a small REST API backed by SQLite, with conflict-lens
// resolving contradictions on write.
package main

import (
	"context"
	"flag"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/voltagebots/memkit/internal/api"
	"github.com/voltagebots/memkit/internal/conflict"
	"github.com/voltagebots/memkit/internal/store"
)

func main() {
	addr := flag.String("addr", envOr("MEMKIT_ADDR", ":8080"), "listen address")
	dbPath := flag.String("db", envOr("MEMKIT_DB", "memkit.db"), "SQLite path (':memory:' for ephemeral)")
	flag.Parse()

	st, err := store.OpenSQLite(*dbPath)
	if err != nil {
		log.Fatalf("open store: %v", err)
	}
	defer st.Close()

	auth := parseAPIKeys(os.Getenv("MEMKIT_API_KEYS"))
	srv := api.New(st, conflict.NewEngine(), auth)

	httpSrv := &http.Server{
		Addr:              *addr,
		Handler:           srv.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	go func() {
		log.Printf("memkit listening on %s (db=%s, tenants=%d)", *addr, *dbPath, len(auth))
		if err := httpSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("serve: %v", err)
		}
	}()

	// Graceful shutdown on SIGINT/SIGTERM.
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	log.Print("shutting down…")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = httpSrv.Shutdown(ctx)
}

// parseAPIKeys reads "key1:tenant1,key2:tenant2" into a map. If unset, it falls
// back to a single dev key so `go run` works out of the box — with a loud
// warning, since that key must never reach production.
func parseAPIKeys(raw string) map[string]string {
	auth := map[string]string{}
	for _, pair := range strings.Split(raw, ",") {
		pair = strings.TrimSpace(pair)
		if pair == "" {
			continue
		}
		k, v, ok := strings.Cut(pair, ":")
		if ok && k != "" && v != "" {
			auth[strings.TrimSpace(k)] = strings.TrimSpace(v)
		}
	}
	if len(auth) == 0 {
		log.Print("WARNING: MEMKIT_API_KEYS unset — using dev key 'dev-key' → tenant 'default'. Do NOT use in production.")
		auth["dev-key"] = "default"
	}
	return auth
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
