// Package maintenance runs periodic background upkeep on the store: pruning
// archived (superseded) facts past a retention window so the database stays
// lean while recent history is preserved.
//
// Recency *decay* is applied at read time in the store's scoring; this loop
// handles the write-side consolidation that scoring can't: reclaiming space.
package maintenance

import (
	"context"
	"log"
	"time"

	"github.com/voltagebots/memkit/internal/store"
)

// Maintainer periodically prunes superseded memories older than Retention.
type Maintainer struct {
	Store     store.Store
	Interval  time.Duration // how often to run (e.g. 1h)
	Retention time.Duration // archived facts older than this are removed (e.g. 720h)
	Logf      func(string, ...any)
}

// New builds a Maintainer with sane defaults for any zero fields.
func New(s store.Store, interval, retention time.Duration) *Maintainer {
	if interval <= 0 {
		interval = time.Hour
	}
	if retention <= 0 {
		retention = 30 * 24 * time.Hour
	}
	return &Maintainer{Store: s, Interval: interval, Retention: retention, Logf: log.Printf}
}

// Run blocks, running one pass every Interval until ctx is cancelled. Intended
// to be launched in its own goroutine.
func (m *Maintainer) Run(ctx context.Context) {
	ticker := time.NewTicker(m.Interval)
	defer ticker.Stop()
	m.Logf("maintenance loop started (interval=%s, retention=%s)", m.Interval, m.Retention)
	for {
		select {
		case <-ctx.Done():
			m.Logf("maintenance loop stopped")
			return
		case <-ticker.C:
			m.runOnce(ctx)
		}
	}
}

func (m *Maintainer) runOnce(ctx context.Context) {
	cutoff := time.Now().Add(-m.Retention)
	n, err := m.Store.PruneSuperseded(ctx, cutoff)
	if err != nil {
		m.Logf("maintenance: prune failed: %v", err)
		return
	}
	if n > 0 {
		m.Logf("maintenance: pruned %d superseded memories older than %s", n, m.Retention)
	}
}
