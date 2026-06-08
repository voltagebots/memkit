# Pure-Go build (CGO disabled — modernc SQLite needs no C toolchain), so the
# binary is fully static and runs on distroless static as non-root.
FROM golang:1.26-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /memkit ./cmd/memkit
# Pre-create a data dir owned by the distroless nonroot uid (65532) so the
# default DB path is writable without a shell in the final image.
RUN mkdir -p /data && chown 65532:65532 /data

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /memkit /memkit
COPY --from=builder --chown=65532:65532 /data /data
ENV MEMKIT_DB=/data/memkit.db
VOLUME /data
EXPOSE 8080
USER 65532:65532
ENTRYPOINT ["/memkit"]
