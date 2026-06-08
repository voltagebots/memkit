package store

import "errors"

// ErrNotFound is returned when a memory does not exist for the given tenant.
var ErrNotFound = errors.New("memory not found")
